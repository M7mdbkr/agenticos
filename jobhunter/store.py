"""SQLite state for the job hunter: jobs found, email drafts, mail log, runs and events."""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .textutil import norm

ID_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"
ACTIVE_STATUSES = ("applied", "interview", "assessment", "offer")
OPEN_STATUSES = ("new", "notified", "interested", "drafted")
ALL_STATUSES = OPEN_STATUSES + ACTIVE_STATUSES + ("rejected", "skipped", "closed")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def fingerprint(title: str, company: str, url: str = "") -> str:
    title_key = re.sub(r"\(.*?\)|\[.*?\]", "", norm(title))
    company_key = re.sub(r"\b(inc|llc|ltd|limited|co|company|corp|corporation|gmbh|plc)\b\.?", "", norm(company))
    key = " ".join(title_key.split()) + "|" + " ".join(company_key.split())
    if not company_key.strip():
        key += "|" + (url or "").split("?")[0].lower()
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def short_id(seed: str, length: int = 5) -> str:
    number = int(hashlib.sha1(seed.encode("utf-8")).hexdigest(), 16)
    chars = []
    for _ in range(length):
        number, rem = divmod(number, len(ID_ALPHABET))
        chars.append(ID_ALPHABET[rem])
    return "".join(chars)


class JobStore:
    def __init__(self, db_path: Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(self.path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self._schema()

    def close(self) -> None:
        with self.lock:
            self.db.close()

    def _schema(self) -> None:
        with self.lock:
            self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS jobs(
              id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL UNIQUE,
              source TEXT NOT NULL, sources_json TEXT NOT NULL DEFAULT '[]', external_id TEXT NOT NULL DEFAULT '',
              title TEXT NOT NULL, company TEXT NOT NULL DEFAULT '', location TEXT NOT NULL DEFAULT '',
              remote INTEGER NOT NULL DEFAULT 0, url TEXT NOT NULL DEFAULT '', apply_email TEXT NOT NULL DEFAULT '',
              description TEXT NOT NULL DEFAULT '', salary TEXT NOT NULL DEFAULT '', posted_at TEXT,
              score INTEGER NOT NULL DEFAULT 0, reasons_json TEXT NOT NULL DEFAULT '[]',
              status TEXT NOT NULL DEFAULT 'new', notes TEXT NOT NULL DEFAULT '', cover_letter TEXT NOT NULL DEFAULT '',
              applied_at TEXT, last_contact_at TEXT, last_inbound_message_id TEXT, last_inbound_from TEXT,
              last_inbound_subject TEXT, followups INTEGER NOT NULL DEFAULT 0,
              found_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status, score);
            CREATE TABLE IF NOT EXISTS outbox(
              id TEXT PRIMARY KEY, job_id TEXT NOT NULL, kind TEXT NOT NULL,
              to_addr TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
              attach_cv INTEGER NOT NULL DEFAULT 0, in_reply_to TEXT, status TEXT NOT NULL DEFAULT 'draft',
              message_id TEXT, created_at TEXT NOT NULL, sent_at TEXT
            );
            CREATE TABLE IF NOT EXISTS mail_log(
              id INTEGER PRIMARY KEY AUTOINCREMENT, direction TEXT NOT NULL, message_id TEXT,
              in_reply_to TEXT, from_addr TEXT NOT NULL DEFAULT '', to_addr TEXT NOT NULL DEFAULT '',
              subject TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL, job_id TEXT,
              classification TEXT NOT NULL DEFAULT '', snippet TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS mail_log_msgid ON mail_log(message_id);
            CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(
              id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, message TEXT NOT NULL,
              detail_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs(
              id INTEGER PRIMARY KEY AUTOINCREMENT, reason TEXT NOT NULL, started_at TEXT NOT NULL,
              finished_at TEXT, fetched INTEGER NOT NULL DEFAULT 0, new INTEGER NOT NULL DEFAULT 0,
              matches INTEGER NOT NULL DEFAULT 0, per_source_json TEXT NOT NULL DEFAULT '{}',
              errors_json TEXT NOT NULL DEFAULT '{}'
            );
            """)
            self.db.commit()

    # ── rows ────────────────────────────────────────────────────────────────
    @staticmethod
    def _job(row: sqlite3.Row) -> Dict[str, Any]:
        job = dict(row)
        job["sources"] = json.loads(job.pop("sources_json") or "[]")
        job["reasons"] = json.loads(job.pop("reasons_json") or "[]")
        job["remote"] = bool(job["remote"])
        return job

    # ── state ───────────────────────────────────────────────────────────────
    def get_state(self, key: str, default: Any = None) -> Any:
        with self.lock:
            row = self.db.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_state(self, key: str, value: Any) -> None:
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO state(key,value) VALUES(?,?)", (key, json.dumps(value)))
            self.db.commit()

    # ── events ──────────────────────────────────────────────────────────────
    def event(self, kind: str, message: str, **detail: Any) -> None:
        with self.lock:
            self.db.execute("INSERT INTO events(kind,message,detail_json,created_at) VALUES(?,?,?,?)",
                            (kind, message[:500], json.dumps(detail, ensure_ascii=False, default=str), utcnow()))
            self.db.execute("DELETE FROM events WHERE id <= (SELECT MAX(id) FROM events) - 2000")
            self.db.commit()

    def events(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["detail"] = json.loads(item.pop("detail_json") or "{}")
            out.append(item)
        return out

    # ── jobs ────────────────────────────────────────────────────────────────
    def _new_id(self, seed: str) -> str:
        for attempt in range(50):
            candidate = short_id(f"{seed}:{attempt}")
            if not self.db.execute("SELECT 1 FROM jobs WHERE id=?", (candidate,)).fetchone():
                return candidate
        raise RuntimeError("Could not allocate a job id")

    def upsert_job(self, item: Dict[str, Any], score: int, reasons: List[str]) -> tuple:
        """Insert a new job or merge the source into an existing one. Returns (job, created)."""
        fp = fingerprint(item.get("title", ""), item.get("company", ""), item.get("url", ""))
        now = utcnow()
        with self.lock:
            row = self.db.execute("SELECT * FROM jobs WHERE fingerprint=?", (fp,)).fetchone()
            if row:
                job = self._job(row)
                sources = job["sources"]
                changes: Dict[str, Any] = {}
                if item.get("source") and item["source"] not in sources:
                    changes["sources_json"] = json.dumps(sources + [item["source"]])
                for key in ("description", "apply_email", "salary", "location"):
                    if item.get(key) and len(str(item[key])) > len(str(job.get(key) or "")):
                        changes[key] = item[key]
                if score > job["score"]:
                    changes["score"] = score
                    changes["reasons_json"] = json.dumps(reasons, ensure_ascii=False)
                if changes:
                    changes["updated_at"] = now
                    cols = ",".join(f"{k}=?" for k in changes)
                    self.db.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*changes.values(), job["id"]))
                    self.db.commit()
                return self.get_job(job["id"]), False
            job_id = self._new_id(fp)
            self.db.execute(
                """INSERT INTO jobs(id,fingerprint,source,sources_json,external_id,title,company,location,remote,url,
                   apply_email,description,salary,posted_at,score,reasons_json,status,found_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (job_id, fp, item.get("source", "manual"), json.dumps([item.get("source", "manual")]),
                 str(item.get("external_id", ""))[:120], item.get("title", "")[:300], item.get("company", "")[:200],
                 item.get("location", "")[:200], int(bool(item.get("remote"))), item.get("url", "")[:1000],
                 item.get("apply_email", "")[:200], item.get("description", "")[:20000], item.get("salary", "")[:120],
                 item.get("posted_at"), int(score), json.dumps(reasons, ensure_ascii=False), "new", now, now))
            self.db.commit()
            return self.get_job(job_id), True

    def get_job(self, job_id: str) -> Dict[str, Any]:
        with self.lock:
            row = self.db.execute("SELECT * FROM jobs WHERE id=?", (job_id.upper(),)).fetchone()
        if not row:
            raise KeyError(f"No job with id {job_id}")
        return self._job(row)

    def update_job(self, job_id: str, **changes: Any) -> Dict[str, Any]:
        allowed = {"status", "notes", "cover_letter", "applied_at", "last_contact_at", "last_inbound_message_id",
                   "last_inbound_from", "last_inbound_subject", "followups", "apply_email", "description",
                   "score", "location", "title", "company", "salary"}
        changes = {k: v for k, v in changes.items() if k in allowed}
        if "status" in changes and changes["status"] not in ALL_STATUSES:
            raise ValueError(f"Unknown status {changes['status']}")
        if not changes:
            return self.get_job(job_id)
        changes["updated_at"] = utcnow()
        with self.lock:
            cur = self.db.execute(f"UPDATE jobs SET {','.join(f'{k}=?' for k in changes)} WHERE id=?",
                                  (*changes.values(), job_id.upper()))
            self.db.commit()
        if not cur.rowcount:
            raise KeyError(f"No job with id {job_id}")
        return self.get_job(job_id)

    def set_reasons(self, job_id: str, score: int, reasons: List[str]) -> None:
        with self.lock:
            self.db.execute("UPDATE jobs SET score=?, reasons_json=?, updated_at=? WHERE id=?",
                            (int(score), json.dumps(reasons, ensure_ascii=False), utcnow(), job_id))
            self.db.commit()

    def list_jobs(self, statuses: Optional[Iterable[str]] = None, min_score: int = 0, query: str = "",
                  limit: int = 100, order: str = "score") -> List[Dict[str, Any]]:
        sql = "SELECT * FROM jobs WHERE score >= ?"
        params: List[Any] = [int(min_score)]
        statuses = list(statuses or [])
        if statuses:
            sql += f" AND status IN ({','.join('?' * len(statuses))})"
            params += statuses
        if query:
            sql += " AND (title LIKE ? OR company LIKE ? OR location LIKE ?)"
            like = f"%{query}%"
            params += [like, like, like]
        sql += " ORDER BY " + ("score DESC, found_at DESC" if order == "score" else "updated_at DESC")
        sql += " LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        with self.lock:
            rows = self.db.execute(sql, params).fetchall()
        return [self._job(r) for r in rows]

    def counts(self) -> Dict[str, int]:
        with self.lock:
            rows = self.db.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status").fetchall()
        counts = {status: 0 for status in ALL_STATUSES}
        counts.update({r[0]: r[1] for r in rows})
        counts["total"] = sum(r[1] for r in rows)
        return counts

    def jobs_found_since(self, iso: str, min_score: int = 0) -> int:
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM jobs WHERE found_at >= ? AND score >= ?",
                                   (iso, min_score)).fetchone()[0]

    def followups_due(self, days: int, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        now = now or datetime.now(timezone.utc)
        cutoff = (now - timedelta(days=days)).isoformat()
        with self.lock:
            rows = self.db.execute(
                """SELECT * FROM jobs WHERE status='applied' AND applied_at IS NOT NULL AND applied_at <= ?
                   AND (last_contact_at IS NULL OR last_contact_at <= ?) AND followups < 2
                   ORDER BY applied_at""", (cutoff, cutoff)).fetchall()
        return [self._job(r) for r in rows]

    # ── outbox (emails to employers — always need your approval) ───────────
    def add_draft(self, job_id: str, kind: str, to_addr: str, subject: str, body: str,
                  attach_cv: bool, in_reply_to: Optional[str] = None) -> Dict[str, Any]:
        now = utcnow()
        draft_id = short_id(f"{job_id}:{kind}:{now}", 6)
        with self.lock:
            self.db.execute("UPDATE outbox SET status='replaced' WHERE job_id=? AND status='draft'", (job_id,))
            self.db.execute(
                "INSERT INTO outbox(id,job_id,kind,to_addr,subject,body,attach_cv,in_reply_to,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (draft_id, job_id, kind, to_addr, subject, body, int(bool(attach_cv)), in_reply_to, "draft", now))
            self.db.commit()
        return self.get_draft(draft_id)

    def get_draft(self, draft_id: str) -> Dict[str, Any]:
        with self.lock:
            row = self.db.execute("SELECT * FROM outbox WHERE id=?", (draft_id,)).fetchone()
        if not row:
            raise KeyError("Draft not found")
        item = dict(row)
        item["attach_cv"] = bool(item["attach_cv"])
        return item

    def pending_draft(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            row = self.db.execute("SELECT id FROM outbox WHERE job_id=? AND status='draft' ORDER BY created_at DESC LIMIT 1",
                                  (job_id,)).fetchone()
        return self.get_draft(row[0]) if row else None

    def update_draft(self, draft_id: str, **changes: Any) -> Dict[str, Any]:
        allowed = {"to_addr", "subject", "body", "attach_cv", "status", "message_id", "sent_at"}
        changes = {k: (int(v) if k == "attach_cv" else v) for k, v in changes.items() if k in allowed}
        if changes:
            with self.lock:
                self.db.execute(f"UPDATE outbox SET {','.join(f'{k}=?' for k in changes)} WHERE id=?",
                                (*changes.values(), draft_id))
                self.db.commit()
        return self.get_draft(draft_id)

    def list_drafts(self, status: str = "draft") -> List[Dict[str, Any]]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM outbox WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
        return [dict(r, attach_cv=bool(r["attach_cv"])) for r in rows]

    def sent_message_id(self, job_id: str, kind: str = "application") -> Optional[str]:
        with self.lock:
            row = self.db.execute("SELECT message_id FROM outbox WHERE job_id=? AND kind=? AND status='sent' "
                                  "ORDER BY sent_at DESC LIMIT 1", (job_id, kind)).fetchone()
        return row[0] if row else None

    def job_for_message_ids(self, message_ids: Iterable[str]) -> Optional[str]:
        ids = [m for m in message_ids if m]
        if not ids:
            return None
        marks = ",".join("?" * len(ids))
        with self.lock:
            row = self.db.execute(f"SELECT job_id FROM outbox WHERE message_id IN ({marks}) LIMIT 1", ids).fetchone()
            if not row:
                row = self.db.execute(
                    f"SELECT job_id FROM mail_log WHERE message_id IN ({marks}) AND job_id IS NOT NULL LIMIT 1", ids).fetchone()
        return row[0] if row else None

    # ── mail log ────────────────────────────────────────────────────────────
    def seen_message(self, message_id: str) -> bool:
        if not message_id:
            return False
        with self.lock:
            return bool(self.db.execute("SELECT 1 FROM mail_log WHERE message_id=?", (message_id,)).fetchone())

    def own_message(self, message_ids: Iterable[str]) -> bool:
        ids = [m for m in message_ids if m]
        if not ids:
            return False
        with self.lock:
            return bool(self.db.execute(
                f"SELECT 1 FROM mail_log WHERE direction='out' AND message_id IN ({','.join('?' * len(ids))})", ids).fetchone())

    def log_mail(self, direction: str, kind: str, message_id: str = "", in_reply_to: str = "", from_addr: str = "",
                 to_addr: str = "", subject: str = "", job_id: Optional[str] = None, classification: str = "",
                 snippet: str = "") -> None:
        with self.lock:
            self.db.execute(
                """INSERT INTO mail_log(direction,message_id,in_reply_to,from_addr,to_addr,subject,kind,job_id,
                   classification,snippet,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (direction, message_id, in_reply_to, from_addr, to_addr, subject[:300], kind, job_id,
                 classification, snippet[:500], utcnow()))
            self.db.commit()

    def mail_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        with self.lock:
            rows = self.db.execute("SELECT * FROM mail_log ORDER BY id DESC LIMIT ?", (max(1, min(limit, 500)),)).fetchall()
        return [dict(r) for r in rows]

    # ── runs ────────────────────────────────────────────────────────────────
    def start_run(self, reason: str) -> int:
        with self.lock:
            cur = self.db.execute("INSERT INTO runs(reason,started_at) VALUES(?,?)", (reason, utcnow()))
            self.db.commit()
            return int(cur.lastrowid)

    def finish_run(self, run_id: int, fetched: int, new: int, matches: int,
                   per_source: Dict[str, int], errors: Dict[str, str]) -> None:
        with self.lock:
            self.db.execute(
                "UPDATE runs SET finished_at=?,fetched=?,new=?,matches=?,per_source_json=?,errors_json=? WHERE id=?",
                (utcnow(), fetched, new, matches, json.dumps(per_source), json.dumps(errors), run_id))
            self.db.execute("DELETE FROM runs WHERE id <= (SELECT MAX(id) FROM runs) - 200")
            self.db.commit()

    def last_run(self) -> Optional[Dict[str, Any]]:
        with self.lock:
            row = self.db.execute("SELECT * FROM runs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        if not row:
            return None
        run = dict(row)
        run["per_source"] = json.loads(run.pop("per_source_json"))
        run["errors"] = json.loads(run.pop("errors_json"))
        return run
