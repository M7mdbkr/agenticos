"""Local-first storage and policy core for Mohammad's Personal OS."""
from __future__ import annotations

import hashlib
import json
import base64
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

RESOURCE_TABLES = {
    "tools", "skills", "connectors", "email_accounts", "job_sources", "tasks", "schedules", "projects", "n8n_webhooks"
}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class OperationsStore:
    """SQLite-backed operational state. Secrets and browser cookies are never stored here."""

    def __init__(self, db_path: Path, upload_dir: Path, profile_dir: Path):
        self.db_path = Path(db_path)
        self.upload_dir = Path(upload_dir)
        self.profile_dir = Path(profile_dir)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._schema()
        self._bootstrap()

    def close(self) -> None:
        self.db.close()

    def _schema(self) -> None:
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS agents(
          slug TEXT PRIMARY KEY, name TEXT NOT NULL, purpose TEXT NOT NULL,
          model_provider TEXT NOT NULL, model_id TEXT NOT NULL,
          free_only INTEGER NOT NULL DEFAULT 0, enabled INTEGER NOT NULL DEFAULT 1,
          tools_json TEXT NOT NULL DEFAULT '[]', skills_json TEXT NOT NULL DEFAULT '[]',
          system_prompt TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS messages(
          id TEXT PRIMARY KEY, agent_slug TEXT NOT NULL REFERENCES agents(slug),
          role TEXT NOT NULL, content TEXT NOT NULL, target_agent TEXT,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS actions(
          id TEXT PRIMARY KEY, agent_slug TEXT NOT NULL REFERENCES agents(slug),
          action_type TEXT NOT NULL, payload_json TEXT NOT NULL, digest TEXT NOT NULL,
          status TEXT NOT NULL, created_at TEXT NOT NULL, decided_at TEXT
        );
        CREATE TABLE IF NOT EXISTS resources(
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, data_json TEXT NOT NULL,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS uploads(
          id TEXT PRIMARY KEY, agent_slug TEXT NOT NULL, original_name TEXT NOT NULL,
          stored_name TEXT NOT NULL, size INTEGER NOT NULL, sha256 TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS news(
          id TEXT PRIMARY KEY, title TEXT NOT NULL, summary TEXT NOT NULL, url TEXT NOT NULL,
          published_at TEXT, source TEXT NOT NULL DEFAULT 'manual', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS scripts(
          id TEXT PRIMARY KEY, news_id TEXT NOT NULL REFERENCES news(id), script TEXT NOT NULL,
          created_at TEXT NOT NULL, UNIQUE(news_id)
        );
        CREATE TABLE IF NOT EXISTS audit(
          seq INTEGER PRIMARY KEY AUTOINCREMENT, event_type TEXT NOT NULL,
          detail_json TEXT NOT NULL, previous_hash TEXT NOT NULL, event_hash TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS telegram_sessions(
          chat_id TEXT PRIMARY KEY, agent_slug TEXT NOT NULL REFERENCES agents(slug),
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS telegram_incoming(
          id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id TEXT NOT NULL,
          update_id INTEGER UNIQUE, message_text TEXT, voice_file_id TEXT,
          from_first TEXT, from_last TEXT, received_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS linkedin_accounts(
          slug TEXT PRIMARY KEY, name TEXT NOT NULL,
          username TEXT NOT NULL, password_b64 TEXT NOT NULL,
          session_cookies TEXT DEFAULT '',
          status TEXT DEFAULT 'idle',
          last_used TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS delegations(
          id TEXT PRIMARY KEY, parent_slug TEXT NOT NULL,
          target_agent TEXT NOT NULL, task_type TEXT NOT NULL,
          instruction TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS job_applications(
          id TEXT PRIMARY KEY,
          company TEXT NOT NULL,
          role TEXT NOT NULL,
          location TEXT NOT NULL DEFAULT '',
          salary TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'found',
          job_url TEXT NOT NULL DEFAULT '',
          job_description TEXT NOT NULL DEFAULT '',
          delegation_id TEXT,
          tailored_resume_path TEXT NOT NULL DEFAULT '',
          email_draft TEXT NOT NULL DEFAULT '',
          email_subject TEXT NOT NULL DEFAULT '',
          applied_at TEXT,
          replied_at TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS inbox_emails(
          id TEXT PRIMARY KEY,
          message_id TEXT NOT NULL UNIQUE,
          source TEXT NOT NULL DEFAULT 'n8n',
          from_name TEXT NOT NULL DEFAULT '',
          from_address TEXT NOT NULL DEFAULT '',
          to_address TEXT NOT NULL DEFAULT '',
          subject TEXT NOT NULL DEFAULT '',
          body TEXT NOT NULL DEFAULT '',
          received_at TEXT NOT NULL DEFAULT '',
          company TEXT NOT NULL DEFAULT '',
          category TEXT NOT NULL DEFAULT 'other',
          confidence REAL NOT NULL DEFAULT 0,
          signals_json TEXT NOT NULL DEFAULT '[]',
          language TEXT NOT NULL DEFAULT 'en',
          status TEXT NOT NULL DEFAULT 'new',
          draft_subject TEXT NOT NULL DEFAULT '',
          draft_body TEXT NOT NULL DEFAULT '',
          draft_source TEXT NOT NULL DEFAULT '',
          action_id TEXT,
          job_application_id TEXT,
          provider_message_id TEXT NOT NULL DEFAULT '',
          replied_at TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS inbox_emails_status ON inbox_emails(status);
        CREATE INDEX IF NOT EXISTS inbox_emails_received ON inbox_emails(received_at DESC);
        CREATE TABLE IF NOT EXISTS base_resume(
          id TEXT PRIMARY KEY,
          original_name TEXT NOT NULL,
          stored_name TEXT NOT NULL,
          size INTEGER NOT NULL,
          sha256 TEXT NOT NULL,
          created_at TEXT NOT NULL
        );
        """)
        self.db.commit()

    def _bootstrap(self) -> None:
        now = utcnow()
        agents = [
            ("ceo", "CEO Agent", "Coordinates every workspace and proposes source-code changes.", "offline", "deterministic", 0,
             ["delegate", "files", "projects", "source-review"], ["planning", "approval-safety"]),
            ("job", "Job Application Agent", "Finds roles, prepares truthful applications and tracks replies.", "ollama", "qwen3:8b", 1,
             ["browser", "files", "job-sources", "email-drafts"], ["cv-tailoring", "job-research"]),
            ("dad", "Dad's Email Agent", "Handles website-support research, draft correspondence and follow-ups.", "ollama", "qwen2.5:7b", 0,
             ["browser", "files", "email-drafts"], ["support-triage"]),
            ("tech-news", "Tech News Agent", "Collects technology news and drafts short-form video scripts.", "ollama", "qwen2.5:7b", 0,
             ["browser", "news", "scripts"], ["source-checking", "tiktok-script"]),
        ]
        for slug, name, purpose, provider, model, free_only, tools, skills in agents:
            self.db.execute("""INSERT OR IGNORE INTO agents
                (slug,name,purpose,model_provider,model_id,free_only,tools_json,skills_json,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (slug, name, purpose, provider, model, free_only, json_dump(tools), json_dump(skills), now, now))
        self.db.commit()

    @staticmethod
    def _row(row: sqlite3.Row) -> Dict[str, Any]:
        value = dict(row)
        for key in list(value):
            if key.endswith("_json"):
                value[key[:-5]] = json.loads(value.pop(key))
            elif key in {"enabled", "free_only"}:
                value[key] = bool(value[key])
        return value

    def _audit(self, event_type: str, detail: Dict[str, Any]) -> None:
        last = self.db.execute("SELECT event_hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
        previous = last[0] if last else "0" * 64
        created = utcnow()
        body = json_dump({"event_type": event_type, "detail": detail, "created_at": created, "previous_hash": previous})
        digest = hashlib.sha256(body.encode()).hexdigest()
        self.db.execute("INSERT INTO audit(event_type,detail_json,previous_hash,event_hash,created_at) VALUES(?,?,?,?,?)",
                        (event_type, json_dump(detail), previous, digest, created))
        self.db.commit()

    def list_agents(self) -> List[Dict[str, Any]]:
        return [self._row(r) for r in self.db.execute("SELECT * FROM agents ORDER BY CASE slug WHEN 'ceo' THEN 0 ELSE 1 END,name")]

    def get_agent(self, slug: str) -> Dict[str, Any]:
        row = self.db.execute("SELECT * FROM agents WHERE slug=?", (slug,)).fetchone()
        if not row:
            raise KeyError("Agent not found")
        return self._row(row)

    def update_agent(self, slug: str, changes: Dict[str, Any]) -> Dict[str, Any]:
        allowed = {"name", "purpose", "model_provider", "model_id", "free_only", "enabled", "tools", "skills", "system_prompt"}
        fields, values = [], []
        for key, val in changes.items():
            if key not in allowed:
                continue
            col = key + "_json" if key in {"tools", "skills"} else key
            if key in {"tools", "skills"}:
                val = json_dump(val)
            if key in {"enabled", "free_only"}:
                val = int(bool(val))
            fields.append(f"{col}=?")
            values.append(val)
        if not fields:
            return self.get_agent(slug)
        fields.append("updated_at=?")
        values.extend([utcnow(), slug])
        self.db.execute(f"UPDATE agents SET {','.join(fields)} WHERE slug=?", values)
        self.db.commit()
        self._audit("agent.updated", {"slug": slug, "fields": sorted(changes)})
        return self.get_agent(slug)

    def create_agent(self, data: Dict[str, Any]) -> Dict[str, Any]:
        slug = re.sub(r"[^a-z0-9]+", "-", data.get("slug") or data.get("name", "agent").lower()).strip("-")
        if not slug:
            raise ValueError("Agent name is required")
        now = utcnow()
        self.db.execute("""INSERT INTO agents(slug,name,purpose,model_provider,model_id,free_only,enabled,
            tools_json,skills_json,system_prompt,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (slug, data.get("name", slug.title()), data.get("purpose", "Custom assistant"), data.get("model_provider", "ollama"),
             data.get("model_id", "qwen2.5:7b"), int(bool(data.get("free_only", False))), 1,
             json_dump(data.get("tools", [])), json_dump(data.get("skills", [])), data.get("system_prompt", ""), now, now))
        self.db.commit()
        self._audit("agent.created", {"slug": slug})
        return self.get_agent(slug)

    def add_message(self, agent_slug: str, role: str, content: str, target_agent: Optional[str] = None) -> Dict[str, Any]:
        self.get_agent(agent_slug)
        if role not in {"user", "assistant", "system"} or not content.strip():
            raise ValueError("Invalid message")
        item = {"id": str(uuid.uuid4()), "agent_slug": agent_slug, "role": role, "content": content.strip(),
                "target_agent": target_agent, "created_at": utcnow()}
        self.db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?)", tuple(item.values()))
        self.db.commit()
        self._audit("message.added", {"agent": agent_slug, "role": role, "target": target_agent})
        return item

    def messages(self, agent_slug: str) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.db.execute("SELECT * FROM messages WHERE agent_slug=? ORDER BY created_at", (agent_slug,))]

    def create_action(self, agent_slug: str, action_type: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.get_agent(agent_slug)
        canonical = json_dump(payload)
        item = {"id": str(uuid.uuid4()), "agent_slug": agent_slug, "action_type": action_type,
                "payload": payload, "digest": hashlib.sha256(canonical.encode()).hexdigest(), "status": "pending",
                "created_at": utcnow(), "decided_at": None}
        self.db.execute("INSERT INTO actions VALUES(?,?,?,?,?,?,?,?)",
                        (item["id"], agent_slug, action_type, canonical, item["digest"], "pending", item["created_at"], None))
        self.db.commit()
        self._audit("action.created", {"id": item["id"], "agent": agent_slug, "type": action_type, "digest": item["digest"]})
        return item

    def get_action(self, action_id: str) -> Dict[str, Any]:
        row = self.db.execute("SELECT * FROM actions WHERE id=?", (action_id,)).fetchone()
        if not row:
            raise KeyError("Action not found")
        return self._row(row)

    def list_actions(self) -> List[Dict[str, Any]]:
        return [self._row(r) for r in self.db.execute("SELECT * FROM actions ORDER BY created_at DESC")]

    def decide_action(self, action_id: str, decision: str) -> Dict[str, Any]:
        if decision not in {"approved", "denied"}:
            raise ValueError("Decision must be approved or denied")
        self.get_action(action_id)
        decided = utcnow()
        self.db.execute("UPDATE actions SET status=?,decided_at=? WHERE id=?", (decision, decided, action_id))
        self.db.commit()
        self._audit("action.decided", {"id": action_id, "decision": decision})
        # After approval, notify any configured n8n webhooks
        if decision == "approved":
            action = self.get_action(action_id)
            self._notify_n8n_webhooks(action)
        return self.get_action(action_id)

    def _notify_n8n_webhooks(self, action: Dict[str, Any]) -> None:
        """POST action details to all configured n8n webhook URLs."""
        try:
            import urllib.request
            import json as _json
            webhooks = self.list_resources("n8n_webhooks")
            payload = _json.dumps({
                "agent": action["agent_slug"],
                "action_type": action["action_type"],
                "payload": action["payload"],
                "digest": action["digest"],
                "decided_at": action.get("decided_at")
            }).encode("utf-8")
            for wh in webhooks:
                url = wh.get("url")
                if not url:
                    continue
                req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
                try:
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        resp.read()  # we ignore response
                except Exception:
                    # Silently ignore webhook delivery failures to not block main flow
                    pass
        except Exception:
            # If anything goes wrong, we don't want to break the approval flow
            pass

    def edit_action(self, action_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        self.get_action(action_id)
        canonical = json_dump(payload)
        digest = hashlib.sha256(canonical.encode()).hexdigest()
        self.db.execute("UPDATE actions SET payload_json=?,digest=?,status='pending',decided_at=NULL WHERE id=?",
                        (canonical, digest, action_id))
        self.db.commit()
        self._audit("action.edited", {"id": action_id, "digest": digest, "approval_invalidated": True})
        return self.get_action(action_id)

    def create_resource(self, kind: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if kind not in RESOURCE_TABLES:
            raise ValueError("Unknown resource kind")
        item = dict(data)
        item["id"] = str(uuid.uuid4())
        now = utcnow()
        self.db.execute("INSERT INTO resources VALUES(?,?,?,?,?)", (item["id"], kind, json_dump(item), now, now))
        self.db.commit()
        self._audit("resource.created", {"kind": kind, "id": item["id"]})
        return item

    def list_resources(self, kind: str) -> List[Dict[str, Any]]:
        if kind not in RESOURCE_TABLES:
            raise ValueError("Unknown resource kind")
        return [json.loads(r[0]) for r in self.db.execute("SELECT data_json FROM resources WHERE kind=? ORDER BY created_at DESC", (kind,))]

    def update_resource(self, kind: str, resource_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        if kind not in RESOURCE_TABLES:
            raise ValueError("Unknown resource kind")
        current = self.db.execute("SELECT data_json FROM resources WHERE kind=? AND id=?", (kind, resource_id)).fetchone()
        if not current:
            raise KeyError("Resource not found")
        item = json.loads(current[0]); item.update(data); item["id"] = resource_id
        self.db.execute("UPDATE resources SET data_json=?,updated_at=? WHERE kind=? AND id=?", (json_dump(item), utcnow(), kind, resource_id))
        self.db.commit(); self._audit("resource.updated", {"kind": kind, "id": resource_id})
        return item

    def delete_resource(self, kind: str, resource_id: str) -> None:
        if kind not in RESOURCE_TABLES:
            raise ValueError("Unknown resource kind")
        self.db.execute("DELETE FROM resources WHERE kind=? AND id=?", (kind, resource_id)); self.db.commit()
        self._audit("resource.deleted", {"kind": kind, "id": resource_id})

    def save_upload(self, agent_slug: str, filename: str, content: bytes) -> Dict[str, Any]:
        self.get_agent(agent_slug)
        original = Path(filename).name
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", original).strip("._") or "upload.bin"
        candidate = safe
        count = 1
        while (self.upload_dir / candidate).exists():
            candidate = f"{Path(safe).stem}-{count}{Path(safe).suffix}"; count += 1
        (self.upload_dir / candidate).write_bytes(content)
        item = {"id": str(uuid.uuid4()), "agent_slug": agent_slug, "original_name": original,
                "stored_name": candidate, "size": len(content), "sha256": hashlib.sha256(content).hexdigest(), "created_at": utcnow()}
        self.db.execute("INSERT INTO uploads VALUES(?,?,?,?,?,?,?)", tuple(item.values())); self.db.commit()
        self._audit("file.uploaded", {k: item[k] for k in ("id", "agent_slug", "stored_name", "size", "sha256")})
        return item

    def list_uploads(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.db.execute("SELECT * FROM uploads ORDER BY created_at DESC")]

    def add_news_item(self, title: str, summary: str, url: str, source: str = "manual", published_at: Optional[str] = None) -> Dict[str, Any]:
        item = {"id": str(uuid.uuid4()), "title": title.strip(), "summary": summary.strip(), "url": url.strip(),
                "published_at": published_at, "source": source, "created_at": utcnow()}
        if not item["title"]:
            raise ValueError("News title is required")
        self.db.execute("INSERT INTO news VALUES(?,?,?,?,?,?,?)", tuple(item.values())); self.db.commit()
        return item

    def list_news(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.db.execute("SELECT * FROM news ORDER BY COALESCE(published_at,created_at) DESC")]

    def generate_script(self, news_id: str) -> Dict[str, Any]:
        existing = self.db.execute("SELECT * FROM scripts WHERE news_id=?", (news_id,)).fetchone()
        if existing:
            return dict(existing)
        news = self.db.execute("SELECT * FROM news WHERE id=?", (news_id,)).fetchone()
        if not news:
            raise KeyError("News item not found")
        script = (f"Hook: This tech update could matter sooner than you think.\n\n"
                  f"Story: {news['title']}\n\nWhat happened: {news['summary']}\n\n"
                  "Why it matters: Look at the practical effect, the limitations, and who benefits before following the hype.\n\n"
                  "Close: Would you use it? Tell me in the comments and follow for the next verified tech update.\n\n"
                  f"Source: {news['url']}\nNote: Verify the source and current details before recording.")
        item = {"id": str(uuid.uuid4()), "news_id": news_id, "script": script, "created_at": utcnow()}
        self.db.execute("INSERT INTO scripts VALUES(?,?,?,?)", tuple(item.values())); self.db.commit()
        self._audit("script.generated", {"news_id": news_id, "script_id": item["id"], "provider": "offline-template"})
        return item

    def browser_profile(self, agent_slug: str) -> Dict[str, Any]:
        self.get_agent(agent_slug)
        path = self.profile_dir / re.sub(r"[^a-z0-9-]", "-", agent_slug.lower())
        path.mkdir(parents=True, exist_ok=True)
        return {"agent_slug": agent_slug, "profile_dir": str(path), "persistent": True}

    # ── Telegram ──────────────────────────────────────────────────────────────

    def telegram_register(self, chat_id: str, agent_slug: str) -> Dict[str, Any]:
        """Link a Telegram chat_id to an agent."""
        self.get_agent(agent_slug)
        now = utcnow()
        self.db.execute("""INSERT OR REPLACE INTO telegram_sessions(chat_id,agent_slug,created_at,updated_at)
                            VALUES(?,?,COALESCE((SELECT created_at FROM telegram_sessions WHERE chat_id=?),?),?)""",
                        (chat_id, agent_slug, chat_id, now, now))
        self.db.commit()
        self._audit("telegram.linked", {"chat_id": chat_id, "agent": agent_slug})
        return {"chat_id": chat_id, "agent_slug": agent_slug}

    def telegram_agent_for(self, chat_id: str) -> Optional[str]:
        """Return the agent slug for a Telegram chat, or None."""
        row = self.db.execute("SELECT agent_slug FROM telegram_sessions WHERE chat_id=?", (chat_id,)).fetchone()
        return row[0] if row else None

    def telegram_save_incoming(self, chat_id: str, update_id: int, text: Optional[str], file_id: Optional[str],
                                first: str, last: str) -> Dict[str, Any]:
        """Log an incoming Telegram message/voice for audit."""
        item = {
            "chat_id": chat_id, "update_id": update_id,
            "message_text": text, "voice_file_id": file_id,
            "from_first": first, "from_last": last,
            "received_at": utcnow()
        }
        self.db.execute(
            "INSERT INTO telegram_incoming(chat_id,update_id,message_text,voice_file_id,from_first,from_last,received_at) VALUES(?,?,?,?,?,?,?)",
            (chat_id, update_id, text, file_id, first, last, item["received_at"]))
        self.db.commit()
        self._audit("telegram.incoming", {"chat_id": chat_id, "update_id": update_id, "has_text": bool(text), "has_voice": bool(file_id)})
        return item

    def list_telegram_sessions(self) -> List[Dict[str, Any]]:
        rows = self.db.execute("SELECT chat_id, agent_slug, created_at FROM telegram_sessions").fetchall()
        return [{"chat_id": r[0], "agent_slug": r[1], "created_at": r[2]} for r in rows]

    # ── LinkedIn Accounts ───────────────────────────────────────────────────

    def list_linkedin_accounts(self) -> List[Dict[str, Any]]:
        rows = self.db.execute("SELECT slug, name, username, status, last_used, created_at FROM linkedin_accounts").fetchall()
        return [{"slug": r[0], "name": r[1], "username": r[2], "status": r[3],
                 "last_used": r[4], "created_at": r[5]} for r in rows]

    def add_linkedin_account(self, data: Dict[str, Any]) -> Dict[str, Any]:
        slug = re.sub(r"[^a-z0-9_-]", "-", data.get("name", data["username"]).lower())[:40]
        password_b64 = base64.b64encode(data["password"].encode()).decode()
        now = utcnow()
        self.db.execute(
            "INSERT OR REPLACE INTO linkedin_accounts(slug,name,username,password_b64,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)",
            (slug, data["name"], data["username"], password_b64, "idle", now, now))
        self.db.commit()
        self._audit("linkedin.account_added", {"slug": slug, "name": data["name"]})
        return self.get_linkedin_account(slug)

    def get_linkedin_account(self, slug: str) -> Dict[str, Any]:
        row = self.db.execute("SELECT slug, name, username, status, last_used, created_at FROM linkedin_accounts WHERE slug=?", (slug,)).fetchone()
        if not row:
            raise KeyError("LinkedIn account not found")
        return {"slug": row[0], "name": row[1], "username": row[2], "status": row[3], "last_used": row[4], "created_at": row[5]}

    def get_linkedin_password(self, slug: str) -> str:
        import base64
        row = self.db.execute("SELECT password_b64 FROM linkedin_accounts WHERE slug=?", (slug,)).fetchone()
        if not row:
            raise KeyError("LinkedIn account not found")
        return base64.b64decode(row[0]).decode()

    def remove_linkedin_account(self, slug: str) -> None:
        self.db.execute("DELETE FROM linkedin_accounts WHERE slug=?", (slug,))
        self.db.commit()
        self._audit("linkedin.account_removed", {"slug": slug})

    def mark_linkedin_used(self, slug: str) -> None:
        self.db.execute("UPDATE linkedin_accounts SET last_used=?, status='in_use' WHERE slug=?", (utcnow(), slug))
        self.db.commit()

    # ── Delegations (CEO → specialist agents) ────────────────────────────────

    def create_delegation(self, parent_slug: str, target_agent: str,
                           task_type: str, instruction: str) -> Dict[str, Any]:
        """Create a task delegated from a parent agent to a specialist."""
        self.get_agent(target_agent)
        item = {
            "id": str(uuid.uuid4()),
            "parent_slug": parent_slug,
            "target_agent": target_agent,
            "task_type": task_type,
            "instruction": instruction,
            "status": "pending",
            "created_at": utcnow(),
            "updated_at": utcnow(),
        }
        self.db.execute(
            "INSERT INTO delegations(id,parent_slug,target_agent,task_type,instruction,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            tuple(item.values()))
        self.db.commit()
        self._audit("delegation.created", {
            "id": item["id"], "parent": parent_slug,
            "target": target_agent, "type": task_type})
        return item

    def list_delegations(self, agent_slug: str = None, status: str = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM delegations WHERE 1=1"
        params = []
        if agent_slug:
            query += " AND target_agent=? AND parent_slug!=?"
            params += [agent_slug, agent_slug]
        if status:
            query += " AND status=?"
            params.append(status)
        query += " ORDER BY created_at DESC"
        return [dict(r) for r in self.db.execute(query, params)]

    def update_delegation_status(self, delegation_id: str, status: str) -> Dict[str, Any]:
        now = utcnow()
        self.db.execute("UPDATE delegations SET status=?,updated_at=? WHERE id=?", (status, now, delegation_id))
        self.db.commit()
        self._audit("delegation.status", {"id": delegation_id, "status": status})
        row = self.db.execute("SELECT * FROM delegations WHERE id=?", (delegation_id,)).fetchone()
        return dict(row) if row else {}

    # ── Job Applications ───────────────────────────────────────────────────────

    def create_job_application(self, data: Dict[str, Any]) -> Dict[str, Any]:
        item = dict(data)
        item["id"] = str(uuid.uuid4())
        now = utcnow()
        self.db.execute(
            "INSERT INTO job_applications(id,company,role,location,salary,status,job_url,job_description,delegation_id,tailored_resume_path,email_draft,email_subject,applied_at,replied_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (item["id"], item.get("company",""), item.get("role",""), item.get("location",""), item.get("salary",""),
             item.get("status","found"), item.get("job_url",""), item.get("job_description",""),
             item.get("delegation_id") or None, item.get("tailored_resume_path",""), item.get("email_draft",""),
             item.get("email_subject",""), item.get("applied_at"), item.get("replied_at"), now, now))
        self.db.commit()
        self._audit("job_application.created", {"id": item["id"], "company": item.get("company")})
        return item

    def list_job_applications(self, status: str = None) -> List[Dict[str, Any]]:
        query = "SELECT * FROM job_applications"
        params = []
        if status:
            query += " WHERE status=?"
            params.append(status)
        query += " ORDER BY created_at DESC"
        return [dict(r) for r in self.db.execute(query, params)]

    def get_job_application(self, app_id: str) -> Dict[str, Any]:
        row = self.db.execute("SELECT * FROM job_applications WHERE id=?", (app_id,)).fetchone()
        if not row:
            raise KeyError("Job application not found")
        return dict(row)

    def update_job_application(self, app_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        row = self.db.execute("SELECT * FROM job_applications WHERE id=?", (app_id,)).fetchone()
        if not row:
            raise KeyError("Job application not found")
        fields = []
        values = []
        for key in ["company","role","location","salary","status","job_url","job_description",
                     "delegation_id","tailored_resume_path","email_draft","email_subject",
                     "applied_at","replied_at"]:
            if key in data:
                fields.append(f"{key}=?")
                values.append(data[key])
        fields.append("updated_at=?")
        values.append(utcnow())
        values.append(app_id)
        self.db.execute(f"UPDATE job_applications SET {','.join(fields)} WHERE id=?", values)
        self.db.commit()
        self._audit("job_application.updated", {"id": app_id, "fields": list(data.keys())})
        return self.get_job_application(app_id)

    def delete_job_application(self, app_id: str) -> None:
        self.db.execute("DELETE FROM job_applications WHERE id=?", (app_id,))
        self.db.commit()
        self._audit("job_application.deleted", {"id": app_id})

    def save_base_resume(self, filename: str, content: bytes) -> Dict[str, Any]:
        original = Path(filename).name
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", original).strip("._") or "resume.pdf"
        candidate = safe
        count = 1
        while (self.upload_dir / candidate).exists():
            candidate = f"{Path(safe).stem}-{count}{Path(safe).suffix}"; count += 1
        (self.upload_dir / candidate).write_bytes(content)
        item = {
            "id": str(uuid.uuid4()), "original_name": original,
            "stored_name": candidate, "size": len(content),
            "sha256": hashlib.sha256(content).hexdigest(), "created_at": utcnow()
        }
        self.db.execute("INSERT INTO base_resume VALUES(?,?,?,?,?,?)",
                        tuple(item.values()))
        self.db.commit()
        self._audit("base_resume.uploaded", {"id": item["id"], "stored_name": candidate})
        return item

    def get_base_resume(self) -> Optional[Dict[str, Any]]:
        row = self.db.execute("SELECT * FROM base_resume ORDER BY created_at DESC LIMIT 1").fetchone()
        return dict(row) if row else None

    # ── Inbox: company email replies ───────────────────────────────────────

    INBOX_STATUSES = {"new", "drafted", "awaiting_approval", "approved",
                      "sent", "denied", "archived"}

    def ingest_email(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Store one inbound email. Idempotent on message_id: a repeated
        delivery from n8n returns the existing record instead of duplicating it.

        Only message metadata and body text are stored — never credentials,
        OAuth tokens or raw provider headers.
        """
        message_id = str(data.get("message_id") or "").strip()
        if not message_id:
            raise ValueError("message_id is required so repeated deliveries are not duplicated")
        existing = self.db.execute("SELECT * FROM inbox_emails WHERE message_id=?", (message_id,)).fetchone()
        if existing:
            item = self._row(existing)
            item["duplicate"] = True
            return item
        now = utcnow()
        item = {
            "id": str(uuid.uuid4()),
            "message_id": message_id,
            "source": str(data.get("source") or "n8n")[:40],
            "from_name": str(data.get("from_name") or "")[:200],
            "from_address": str(data.get("from_address") or "")[:320],
            "to_address": str(data.get("to_address") or "")[:320],
            "subject": str(data.get("subject") or "")[:500],
            "body": str(data.get("body") or "")[:200_000],
            "received_at": str(data.get("received_at") or now)[:64],
            "company": str(data.get("company") or "")[:200],
            "category": str(data.get("category") or "other")[:40],
            "confidence": float(data.get("confidence") or 0.0),
            "signals": list(data.get("signals") or []),
            "language": str(data.get("language") or "en")[:8],
            "status": "new",
            "draft_subject": "",
            "draft_body": "",
            "draft_source": "",
            "action_id": None,
            "job_application_id": data.get("job_application_id"),
            "provider_message_id": "",
            "replied_at": None,
            "created_at": now,
            "updated_at": now,
        }
        self.db.execute(
            """INSERT INTO inbox_emails(id,message_id,source,from_name,from_address,to_address,subject,body,
               received_at,company,category,confidence,signals_json,language,status,draft_subject,draft_body,
               draft_source,action_id,job_application_id,provider_message_id,replied_at,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (item["id"], item["message_id"], item["source"], item["from_name"], item["from_address"],
             item["to_address"], item["subject"], item["body"], item["received_at"], item["company"],
             item["category"], item["confidence"], json_dump(item["signals"]), item["language"], item["status"],
             "", "", "", None, item["job_application_id"], "", None, now, now))
        self.db.commit()
        # The audit trail records that a message arrived and how it was classified.
        # It deliberately does not copy the body.
        self._audit("inbox.received", {"id": item["id"], "from": item["from_address"],
                                       "subject": item["subject"][:120], "category": item["category"],
                                       "confidence": round(item["confidence"], 2)})
        item["duplicate"] = False
        return item

    def list_inbox(self, status: Optional[str] = None, limit: int = 200) -> List[Dict[str, Any]]:
        if status:
            rows = self.db.execute(
                "SELECT * FROM inbox_emails WHERE status=? ORDER BY received_at DESC, created_at DESC LIMIT ?",
                (status, max(1, min(limit, 500)))).fetchall()
        else:
            rows = self.db.execute(
                "SELECT * FROM inbox_emails ORDER BY received_at DESC, created_at DESC LIMIT ?",
                (max(1, min(limit, 500)),)).fetchall()
        return [self._row(r) for r in rows]

    def get_email(self, email_id: str) -> Dict[str, Any]:
        row = self.db.execute("SELECT * FROM inbox_emails WHERE id=?", (email_id,)).fetchone()
        if not row:
            raise KeyError("Email not found")
        return self._row(row)

    def update_email(self, email_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
        self.get_email(email_id)
        allowed = ("company", "category", "confidence", "status", "draft_subject", "draft_body",
                   "draft_source", "action_id", "job_application_id", "provider_message_id", "replied_at")
        changes = {k: v for k, v in data.items() if k in allowed}
        if "status" in changes and changes["status"] not in self.INBOX_STATUSES:
            raise ValueError("Unknown inbox status")
        if "signals" in data:
            changes["signals_json"] = json_dump(list(data["signals"]))
        if not changes:
            return self.get_email(email_id)
        changes["updated_at"] = utcnow()
        assignments = ",".join(f"{key}=?" for key in changes)
        self.db.execute(f"UPDATE inbox_emails SET {assignments} WHERE id=?",
                        (*changes.values(), email_id))
        self.db.commit()
        self._audit("inbox.updated", {"id": email_id, "fields": sorted(changes)})
        return self.get_email(email_id)

    def inbox_summary(self) -> Dict[str, Any]:
        rows = self.db.execute("SELECT status, COUNT(*) FROM inbox_emails GROUP BY status").fetchall()
        by_status = {r[0]: r[1] for r in rows}
        rows = self.db.execute("SELECT category, COUNT(*) FROM inbox_emails GROUP BY category").fetchall()
        return {"by_status": by_status, "by_category": {r[0]: r[1] for r in rows},
                "total": sum(by_status.values())}

    def mark_email_sent(self, email_id: str, provider_message_id: str) -> Dict[str, Any]:
        """Record a *confirmed* send. Called back by the automation that actually
        delivered the reply, carrying the provider's own message id. Without that
        confirmation the reply is never shown as sent.
        """
        email = self.get_email(email_id)
        confirmation = str(provider_message_id or "").strip()
        if not confirmation:
            raise ValueError("provider_message_id is required as proof the reply was delivered")
        if email["status"] not in {"approved", "sent"}:
            raise ValueError("Only an approved reply can be marked as sent")
        now = utcnow()
        self.db.execute("UPDATE inbox_emails SET status='sent',provider_message_id=?,replied_at=?,updated_at=? WHERE id=?",
                        (confirmation, now, now, email_id))
        self.db.commit()
        self._audit("inbox.reply_confirmed", {"id": email_id, "provider_message_id": confirmation})
        return self.get_email(email_id)

    def delete_email(self, email_id: str) -> None:
        self.get_email(email_id)
        self.db.execute("DELETE FROM inbox_emails WHERE id=?", (email_id,))
        self.db.commit()
        self._audit("inbox.deleted", {"id": email_id})

    # ── Audit / Activity ───────────────────────────────────────────────────

    def audit_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        rows = self.db.execute("SELECT * FROM audit ORDER BY seq DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
        return [self._row(r) for r in rows]

    def recent_activity(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Unified feed: latest messages, actions, uploads, news across all agents."""
        items = []
        # Recent messages
        rows = self.db.execute(
            "SELECT 'message' as type, id, agent_slug as agent, role as detail, content, created_at "
            "FROM messages ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        for r in rows:
            items.append({"type": "message", "id": r[0], "agent": r[1], "detail": r[2], "content": r[3][:120], "created_at": r[4]})
        # Recent actions
        rows = self.db.execute(
            "SELECT 'action' as type, id, agent_slug as agent, action_type as detail, status, created_at "
            "FROM actions ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        for r in rows:
            items.append({"type": "action", "id": r[0], "agent": r[1], "detail": r[2], "status": r[3], "created_at": r[4]})
        # Sort all by created_at desc, deduplicate by id
        items.sort(key=lambda x: x["created_at"], reverse=True)
        seen = set(); deduped = []
        for it in items:
            if it["id"] not in seen:
                seen.add(it["id"]); deduped.append(it)
        return deduped[:limit]