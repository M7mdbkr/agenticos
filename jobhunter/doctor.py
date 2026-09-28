"""`python3 -m jobhunter doctor` — checks every moving part on this laptop and says how to fix what's broken."""
from __future__ import annotations

import json
import shutil
import sys
import urllib.request
from typing import Any, Dict, List

from . import notify
from .cards import OLLAMA
from .mailbox import MailError
from .profile import is_ready
from .sources import Query, SourceError


def _check(name: str, ok: bool, detail: str, fix: str = "", level: str = "") -> Dict[str, Any]:
    return {"name": name, "status": "ok" if ok else (level or "fail"), "detail": detail, "fix": "" if ok else fix}


def _ollama_models() -> List[str]:
    try:
        with urllib.request.urlopen(f"{OLLAMA}/api/tags", timeout=4) as response:
            return [m.get("name", "") for m in json.loads(response.read()).get("models", [])]
    except Exception:
        return []


def run(hunter, live: bool = True) -> List[Dict[str, Any]]:
    profile = hunter.profile()
    checks = [_check("Python", sys.version_info >= (3, 9), sys.version.split()[0], "Install Python 3.9+ (brew install python)")]

    checks.append(_check("Profile", is_ready(profile), f"roles: {', '.join(profile['roles']) or 'none'} · "
                         f"locations: {', '.join(profile['locations']) or 'any'}",
                         "Add target roles: python3 -m jobhunter setup (or Job Hunter → Settings)"))
    name = profile["name"]
    checks.append(_check("Name", bool(name) and "mohammad " not in (name.lower() + " "), name or "not set",
                         "Set your display name (e.g. 'Mohammed Bakr') in Settings", level="warn"))
    master, cv = hunter.master_cv().strip(), hunter._cv_path(profile)
    checks.append(_check("CV", bool(master or cv), "master CV ✓" if master else (cv.name if cv else "none"),
                         "python3 -m jobhunter cv import ~/path/ATS-1.docx", level="warn"))

    mailbox = hunter.mailbox
    if not mailbox.configured:
        checks.append(_check("Email", False, "not connected",
                             "python3 -m jobhunter setup → paste a Gmail App Password (myaccount.google.com/apppasswords)"))
    elif live:
        try:
            mailbox.test()
            checks.append(_check("Email", True, f"{mailbox.address}: IMAP + SMTP login OK"))
        except MailError as exc:
            checks.append(_check("Email", False, str(exc), "Create a new App Password and run setup again"))
    checks.append(_check("Updates go to", bool(hunter.owner_emails(profile)), ", ".join(hunter.owner_emails(profile)) or "nobody",
                         "Set 'Send updates to' in Settings"))

    if live and is_ready(profile):
        term = profile["roles"][0]
        place = next((l for l in profile["locations"] if l.lower() not in ("remote", "anywhere")), "")
        ctx = {"env": hunter.env, "profile": profile, "extra_feeds": hunter._extra_feeds(), "delay": 1.0}
        for name_, src in hunter.sources.items():
            if not hunter._source_wanted(name_, src, profile):
                if src.needs and not src.configured(hunter.env):
                    checks.append(_check(f"Source · {src.label}", False, "no API key",
                                         f"Optional: add {' + '.join(src.needs)} to .env for {src.covers}", level="skip"))
                continue
            if src.mode == "once" and name_ in ("greenhouse", "lever", "rss", "companies") and not (
                    profile.get({"greenhouse": "greenhouse_boards", "lever": "lever_boards", "rss": "rss_feeds",
                                 "companies": "company_sites"}[name_]) or (name_ == "rss" and ctx["extra_feeds"])):
                continue
            try:
                query = Query(term if src.mode != "once" else "", place if src.mode == "query_location" else "", profile["level"])
                found = src.fetch(query, ctx)
                checks.append(_check(f"Source · {src.label}", True, f"reachable — {len(found)} postings for “{term}”"))
            except SourceError as exc:
                checks.append(_check(f"Source · {src.label}", False, str(exc),
                                     "Check your internet/VPN; 403/429 means the site is limiting requests — it retries next cycle",
                                     level="warn"))
            except Exception as exc:
                checks.append(_check(f"Source · {src.label}", False, f"adapter error: {exc}",
                                     "The site may have changed its format — report it", level="warn"))

    models = _ollama_models()
    brain = profile["brain"]
    if brain == "ollama":
        checks.append(_check("Writing brain", bool(models), f"Ollama models: {', '.join(models[:4]) or 'server not running'}",
                             "Start Ollama (ollama serve) and pull a model: ollama pull qwen2.5:7b"))
    elif brain in ("claude-code", "codex-cli"):
        exe = shutil.which("claude" if brain == "claude-code" else "codex")
        checks.append(_check("Writing brain", bool(exe), exe or f"{brain} CLI not found", f"Install and log in to {brain}"))
    else:
        checks.append(_check("Writing brain", True, "templates (set Ollama/Claude Code in Settings for AI-written letters)"))

    vision = profile.get("vision_model", "")
    has_vision = bool(vision) and any(m.split(":")[0] == vision.split(":")[0] for m in models)
    has_tesseract = bool(shutil.which("tesseract"))
    checks.append(_check("Business-card reader", has_vision or has_tesseract,
                         "Ollama vision" if has_vision else ("tesseract OCR" if has_tesseract else "none installed"),
                         f"ollama pull {vision or 'llama3.2-vision'}   (or: brew install tesseract tesseract-lang)", level="warn"))

    token = hunter.env.get("TELEGRAM_BOT_TOKEN", "")
    checks.append(_check("Telegram", bool(token and profile["telegram_chat_id"]),
                         "bot + chat linked" if token and profile["telegram_chat_id"] else "not linked",
                         "Optional: connect the bot on the Telegram page, then put your chat ID in Job Hunter settings",
                         level="skip"))
    checks.append(_check("Browser", bool(notify._chrome()), notify._chrome() or "default browser",
                         "Optional: install Google Chrome so jobs open in the agent's own profile", level="skip"))
    running = hunter.running or hunter.service_running_elsewhere()
    checks.append(_check("Always on", running, "running" if running else "not running",
                         "python3 -m jobhunter install-service   (or ▶ Start agent in the app)"))
    return checks


def format_report(checks: List[Dict[str, Any]]) -> str:
    icons = {"ok": "✅", "fail": "❌", "warn": "⚠️ ", "skip": "➖"}
    lines = []
    for c in checks:
        lines.append(f"{icons[c['status']]} {c['name']}: {c['detail']}")
        if c["fix"]:
            lines.append(f"     → {c['fix']}")
    failed = [c for c in checks if c["status"] == "fail"]
    lines.append("\nAll essentials work. 🎉" if not failed else f"\n{len(failed)} thing(s) to fix before it can run on its own.")
    return "\n".join(lines)
