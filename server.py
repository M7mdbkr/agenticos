"""No-dependency local HTTP server for Personal OS."""
from __future__ import annotations

import argparse
import cgi
import json
import mimetypes
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from functools import wraps
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlparse, quote

# Load .env file manually (no pip needed)
_ENV_FILE = Path(__file__).resolve().parent / ".env"
if _ENV_FILE.exists():
    for line in _ENV_FILE.read_text().splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

from personal_os import OperationsStore

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("PERSONAL_OS_DATA_DIR", str(ROOT / "data")))
STORE = OperationsStore(DATA / "personal-os.db", ROOT / "uploads", ROOT / "browser-profiles")
MAX_UPLOAD = 25 * 1024 * 1024
STORE_LOCK = threading.RLock()
AGENT_LOCKS = {}
BRAIN_SLOTS = threading.BoundedSemaphore(2)
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_POLLING_RUNNING = False
TELEGRAM_POLLING_STOP = threading.Event()
TELEGRAM_PENDING = []  # incoming updates from polling thread
TELEGRAM_LOCK = threading.Lock()


def store_request(method):
    @wraps(method)
    def guarded(self):
        with STORE_LOCK:
            return method(self)
    return guarded


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def fetch_rss(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mohammad-Personal-OS/1.0"})
    with urllib.request.urlopen(req, timeout=12) as response:
        payload = response.read(2_000_000)
    root = ET.fromstring(payload)
    items = []
    for node in root.findall(".//item")[:20]:
        title = (node.findtext("title") or "").strip()
        link = (node.findtext("link") or "").strip()
        desc = (node.findtext("description") or "").strip()
        if title and link:
            items.append((title, desc[:1000], link, node.findtext("pubDate")))
    if not items:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for node in root.findall(".//a:entry", ns)[:20]:
            link_node = node.find("a:link", ns)
            title = (node.findtext("a:title", default="", namespaces=ns)).strip()
            link = link_node.attrib.get("href", "") if link_node is not None else ""
            desc = node.findtext("a:summary", default="", namespaces=ns).strip()
            if title and link:
                items.append((title, desc[:1000], link, node.findtext("a:updated", default="", namespaces=ns)))
    return items


# ── Telegram polling ──────────────────────────────────────────────────────────

def _telegram_api(method: str, data: dict = None) -> dict:
    """Call Telegram Bot API method."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/{method}"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    payload = json.dumps(data or {}).encode("utf-8") if data else None
    if payload:
        req.data = payload
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API error: {result}")
    return result.get("result", [])


def _telegram_send(chat_id: str, text: str, parse: str = "Markdown") -> dict:
    """Send a text message to a Telegram chat."""
    return _telegram_api("sendMessage", {"chat_id": chat_id, "text": text, "parse_mode": parse})


def _telegram_voice(file_id: str) -> dict:
    """Get a voice file from Telegram."""
    return _telegram_api("getFile", {"file_id": file_id})


def _telegram_poll(offset: int = 0, timeout: int = 30) -> list:
    """Long-poll Telegram updates."""
    return _telegram_api("getUpdates", {"offset": offset, "timeout": timeout, "allowed_updates": ["message"]})


def _telegram_download_url(file_path: str) -> str:
    return f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}"


def _telegram_voice_to_text(file_id: str) -> str:
    """Download voice file and transcribe via Web Speech API (client-side)."""
    # The audio file URL is returned; transcription happens in-browser via TTS/STTS
    return file_id  # placeholder – actual transcription done client-side


def telegram_polling_thread(bot_token: str, update_queue: list) -> None:
    """Background thread: poll Telegram, push text messages into the queue."""
    global TELEGRAM_POLLING_RUNNING
    TELEGRAM_POLLING_RUNNING = True
    offset = 0
    while not TELEGRAM_POLLING_STOP.is_set():
        try:
            updates = _telegram_poll(offset, timeout=20)
        except Exception as e:
            sys.stderr.write(f"[Telegram poll error] {e}\n")
            time.sleep(5)
            continue
        for upd in updates:
            offset = max(offset, upd["update_id"] + 1)
            msg = upd.get("message", {})
            chat = msg.get("chat", {})
            text = msg.get("text") or ""
            voice = msg.get("voice")
            if text and _jobhunter_telegram(str(chat.get("id", "")), text):
                continue
            # Only handle text or voice messages
            if text or voice:
                update_queue.append({
                    "chat_id": str(chat.get("id", "")),
                    "chat_title": chat.get("title", "") or f"{chat.get('first_name','')} {chat.get('last_name','')}".strip(),
                    "text": text,
                    "voice_file_id": voice.get("file_id") if voice else None,
                    "from_first": msg.get("from", {}).get("first_name", ""),
                    "from_last": msg.get("from", {}).get("last_name", ""),
                    "update_id": upd["update_id"],
                })
    TELEGRAM_POLLING_RUNNING = False


def start_telegram_polling() -> bool:
    """Start the background Telegram polling thread. Returns True if started."""
    global TELEGRAM_BOT_TOKEN, TELEGRAM_POLLING_STOP
    if not TELEGRAM_BOT_TOKEN:
        return False
    TELEGRAM_POLLING_STOP.clear()
    t = threading.Thread(target=telegram_polling_thread, args=(TELEGRAM_BOT_TOKEN, TELEGRAM_PENDING), daemon=True, name="telegram-polling")
    t.start()
    return True


# ── Job Hunter agent (jobhunter/) ─────────────────────────────────────────────

JOBHUNTER = None
JOBHUNTER_LOCK = threading.Lock()
CV_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".rtf", ".odt"}


def _job_source_feeds() -> list:
    """RSS feeds from the Job sources page feed the job hunter too."""
    with STORE_LOCK:
        sources = STORE.list_resources("job_sources")
    return [s.get("url", "") for s in sources if s.get("enabled") and "rss" in str(s.get("kind", "")).lower()
            and str(s.get("url", "")).startswith(("http://", "https://"))]


def get_hunter():
    global JOBHUNTER
    with JOBHUNTER_LOCK:
        if JOBHUNTER is None:
            from jobhunter import JobHunter
            JOBHUNTER = JobHunter(data_dir=DATA / "jobhunter", extra_feeds=_job_source_feeds)
        return JOBHUNTER


def _jobhunter_telegram(chat_id: str, text: str) -> bool:
    """Route '/jobs …' Telegram messages from the chat set in Job Hunter settings. True when handled."""
    if not re.match(r"^/?(jobs?|jh)\b", text.strip(), re.I):
        return False
    try:
        hunter = get_hunter()
        allowed = hunter.profile()["telegram_chat_id"]
    except Exception:
        return False
    if not allowed or allowed != chat_id:
        return False
    body = re.sub(r"^/?(jobs?|jh)(@\w+)?\b[:\s]*", "", text.strip(), flags=re.I).strip() or "jobs"

    def answer():
        from jobhunter.notify import telegram_send
        try:
            reply = hunter.handle_text(body, channel="telegram")
        except Exception as exc:
            reply = f"Job Hunter error: {exc}"
        telegram_send(TELEGRAM_BOT_TOKEN, chat_id, reply)

    threading.Thread(target=answer, daemon=True, name="jobhunter-telegram").start()
    return True


class Handler(BaseHTTPRequestHandler):
    server_version = "PersonalOS/1.0"

    def parse_request(self):
        if not super().parse_request():
            return False
        port = cast(ThreadingHTTPServer, self.server).server_port
        hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
        if self.headers.get("Host") not in hosts:
            self.send_json({"error": "Localhost access only"}, 403)
            return False
        origin = self.headers.get("Origin")
        if (origin and origin not in {f"http://{host}" for host in hosts}) or self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.send_json({"error": "Cross-origin access is not allowed"}, 403)
            return False
        return True

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def send_json(self, value, status=200):
        body = json_bytes(value)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers(); self.wfile.write(body)

    def body_json(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size > MAX_UPLOAD:
            raise ValueError("Request too large")
        return json.loads(self.rfile.read(size) or b"{}")

    def static(self, path):
        allowed = path in {"/", "/index.html", "/README.md"} or path.startswith(("/static/", "/docs/"))
        if not allowed:
            return self.send_error(404)
        target = ROOT / ("index.html" if path == "/" else path.lstrip("/"))
        try:
            target = target.resolve()
            if ROOT.resolve() not in target.parents and target != ROOT.resolve():
                raise FileNotFoundError
            relative = target.relative_to(ROOT.resolve())
            if relative.parts[0] not in {"static", "docs", "index.html", "README.md"}:
                raise FileNotFoundError
            data = target.read_bytes()
        except (OSError, ValueError):
            return self.send_error(404)
        kind = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200); self.send_header("Content-Type", kind)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data))); self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers(); self.wfile.write(data)

    def do_GET(self):
        if urlparse(self.path).path.startswith("/api/jobhunter/"):
            return self.jobhunter_request("GET")
        return self._get_core()

    @store_request
    def _get_core(self):
        global TELEGRAM_BOT_TOKEN
        parsed = urlparse(self.path); path = parsed.path
        try:
            if path == "/api/health":
                return self.send_json({"ok": True, "version": "1.1", "runtime": "cli-chat", "loopback": cast(ThreadingHTTPServer, self.server).server_name, "scheduler": "not-configured", "capabilities": ["chat", "drafts"]})
            if path == "/api/brains":
                from brains import provider_status
                return self.send_json(provider_status())
            if path == "/api/agents": return self.send_json(STORE.list_agents())
            if path.startswith("/api/agents/") and path.endswith("/messages"):
                return self.send_json(STORE.messages(path.split("/")[3]))
            if path == "/api/actions": return self.send_json(STORE.list_actions())
            if path.startswith("/api/resources/"): return self.send_json(STORE.list_resources(path.split("/")[3]))
            if path == "/api/uploads": return self.send_json(STORE.list_uploads())
            if path == "/api/news": return self.send_json(STORE.list_news())
            if path == "/api/audit": return self.send_json(STORE.audit_events())
            if path == "/api/n8n/webhooks": return self.send_json(STORE.list_resources("n8n_webhooks"))
            if path == "/api/n8n/status":
                import urllib.request
                base = os.environ.get("N8N_BASE_URL", "http://localhost:5678")
                try:
                    req = urllib.request.Request(base + "/rest/settings", headers={"Accept": "application/json"})
                    with urllib.request.urlopen(req, timeout=3) as r:
                        data = json.loads(r.read())
                    return self.send_json({"connected": True, "base_url": base, "version": data.get("version", "unknown")})
                except Exception:
                    return self.send_json({"connected": False, "base_url": base})
            if path == "/api/activity": return self.send_json(STORE.recent_activity())
            if path == "/api/telegram/status":
                return self.send_json({
                    "bot_token_set": bool(TELEGRAM_BOT_TOKEN),
                    "polling": TELEGRAM_POLLING_RUNNING,
                })
            if path == "/api/telegram/configure" and self.method == "POST":
                data = self.body_json()
                token = str(data.get("token", "")).strip()
                if not token:
                    return self.send_json({"error": "token is required"}, 400)
                # Validate token against Telegram
                test_url = f"https://api.telegram.org/bot{token}/getMe"
                try:
                    req = urllib.request.Request(test_url)
                    with urllib.request.urlopen(req, timeout=5) as r:
                        result = json.loads(r.read())
                    if not result.get("ok"):
                        return self.send_json({"error": "Invalid bot token"}, 401)
                except Exception as e:
                    return self.send_json({"error": f"Could not reach Telegram: {e}"}, 502)
                # Save token to .env
                env_path = ROOT / ".env"
                lines = []
                if env_path.exists():
                    lines = env_path.read_text().splitlines()
                # Replace or append TELEGRAM_BOT_TOKEN
                found = False
                new_lines = []
                for line in lines:
                    if line.strip().startswith("TELEGRAM_BOT_TOKEN"):
                        new_lines.append(f'TELEGRAM_BOT_TOKEN={token}')
                        found = True
                    else:
                        new_lines.append(line)
                if not found:
                    new_lines.append(f'TELEGRAM_BOT_TOKEN={token}')
                env_path.write_text("\n".join(new_lines) + "\n")
                TELEGRAM_BOT_TOKEN = token
                os.environ["TELEGRAM_BOT_TOKEN"] = token  # visible to the job hunter too
                # Start polling
                start_telegram_polling()
                return self.send_json({"ok": True, "bot_username": result.get("result", {}).get("username", "unknown")})
            if path == "/api/telegram/sessions":
                return self.send_json(STORE.list_telegram_sessions())
            if path == "/api/telegram/pending":
                with TELEGRAM_LOCK:
                    pending = list(TELEGRAM_PENDING)
                    TELEGRAM_PENDING.clear()
                return self.send_json({"messages": pending})
            if path == "/api/telegram/send":
                data = self.body_json()
                chat_id = str(data.get("chat_id", "")).strip()
                text = str(data.get("text", "")).strip()
                if not chat_id or not text:
                    return self.send_json({"error": "chat_id and text are required"}, 400)
                try:
                    result = _telegram_send(chat_id, text)
                    return self.send_json({"ok": True, "message_id": result.get("message_id")})
                except Exception as e:
                    return self.send_json({"ok": False, "error": str(e)}, 502)
            if path == "/api/telegram/link":
                data = self.body_json()
                chat_id = str(data.get("chat_id", "")).strip()
                agent_slug = str(data.get("agent_slug", "")).strip()
                if not chat_id or not agent_slug:
                    return self.send_json({"error": "chat_id and agent_slug are required"}, 400)
                try:
                    return self.send_json(STORE.telegram_register(chat_id, agent_slug))
                except KeyError:
                    return self.send_json({"error": "Agent not found"}, 404)
            if path == "/api/telegram/voice-url":
                data = self.body_json()
                file_id = str(data.get("file_id", "")).strip()
                if not file_id:
                    return self.send_json({"error": "file_id is required"}, 400)
                try:
                    file_info = _telegram_voice(file_id)
                    path_ = file_info.get("file_path", "")
                    return self.send_json({"url": _telegram_download_url(path_), "file_path": path_})
                except Exception as e:
                    return self.send_json({"error": str(e)}, 502)
            if path == "/api/telegram/forward":
                # Forward an agent reply to a Telegram chat
                data = self.body_json()
                chat_id = str(data.get("chat_id", "")).strip()
                agent_slug = str(data.get("agent_slug", "")).strip()
                text = str(data.get("text", "")).strip()
                if not all([chat_id, agent_slug, text]):
                    return self.send_json({"error": "chat_id, agent_slug, and text are required"}, 400)
                try:
                    _telegram_send(chat_id, f"*{agent_slug.upper()}*: {text}")
                    return self.send_json({"ok": True})
                except Exception as e:
                    return self.send_json({"ok": False, "error": str(e)}, 502)
            if path == "/api/delegations":
                return self.send_json(STORE.list_delegations())
            if path == "/api/delegations/pending":
                return self.send_json(STORE.list_delegations(status="pending"))
            if path.startswith("/api/delegations/"):
                parts = path.split("/")
                if len(parts) == 5 and parts[3]:
                    return self.send_json(STORE.update_delegation_status(parts[3], self.body_json().get("status", "done")))
                delegations = STORE.list_delegations(agent_slug=parts[3] if len(parts) > 3 else None)
                return self.send_json(delegations)
            if path == "/api/connectors/status":
                obsidian = str(Path.home() / "Desktop" / "Personal-OS" / "vault")
                notion_key_set = bool(os.environ.get("NOTION_API_KEY"))
                return self.send_json({
                    "hermes": {"connected": True, "version": "1.0"},
                    "obsidian": {"connected": Path(obsidian).exists(), "vault_path": obsidian},
                    "notion": {"connected": notion_key_set, "note": "OAuth MCP active in Hermes" if notion_key_set else "Set NOTION_API_KEY for REST API access"},
                    "telegram": {
                        "connected": bool(TELEGRAM_BOT_TOKEN),
                        "note": "Bot token set" if TELEGRAM_BOT_TOKEN else "Set TELEGRAM_BOT_TOKEN to connect"
                    },
                    "linkedin": {
                        "connected": bool(os.environ.get("LINKEDIN_ACCESS_TOKEN")),
                        "note": "Set LINKEDIN_ACCESS_TOKEN for LinkedIn job posting"
                    },
                    "gmail": {
                        "connected": bool(os.environ.get("GMAIL_ACCESS_TOKEN")),
                        "note": "Set GMAIL_ACCESS_TOKEN for Gmail sending"
                    },
                    "google_sheets": {
                        "connected": bool(os.environ.get("GOOGLE_SHEETS_TOKEN")),
                        "note": "Set GOOGLE_SHEETS_TOKEN for spreadsheet updates"
                    },
                })
            if path.startswith("/api/browser/"):
                return self.send_json(STORE.browser_profile(path.split("/")[3]))
            # Job applications API
            if path == "/api/jobs":
                return self.send_json(STORE.list_job_applications())
            if path == "/api/linkedin/accounts":
                return self.send_json(STORE.list_linkedin_accounts())
            if path.startswith("/api/jobs/"):
                parts = path.split("/")
                if len(parts) == 4 and parts[3]:
                    return self.send_json(STORE.get_job_application(parts[3]))
            # Base resume API
            if path == "/api/resume":
                return self.send_json(STORE.get_base_resume() or {})
            return self.static(path)
        except (KeyError, ValueError) as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"error": "Internal error", "detail": str(exc)}, 500)

    def jobhunter_request(self, method):
        """Job Hunter API. Runs outside STORE_LOCK: searches and brain calls can take a while."""
        parsed = urlparse(self.path)
        path = parsed.path[len("/api/jobhunter"):]
        query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
        try:
            hunter = get_hunter()
            if method == "GET":
                if path == "/status":
                    return self.send_json(hunter.status())
                if path == "/profile":
                    return self.send_json(hunter.profile())
                if path == "/jobs":
                    statuses = [s for s in query.get("status", "").split(",") if s]
                    return self.send_json(hunter.store.list_jobs(
                        statuses=statuses or None, min_score=int(query.get("min_score") or 0), query=query.get("q", "")[:100],
                        limit=int(query.get("limit") or 200), order=query.get("order", "score")))
                if path.startswith("/jobs/"):
                    return self.send_json(hunter.store.get_job(path.split("/")[2]))
                if path == "/drafts":
                    return self.send_json(hunter.store.list_drafts())
                if path == "/activity":
                    return self.send_json({"events": hunter.store.events(80), "mail": hunter.store.mail_log(80)})
                return self.send_json({"error": "Not found"}, 404)
            if path == "/cv":
                return self.jobhunter_cv(hunter)
            data = self.body_json()
            if not isinstance(data, dict):
                raise ValueError("JSON object expected")
            if path == "/profile":
                return self.send_json(hunter.update_profile(data))
            if path == "/ask":
                text = str(data.get("text", "")).strip()
                if not text or len(text) > 4000:
                    return self.send_json({"error": "Enter a command or question (max 4,000 characters)"}, 400)
                return self.send_json({"reply": hunter.handle_text(text, channel="web")})
            if path == "/search":
                terms = str(data.get("query", "")).strip()[:200]
                if not terms:
                    return self.send_json({"error": "query is required"}, 400)
                report = hunter.search(query=terms, location=str(data.get("location", "")).strip()[:120] or None,
                                       reason="search in the app", notify=False)
                if report.get("busy"):
                    return self.send_json({"error": "A search is already running — try again in a minute"}, 409)
                return self.send_json({"results": report["results"][:50], "errors": report["errors"],
                                       "per_source": report["per_source"], "fetched": report["fetched"]})
            if path == "/run":
                threading.Thread(target=hunter.search, kwargs={"reason": "requested in the app"}, daemon=True).start()
                return self.send_json({"started": True}, 202)
            if path == "/inbox":
                return self.send_json(hunter.check_inbox())
            if path == "/start":
                result = hunter.start()
                if result.get("running"):
                    hunter.update_profile({"autostart": True})
                return self.send_json(result, 200 if result.get("running") else 409)
            if path == "/stop":
                hunter.update_profile({"autostart": False})
                return self.send_json(hunter.stop())
            if path == "/email":
                return self.jobhunter_email(hunter, data)
            if path == "/email/test":
                used = hunter.notify_owner("✅ Job Hunter is connected",
                                           "This is a test from your Job Hunter agent. Reply \"status\" or \"help\" "
                                           "and I'll answer within a few minutes while I'm running.", kind="notice")
                return self.send_json({"sent": used}, 200 if used.get("email") else 502)
            if path == "/jobs":
                url = str(data.get("url", "")).strip()
                if not url.startswith(("https://", "http://")):
                    return self.send_json({"error": "A job link (https://…) is required"}, 400)
                return self.send_json({"message": hunter.track_url(url, str(data.get("title", "")).strip()[:200])}, 201)
            if path.startswith("/jobs/"):
                parts = path.split("/")
                if len(parts) != 4:
                    return self.send_json({"error": "Not found"}, 404)
                job_id, action = parts[2].upper(), parts[3]
                actions = {"apply": hunter.prepare_application, "send": hunter.send_draft, "cancel": hunter.cancel_draft,
                           "applied": hunter.mark_applied, "followup": hunter.draft_followup, "open": hunter.open_job}
                statuses = {"skip": "skipped", "save": "interested", "interview": "interview", "assessment": "assessment",
                            "offer": "offer", "rejected": "rejected", "close": "closed", "reopen": "interested"}
                if action in actions:
                    message = actions[action](job_id)
                elif action in statuses:
                    message = hunter.set_status(job_id, statuses[action])
                elif action == "reply":
                    message = hunter.draft_reply(job_id, str(data.get("text", "")).strip()[:4000])
                else:
                    return self.send_json({"error": "Unknown action"}, 404)
                return self.send_json({"message": message, "job": hunter.store.get_job(job_id)})
            if path.startswith("/drafts/"):
                draft = hunter.store.get_draft(path.split("/")[2])
                if draft["status"] != "draft":
                    return self.send_json({"error": "This email was already sent or cancelled"}, 409)
                changes = {k: str(data[k])[:20000] for k in ("to_addr", "subject", "body") if k in data}
                if "to_addr" in changes and "@" not in changes["to_addr"]:
                    return self.send_json({"error": "Enter a valid email address"}, 400)
                return self.send_json(hunter.store.update_draft(draft["id"], **changes))
            return self.send_json({"error": "Not found"}, 404)
        except KeyError as exc:
            return self.send_json({"error": str(exc).strip("'\"")}, 404)
        except ValueError as exc:
            return self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            return self.send_json({"error": "Job Hunter error", "detail": str(exc)}, 500)

    def jobhunter_email(self, hunter, data):
        from jobhunter.config import mail_settings, save_env_values
        from jobhunter.mailbox import Mailbox, MailError
        address = str(data.get("address", "")).strip()
        if "@" not in address:
            return self.send_json({"error": "Enter the email address the agent should use"}, 400)
        values = {"JOBHUNTER_EMAIL": address}
        password = str(data.get("password", "")).replace(" ", "").strip()
        if password:
            values["JOBHUNTER_EMAIL_PASSWORD"] = password
        for key, env_key in (("imap_host", "JOBHUNTER_IMAP_HOST"), ("smtp_host", "JOBHUNTER_SMTP_HOST"),
                             ("smtp_port", "JOBHUNTER_SMTP_PORT")):
            value = str(data.get(key, "")).strip()
            if value:
                values[env_key] = value
        settings = mail_settings({**os.environ, **values})
        if not settings.configured:
            return self.send_json({"error": "Add the app password (and IMAP/SMTP servers for non-Gmail/Outlook/Yahoo/iCloud addresses)"}, 400)
        try:
            Mailbox(settings).test()
        except MailError as exc:
            return self.send_json({"error": str(exc)}, 400)
        save_env_values(values, ROOT / ".env")
        owners = data.get("owner_emails")
        if owners:
            hunter.update_profile({"owner_emails": owners})
        hunter.store.event("agent", f"Email connected: {address}")
        return self.send_json({"ok": True, "email": settings.public()})

    def jobhunter_cv(self, hunter):
        size = int(self.headers.get("Content-Length", "0"))
        name = Path(self.headers.get("X-Filename", "cv.pdf")).name
        if not 0 < size <= 10 * 1024 * 1024:
            return self.send_json({"error": "CV must be between 1 byte and 10 MB"}, 400)
        if Path(name).suffix.lower() not in CV_EXTENSIONS:
            return self.send_json({"error": "Upload a PDF, DOCX, DOC, ODT, RTF or TXT file"}, 400)
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", name).strip("._") or "cv.pdf"
        folder = hunter.data_dir / "cv"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / safe
        target.write_bytes(self.rfile.read(size))
        hunter.update_profile({"cv_path": str(target)})
        return self.send_json({"cv": safe}, 201)

    def chat_request(self, slug, model_override=None, model_id_override=None):
        data = self.body_json()
        content = data.get("content")
        model_override = data.get("model_provider") or model_override
        model_id_override = data.get("model_id") or model_id_override
        if not isinstance(content, str) or not content.strip() or len(content) > 20000:
            return self.send_json({"error": "Enter a message of 1–20,000 characters"}, 400)
        if data.get("target_agent"):
            return self.send_json({"error": "Open the specialist's tab to chat; automatic delegation is not enabled"}, 400)
        with STORE_LOCK:
            agent = STORE.get_agent(slug)
            lock = AGENT_LOCKS.setdefault(slug, threading.Lock())
        if not agent["enabled"]:
            return self.send_json({"error": "This agent is paused"}, 409)
        # CEO can delegate: detect @agent directives
        delegations_created = []
        if slug == "ceo":
            import re
            # Match @agent_name [command] <instruction> — lenient: bare @agent followed by text counts
            pattern = r'@([a-z0-9_-]+)\s+(.+?)(?=(?:\n@)|$)'
            matches = re.findall(pattern, content.strip(), re.IGNORECASE | re.DOTALL)
            for target_slug, instruction in matches:
                target_slug = target_slug.lower().strip()
                # Resolve common aliases
                alias_map = {"job": "job", "jobs": "job", "dad": "dad",
                             "email": "dad", "tech": "tech-news", "news": "tech-news"}
                resolved = alias_map.get(target_slug, target_slug) or target_slug
                agents = {a["slug"] for a in STORE.list_agents()}
                if resolved not in agents:
                    continue
                try:
                    task_type = instruction.strip().split("\n")[0][:60]
                    d = STORE.create_delegation("ceo", resolved, task_type, instruction.strip())
                    delegations_created.append({"target": resolved, "instruction": instruction.strip()[:80], "id": d["id"]})
                except Exception:
                    pass
        if agent["model_provider"] not in {"codex-cli", "claude-code", "ollama"}:
            return self.send_json({"error": "Choose Claude Code, Codex, or Ollama as this agent's brain first"}, 503)
        if not lock.acquire(blocking=False):
            return self.send_json({"error": "This agent is still replying. Wait before sending again"}, 409)
        acquired = BRAIN_SLOTS.acquire(blocking=False)
        try:
            if not acquired:
                return self.send_json({"error": "Two agents are replying. Try again shortly"}, 429)
            from brains import BrainError, reply
            effective_provider = model_override or agent["model_provider"]
            effective_model_id = (model_id_override if model_id_override is not None else agent["model_id"])
            with STORE_LOCK:
                history = STORE.messages(slug) + [{"role": "user", "content": content.strip()}]
            try:
                result = reply(agent, history, DATA / "chat-workspaces", provider=effective_provider, model_id=effective_model_id)
            except BrainError as exc:
                return self.send_json({"error": str(exc)}, 502)
            with STORE_LOCK:
                user = STORE.add_message(slug, "user", content)
                assistant = STORE.add_message(slug, "assistant", result["content"])
            # Log to Obsidian vault
            try:
                from brains import _vault_append_entry
                summary = f"**User:** {content[:200]}\n**Reply:** {result['content'][:300]}"
                _vault_append_entry(slug, summary)
            except Exception:
                pass  # vault write is best-effort
            response = {"user": user, "assistant": assistant, "runtime": result["runtime"], "model": result["model"]}
            if delegations_created:
                lines = ["I've delegated the following tasks:"]
                for d in delegations_created:
                    lines.append(f"  → @{d['target']}: {d['instruction'][:60]}")
                delegation_note = "\n".join(lines)
                STORE.add_message(slug, "assistant", delegation_note)
                response["assistant"]["content"] = result["content"] + "\n\n" + delegation_note
                response["delegations"] = delegations_created
            return self.send_json(response, 201)
        finally:
            if acquired:
                BRAIN_SLOTS.release()
            lock.release()

    def do_POST(self):
        path = urlparse(self.path).path
        if path.startswith("/api/jobhunter/"):
            return self.jobhunter_request("POST")
        if path.startswith("/api/agents/") and path.endswith("/messages"):
            try:
                return self.chat_request(path.split("/")[3])
            except KeyError:
                return self.send_json({"error": "Agent not found"}, 404)
            except (ValueError, TypeError):
                return self.send_json({"error": "Invalid chat request"}, 400)
            except Exception:
                return self.send_json({"error": "Chat request failed; no fallback reply was saved"}, 500)
        if path == "/api/page-agent/edit":
            return self.page_agent_edit()
        if path == "/api/telegram/configure":
            global TELEGRAM_BOT_TOKEN
            data = self.body_json()
            token = str(data.get("token", "")).strip()
            if not token:
                return self.send_json({"error": "token is required"}, 400)
            test_url = f"https://api.telegram.org/bot{token}/getMe"
            try:
                req = urllib.request.Request(test_url)
                with urllib.request.urlopen(req, timeout=5) as r:
                    result = json.loads(r.read())
                if not result.get("ok"):
                    return self.send_json({"error": "Invalid bot token"}, 401)
            except Exception as e:
                return self.send_json({"error": f"Could not reach Telegram: {e}"}, 502)
            env_path = ROOT / ".env"
            lines = []
            if env_path.exists():
                lines = env_path.read_text().splitlines()
            found = False
            new_lines = []
            for line in lines:
                if line.strip().startswith("TELEGRAM_BOT_TOKEN"):
                    new_lines.append(f'TELEGRAM_BOT_TOKEN={token}')
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append(f'TELEGRAM_BOT_TOKEN={token}')
            env_path.write_text("\n".join(new_lines) + "\n")
            TELEGRAM_BOT_TOKEN = token
            os.environ["TELEGRAM_BOT_TOKEN"] = token  # visible to the job hunter too
            start_telegram_polling()
            return self.send_json({"ok": True, "bot_username": result.get("result", {}).get("username", "unknown")})
        if path == "/api/notion/configure":
            data = self.body_json()
            api_key = str(data.get("api_key", "")).strip()
            if not api_key:
                return self.send_json({"error": "api_key is required"}, 400)
            # Validate against Notion API
            test_req = urllib.request.Request(
                "https://api.notion.com/v1/users/me",
                headers={"Authorization": f"Bearer {api_key}", "Notion-Version": "2022-06-28"}
            )
            try:
                with urllib.request.urlopen(test_req, timeout=5) as r:
                    if r.status != 200:
                        raise ValueError(f"HTTP {r.status}")
            except Exception as e:
                return self.send_json({"error": f"Notion API error: {e}"}, 502)
            # Save to .env
            env_path = ROOT / ".env"
            lines = []
            if env_path.exists():
                lines = env_path.read_text().splitlines()
            new_lines, found = [], False
            for line in lines:
                if line.strip().startswith("NOTION_API_KEY"):
                    new_lines.append(f"NOTION_API_KEY={api_key}")
                    found = True
                else:
                    new_lines.append(line)
            if not found:
                new_lines.append(f"NOTION_API_KEY={api_key}")
            env_path.write_text("\n".join(new_lines) + "\n")
            os.environ["NOTION_API_KEY"] = api_key
            return self.send_json({"ok": True, "note": "Notion API key saved. Restart server to activate."})
        return self.post_resource()

    def page_agent_edit(self):
        """Edit a page element via CSS injection — safe, no external calls."""
        data = self.body_json()
        instruction = str(data.get("instruction", "")).strip()
        if not instruction or len(instruction) > 1000:
            return self.send_json({"error": "Invalid instruction"}, 400)
        # Use Ollama if available, otherwise simple fallback
        result = self._safe_page_edit(instruction)
        return self.send_json(result)

    def _safe_page_edit(self, instruction: str) -> dict:
        """Apply a safe CSS/text edit to the page based on natural-language instruction."""
        instr = instruction.lower()
        # ── Color & background ──────────────────────────────────
        if any(k in instr for k in ["blue", "background blue", "make blue"]):
            return {"css": ".page-head { background: #0071e3 !important; }", "description": "Changed page header background to blue."}
        if any(k in instr for k in ["green", "background green"]):
            return {"css": ".page-head { background: #34c759 !important; }", "description": "Changed page header background to green."}
        if any(k in instr for k in ["red", "background red"]):
            return {"css": ".page-head { background: #ff3b30 !important; }", "description": "Changed page header background to red."}
        if any(k in instr for k in ["dark", "dark mode", "darken"]):
            return {"css": "body { background: #1c1c1e !important; color: #f5f5f7 !important; }", "description": "Applied dark mode."}
        if any(k in instr for k in ["light", "light mode", "bright"]):
            return {"css": "body { background: #f5f5f7 !important; color: #1d1d1f !important; }", "description": "Applied light mode."}
        if any(k in instr for k in ["purple", "violet"]):
            return {"css": ".brand-mark { background: #5856d6 !important; }", "description": "Changed brand color to purple."}
        # ── Text & font ──────────────────────────────────────────
        if any(k in instr for k in ["bigger text", "larger text", "increase font", "bigger font"]):
            return {"css": "body { font-size: 18px !important; }", "description": "Increased base font size."}
        if any(k in instr for k in ["smaller text", "decrease font", "shrink text"]):
            return {"css": "body { font-size: 13px !important; }", "description": "Decreased base font size."}
        if any(k in instr for k in ["bold headings", "bold titles", "bold header"]):
            return {"css": "h1, h2, h3 { font-weight: 700 !important; }", "description": "Made headings bold."}
        # ── Layout ──────────────────────────────────────────────
        if any(k in instr for k in ["hide sidebar", "hide nav", "remove sidebar"]):
            return {"css": "#sidebar { display: none !important; }", "description": "Hid the sidebar."}
        if any(k in instr for k in ["show sidebar", "show nav"]):
            return {"css": "#sidebar { display: flex !important; }", "description": "Showed the sidebar."}
        if any(k in instr for k in ["center content", "center page"]):
            return {"css": "#content { max-width: 800px !important; margin: 0 auto !important; }", "description": "Centered the content area."}
        if any(k in instr for k in ["full width", "wide layout"]):
            return {"css": "#content { max-width: 100% !important; }", "description": "Made content full width."}
        if any(k in instr for k in ["compact", "dense", "smaller spacing"]):
            return {"css": ".content-wrap, .card, .panel { padding: 8px !important; gap: 8px !important; }", "description": "Made layout more compact."}
        if any(k in instr for k in ["spacious", "more padding", "bigger gaps"]):
            return {"css": ".content-wrap, .card, .panel { padding: 24px !important; gap: 20px !important; }", "description": "Made layout more spacious."}
        if any(k in instr for k in ["hide topbar", "hide header"]):
            return {"css": ".topbar { display: none !important; }", "description": "Hid the top bar."}
        # ── Cards & widgets ──────────────────────────────────────
        if any(k in instr for k in ["bigger cards", "larger cards", "cards bigger"]):
            return {"css": ".card, .resource-card, .overview-card { padding: 20px !important; }", "description": "Made cards larger."}
        if any(k in instr for k in ["shadow", "more shadow", "lift cards"]):
            return {"css": ".card, .resource-card { box-shadow: 0 8px 32px rgba(0,0,0,0.15) !important; }", "description": "Added more shadow to cards."}
        if any(k in instr for k in ["no shadow", "flat cards", "remove shadow"]):
            return {"css": ".card, .resource-card { box-shadow: none !important; }", "description": "Removed shadows from cards."}
        if any(k in instr for k in ["rounded", "more rounded", "rounder corners"]):
            return {"css": ".card, .resource-card, .btn, input, textarea { border-radius: 20px !important; }", "description": "Made corners more rounded."}
        if any(k in instr for k in ["squared", "square corners", "less rounded"]):
            return {"css": ".card, .resource-card, .btn, input, textarea { border-radius: 4px !important; }", "description": "Made corners more squared."}
        # ── Nav & sidebar ────────────────────────────────────────
        if any(k in instr for k in ["wider sidebar", "wider nav"]):
            return {"css": "#sidebar { width: 240px !important; }", "description": "Widened the sidebar."}
        if any(k in instr for k in ["narrower sidebar", "narrow sidebar", "skinnier nav"]):
            return {"css": "#sidebar { width: 180px !important; }", "description": "Narrowed the sidebar."}
        # ── Accent color ─────────────────────────────────────────
        if any(k in instr for k in ["accent blue", "change accent to blue", "blue accent"]):
            return {"css": ":root { --accent: #0071e3; --accent-dark: #005bb5; }", "description": "Changed accent to blue."}
        if any(k in instr for k in ["accent green", "green accent"]):
            return {"css": ":root { --accent: #34c759; --accent-dark: #28a745; }", "description": "Changed accent to green."}
        if any(k in instr for k in ["accent purple", "purple accent"]):
            return {"css": ":root { --accent: #5856d6; --accent-dark: #4240d0; }", "description": "Changed accent to purple."}
        if any(k in instr for k in ["accent orange", "orange accent"]):
            return {"css": ":root { --accent: #ff9500; --accent-dark: #e68600; }", "description": "Changed accent to orange."}
        # ── Page Agent ───────────────────────────────────────────
        if any(k in instr for k in ["hide page agent", "close page agent"]):
            return {"css": "#page-agent, #page-agent-toggle { display: none !important; }", "description": "Hidden the Page Agent."}
        if any(k in instr for k in ["show page agent", "show page agent button"]):
            return {"css": "#page-agent-toggle { display: flex !important; }", "description": "Showed the Page Agent button."}
        # Fallback
        return {"message": f"I understood '{instruction}' but don't know how to apply that as a page edit yet. Try: change color, hide sidebar, bigger text, dark mode, center content, shadow, rounded corners."}

    def _notify_job_approved(self, app: Dict[str, Any]) -> None:
        """POST job application details to n8n webhooks when user approves."""
        try:
            webhooks = STORE.list_resources("n8n_webhooks")
            payload = json.dumps({
                "event": "job_application_approved",
                "application": app,
            }).encode("utf-8")
            for wh in webhooks:
                url = wh.get("url")
                if not url:
                    continue
                req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
                try:
                    with urllib.request.urlopen(req, timeout=5):
                        pass
                except Exception:
                    pass
        except Exception:
            pass

    @store_request
    def post_resource(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/resume/upload":
                ctype, params = cgi.parse_header(self.headers.get("Content-Type", ""))
                if ctype != "multipart/form-data":
                    raise ValueError("multipart/form-data required")
                form = cgi.FieldStorage(fp=self.rfile, headers=self.headers,
                                       environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers["Content-Type"]})
                item = form["file"]
                content = item.file.read(MAX_UPLOAD + 1)
                if len(content) > MAX_UPLOAD:
                    raise ValueError("File exceeds 25 MB")
                return self.send_json(STORE.save_base_resume(item.filename, content), 201)
            if path == "/api/jobs":
                return self.send_json(STORE.create_job_application(self.body_json()), 201)
            if path == "/api/jobs/search":
                data = self.body_json()
                query = data.get("query", "")
                location = data.get("location", "Saudi Arabia")
                sources = STORE.list_resources("job_sources")
                results = []
                for source in sources:
                    if not source.get("enabled"):
                        continue
                    kind = source.get("kind", "")
                    url = source.get("url", "")
                    if kind == "website" and url:
                        results.append({
                            "source": source.get("name", "Unknown"),
                            "company": query,
                            "role": query,
                            "location": location,
                            "salary": "",
                            "job_url": url,
                            "status": "found"
                        })
                if not results:
                    results.append({
                        "source": "LinkedIn",
                        "company": query,
                        "role": query,
                        "location": location,
                        "salary": "",
                        "job_url": f"https://www.linkedin.com/jobs/search/?keywords={query}&location={location}",
                        "status": "found"
                    })
                return self.send_json({"results": results})
            if path.startswith("/api/jobs/") and path.endswith("/tailor"):
                app_id = path.split("/")[3]
                app = STORE.get_job_application(app_id)
                resume = STORE.get_base_resume()
                if not resume:
                    return self.send_json({"error": "No base resume uploaded. Upload one in the Job Queue first."}, 400)
                resume_path = STORE.upload_dir / resume["stored_name"]
                resume_text = resume_path.read_text(errors="replace") if resume_path.exists() else ""
                try:
                    from brains import _ollama_reply
                    prompt = f"""You are a CV tailoring assistant. Rewrite the following CV to match the job description.

CV:
{resume_text[:3000]}

Job Description:
{app.get('job_description','')[:2000]}

Output only the tailored CV/resume text. Make it concise, relevant, and truthful. Do not fabricate experience."""
                    tailored = _ollama_reply(prompt)
                    tailored_path = STORE.upload_dir / f"tailored-{app['id']}.txt"
                    tailored_path.write_text(tailored)
                    STORE.update_job_application(app_id, {
                        "tailored_resume_path": str(tailored_path),
                        "status": "tailoring"
                    })
                    return self.send_json({"ok": True, "tailored_length": len(tailored)})
                except Exception as e:
                    return self.send_json({"error": str(e)}, 500)
            if path.startswith("/api/jobs/") and path.endswith("/email"):
                app_id = path.split("/")[3]
                app = STORE.get_job_application(app_id)
                try:
                    from brains import _ollama_reply
                    prompt = f"""Write a professional job application email for the following role.

Company: {app.get('company','')}
Role: {app.get('role','')}
Location: {app.get('location','')}

Write a concise, compelling email that:
1. Has a clear subject line
2. Has a brief intro paragraph
3. Highlights 2-3 most relevant qualifications
4. Ends with a call to action
5. References the CV attachment

Output format:
SUBJECT: <subject line>
BODY: <email body>"""
                    result = _ollama_reply(prompt)
                    lines = result.split("\n", 1)
                    subject = lines[0].replace("SUBJECT:", "").strip() if lines else "Application"
                    body = lines[1] if len(lines) > 1 else result
                    STORE.update_job_application(app_id, {
                        "email_subject": subject,
                        "email_draft": body,
                        "status": "ready"
                    })
                    return self.send_json({"ok": True, "subject": subject})
                except Exception as e:
                    return self.send_json({"error": str(e)}, 500)
            if path.startswith("/api/jobs/") and path.endswith("/approve"):
                app_id = path.split("/")[3]
                app = STORE.get_job_application(app_id)
                STORE.update_job_application(app_id, {"status": "sent", "applied_at": __import__('datetime').datetime.now().__str__()})
                self._notify_job_approved(app)
                return self.send_json({"ok": True})
            if path == "/api/agents": return self.send_json(STORE.create_agent(self.body_json()), 201)

            if path == "/api/linkedin/accounts":
                return self.send_json(STORE.add_linkedin_account(self.body_json()), 201)

            if path == "/api/actions":
                data = self.body_json(); return self.send_json(STORE.create_action(data["agent_slug"], data["action_type"], data.get("payload", {})), 201)
            if path.startswith("/api/actions/") and path.endswith("/decision"):
                parts = path.split("/"); return self.send_json(STORE.decide_action(parts[3], self.body_json()["decision"]))
            if path.startswith("/api/resources/"):
                return self.send_json(STORE.create_resource(path.split("/")[3], self.body_json()), 201)
            if path == "/api/upload":
                ctype, params = cgi.parse_header(self.headers.get("Content-Type", ""))
                if ctype != "multipart/form-data": raise ValueError("multipart/form-data required")
                form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ={"REQUEST_METHOD": "POST", "CONTENT_TYPE": self.headers["Content-Type"]})
                item = form["file"]; content = item.file.read(MAX_UPLOAD + 1)
                if len(content) > MAX_UPLOAD: raise ValueError("File exceeds 25 MB")
                return self.send_json(STORE.save_upload(form.getfirst("agent_slug", "ceo"), item.filename, content), 201)
            if path == "/api/news":
                data = self.body_json(); return self.send_json(STORE.add_news_item(data["title"], data.get("summary", ""), data.get("url", "")), 201)
            if path.startswith("/api/news/") and path.endswith("/script"):
                return self.send_json(STORE.generate_script(path.split("/")[3]), 201)
            if path == "/api/news/fetch":
                data = self.body_json(); added = []
                for title, summary, link, published in fetch_rss(data["url"]):
                    added.append(STORE.add_news_item(title, summary, link, data.get("name", "RSS"), published))
                return self.send_json({"added": len(added), "items": added}, 201)
            if path.startswith("/api/browser/") and path.endswith("/open"):
                slug = path.split("/")[3]; data = self.body_json(); url = data.get("url", "about:blank")
                if not (url == "about:blank" or url.startswith("https://") or url.startswith("http://")): raise ValueError("Only http/https URLs are allowed")
                profile = STORE.browser_profile(slug)
                chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
                if not Path(chrome).exists(): raise ValueError("Google Chrome is not installed")
                subprocess.Popen([chrome, f"--user-data-dir={profile['profile_dir']}", f"--app={url}", "--no-first-run"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return self.send_json({"opened": True, **profile})
            if path == "/api/n8n/status":
                base = os.environ.get("N8N_BASE_URL", "http://localhost:5678")
                req = urllib.request.Request(base + "/health", headers={"User-Agent": "PersonalOS/1.0"})
                try:
                    with urllib.request.urlopen(req, timeout=5) as r:
                        data = json.loads(r.read())
                    return self.send_json({"connected": True, "version": data.get("version", "unknown"), "base_url": base})
                except Exception as e:
                    return self.send_json({"connected": False, "base_url": base, "error": str(e)})
            if path == "/api/n8n/webhooks":
                return self.send_json(STORE.list_resources("n8n_webhooks"))
            if path.startswith("/api/n8n/webhooks") and path.endswith("/test"):
                wh_id = path.split("/")[4]
                webhooks = STORE.list_resources("n8n_webhooks")
                wh = next((w for w in webhooks if w["id"] == wh_id), None)
                if not wh:
                    return self.send_json({"error": "Webhook not found"}, 404)
                payload = json.dumps({"test": True, "webhook_id": wh_id, "message": "Personal OS test ping"}).encode()
                req = urllib.request.Request(wh["url"], data=payload, headers={"Content-Type": "application/json"})
                try:
                    with urllib.request.urlopen(req, timeout=10) as r:
                        resp_body = r.read() if r.status != 204 else b""
                        return self.send_json({"ok": True, "status": r.status, "response": resp_body.decode("utf-8", errors="replace")})
                except Exception as e:
                    return self.send_json({"ok": False, "error": str(e)}, 502)
            if path.startswith("/api/linkedin/accounts/"):
                slug = path.split("/")[4]
                STORE.remove_linkedin_account(slug)
                return self.send_json({"deleted": True})
            if path == "/api/linkedin/open-chat":
                data = self.body_json()
                slug = data.get("account_slug")
                hr_url = data.get("hr_url", "")
                message = data.get("message", "")
                if not slug:
                    return self.send_json({"error": "account_slug is required"}, 400)
                accounts = STORE.list_linkedin_accounts()
                if not any(a["slug"] == slug for a in accounts):
                    return self.send_json({"error": f"LinkedIn account '{slug}' not found"}, 404)
                password = STORE.get_linkedin_password(slug)
                STORE.mark_linkedin_used(slug)
                chrome = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
                if not Path(chrome).exists():
                    return self.send_json({"error": "Google Chrome not found"}, 400)
                if hr_url and "linkedin.com" in hr_url:
                    profile_id = hr_url.rstrip("/").split("/")[-1]
                    if profile_id.startswith("in-"):
                        compose_url = f"https://www.linkedin.com/messaging/compose/?recipients={profile_id[3:]}&msgText={quote(message)}"
                    else:
                        compose_url = hr_url
                else:
                    compose_url = "https://www.linkedin.com/messaging/"
                profile_dir = Path.home() / ".config" / "google-chrome" / "PersonalOS-LinkedIn"
                profile_dir.mkdir(parents=True, exist_ok=True)
                subprocess.Popen([chrome, "--profile-directory=PersonalOS-LinkedIn", "--new-tab", compose_url],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return self.send_json({"opened": True, "url": compose_url, "account": slug, "message": message})
            self.send_json({"error": "Not found"}, 404)
        except (KeyError, ValueError, sqlite3.IntegrityError) as exc:
            self.send_json({"error": str(exc)}, 400)
        except Exception as exc:
            self.send_json({"error": "Internal error", "detail": str(exc)}, 500)

    @store_request
    def do_PATCH(self):
        path = urlparse(self.path).path
        try:
            if path.startswith("/api/agents/"):
                return self.send_json(STORE.update_agent(path.split("/")[3], self.body_json()))
            if path.startswith("/api/actions/"):
                return self.send_json(STORE.edit_action(path.split("/")[3], self.body_json().get("payload", {})))
            if path.startswith("/api/resources/"):
                parts = path.split("/"); return self.send_json(STORE.update_resource(parts[3], parts[4], self.body_json()))
            if path.startswith("/api/jobs/"):
                parts = path.split("/")
                if len(parts) == 4 and parts[3]:
                    return self.send_json(STORE.update_job_application(parts[3], self.body_json()))
            self.send_json({"error": "Not found"}, 404)
        except (KeyError, ValueError) as exc: self.send_json({"error": str(exc)}, 400)

    @store_request
    def do_DELETE(self):
        path = urlparse(self.path).path
        try:
            if path.startswith("/api/resources/"):
                parts = path.split("/"); STORE.delete_resource(parts[3], parts[4]); return self.send_json({"deleted": True})
            if path.startswith("/api/jobs/"):
                parts = path.split("/")
                if len(parts) == 4 and parts[3]:
                    STORE.delete_job_application(parts[3]); return self.send_json({"deleted": True})
            self.send_json({"error": "Not found"}, 404)
        except (KeyError, ValueError) as exc: self.send_json({"error": str(exc)}, 400)


def main():
    parser = argparse.ArgumentParser(description="Run Personal OS locally")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost"}:
        parser.error("Personal OS must bind to localhost because it uses local signed-in AI accounts")
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    started = start_telegram_polling()
    try:
        hunter = get_hunter()
        if hunter.profile()["autostart"] or os.environ.get("JOBHUNTER_AUTOSTART") == "1":
            result = hunter.start()
            print("Job Hunter: " + ("running" if result.get("running") else result.get("error", "not started")), flush=True)
    except Exception as exc:
        print(f"Job Hunter could not start: {exc}", flush=True)
    print(f"Personal OS running at http://{args.host}:{args.port} (Claude Code / Codex chat){' | Telegram polling active' if started else ' | Telegram: set TELEGRAM_BOT_TOKEN'}", flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close(); STORE.close()


if __name__ == "__main__":
    main()
