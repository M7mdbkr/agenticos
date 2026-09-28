"""The Job Hunter agent.

Every few hours it searches every enabled job source, scores what it finds
against your profile and emails you the best new matches. Every few minutes it
reads your inbox: commands you send it get an answer, employer replies update
the application (interview / rejection / offer…) and job-alert emails from
LinkedIn, Indeed, Bayt… become new leads. Once a day it sends a summary with
follow-ups that are due.

Nothing is ever sent to an employer without your explicit "send <id>".
"""
from __future__ import annotations

import os
import re
import threading
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence

from . import cards, companies, cv as cvlib, notify, writer  # noqa: F401  (importing companies registers its source)
from .commands import Commands, command_lines
from .config import data_dir as default_data_dir, mail_settings
from .inbox import LABELS, classify_reply, is_job_alert, looks_recruiting, match_company, parse_alert
from .mailbox import IncomingMail, MailError, Mailbox
from .profile import is_ready, load_profile, update_profile
from .scoring import score_job
from .sources import ENRICHERS, SOURCES, Query, Source, SourceError, http_get, job as make_job
from .store import ACTIVE_STATUSES, OPEN_STATUSES, JobStore, utcnow
from .textutil import age_days, human_age, norm, snippet, strip_tags, url_domain

try:
    import fcntl
except ImportError:  # Windows: single-instance lock is skipped
    fcntl = None

STORE_FLOOR = 20          # jobs scoring below this are not even stored
MAX_AGE_DAYS = 45         # older postings are ignored
TICK_SECONDS = 20
# name → (minimum minutes between scheduled runs, maximum API calls per run). Keeps free API quotas safe.
SOURCE_BUDGETS = {"jsearch": (1440, 5), "serpapi": (1440, 3), "adzuna": (360, 8)}
DEFAULT_BUDGET = (0, 16)
COMMAND_SUBJECT = re.compile(r"^\s*\[?(jobs?|job ?hunter|agent|cards?|contacts?|وظائف|وظايف|كرت|كروت|بطاقة|بطاقات)\]?(\s*[:\-]|\s*$)", re.I)
_REPLY_PREFIX = re.compile(r"^((re|fwd?|aw|sv)\s*:\s*)+", re.I)


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


class JobHunter:
    def __init__(self, data_dir: Optional[Path] = None, env: Optional[Mapping[str, str]] = None,
                 mailbox: Optional[Any] = None, sources: Optional[Dict[str, Source]] = None,
                 extra_feeds: Optional[Callable[[], List[str]]] = None, brain: Optional[writer.Brain] = None,
                 telegram: Callable[..., bool] = notify.telegram_send, desktop: Callable[..., bool] = notify.desktop_notify,
                 opener: Callable[..., bool] = notify.open_url, request_delay: float = 1.5):
        self.env = os.environ if env is None else env
        self.data_dir = Path(data_dir) if data_dir else default_data_dir(self.env)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = JobStore(self.data_dir / "jobhunter.db")
        self.profile_path = self.data_dir / "profile.json"
        self._mailbox = mailbox
        self.sources = SOURCES if sources is None else sources
        self.extra_feeds = extra_feeds or (lambda: [])
        self._brain = brain
        self._telegram, self._desktop, self._opener = telegram, desktop, opener
        self.request_delay = request_delay
        self.enrich_limit = 12
        self._search_lock = threading.Lock()
        self._inbox_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock_file = None
        self.last_error = ""

    # ── configuration ───────────────────────────────────────────────────────
    def profile(self) -> Dict[str, Any]:
        return load_profile(self.profile_path)

    def update_profile(self, changes: Dict[str, Any]) -> Dict[str, Any]:
        profile = update_profile(self.profile_path, changes)
        self.store.event("profile", "Profile updated", fields=sorted(changes))
        return profile

    @property
    def mailbox(self) -> Any:
        return self._mailbox if self._mailbox is not None else Mailbox(mail_settings(self.env))

    def brain(self) -> writer.Brain:
        if self._brain is not None:
            return self._brain
        profile = self.profile()
        return writer.Brain(profile["brain"], profile["brain_model"], self.data_dir / "brain-work")

    def owner_emails(self, profile: Optional[Dict[str, Any]] = None) -> List[str]:
        profile = profile or self.profile()
        owners = list(profile["owner_emails"])
        for extra in self.env.get("JOBHUNTER_OWNER_EMAIL", "").split(","):
            extra = extra.strip().lower()
            if "@" in extra and extra not in owners:
                owners.append(extra)
        if not owners and self.mailbox.address:
            owners = [self.mailbox.address.lower()]
        return owners

    def _cv_path(self, profile: Dict[str, Any]) -> Optional[Path]:
        if not profile.get("cv_path"):
            return None
        path = Path(profile["cv_path"]).expanduser()
        return path if path.is_file() else None

    def _signature_email(self, profile: Dict[str, Any]) -> str:
        owners = self.owner_emails(profile)
        return owners[0] if owners else ""

    # ── scheduler ───────────────────────────────────────────────────────────
    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _acquire_lock(self) -> bool:
        if fcntl is None:
            return True
        handle = open(self.data_dir / "scheduler.lock", "a+")
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        self._lock_file = handle
        return True

    def _release_lock(self) -> None:
        if self._lock_file is not None:
            try:
                fcntl.flock(self._lock_file, fcntl.LOCK_UN)
            finally:
                self._lock_file.close()
                self._lock_file = None

    def service_running_elsewhere(self) -> bool:
        """True when another process (e.g. the background service) holds the scheduler lock."""
        if self.running or fcntl is None:
            return False
        try:
            with open(self.data_dir / "scheduler.lock", "a+") as handle:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                fcntl.flock(handle, fcntl.LOCK_UN)
            return False
        except OSError:
            return True

    def start(self) -> Dict[str, Any]:
        if self.running:
            return {"running": True}
        if not self._acquire_lock():
            return {"running": False, "error": "Another Job Hunter is already running on this computer "
                                               "(probably the background service). Stop it first."}
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="job-hunter", daemon=True)
        self._thread.start()
        self.store.event("agent", "Agent started")
        return {"running": True}

    def stop(self) -> Dict[str, Any]:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        self._thread = None
        self._release_lock()
        self.store.event("agent", "Agent stopped")
        return {"running": False}

    def run_forever(self) -> None:
        """Foreground loop for the CLI / background service."""
        if not self._acquire_lock():
            raise SystemExit("Another Job Hunter is already running on this computer.")
        self.store.event("agent", "Background service started")
        try:
            self._loop()
        finally:
            self._release_lock()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # keep the agent alive whatever happens
                self.last_error = str(exc)[:300]
                self.store.event("error", f"Agent loop error: {exc}", trace=traceback.format_exc()[-1500:])
            self._stop.wait(TICK_SECONDS)

    def _due(self, key: str, minutes: int, now: datetime) -> bool:
        last = _parse_iso(self.store.get_state(key))
        return last is None or (now - last).total_seconds() >= minutes * 60

    def tick(self, now: Optional[datetime] = None) -> List[str]:
        """Do whatever is due right now. Returns the names of the jobs that ran."""
        now = now or datetime.now(timezone.utc)
        profile = self.profile()
        done = []
        if self.mailbox.configured and self._due("last_inbox_at", profile["inbox_every_minutes"], now):
            self.check_inbox()
            done.append("inbox")
        if profile["paused"] or not is_ready(profile):
            return done
        if self._due("last_search_at", profile["search_every_minutes"], now):
            self.search(reason="scheduled")
            done.append("search")
        if self._summary_due(profile, now):
            self.send_daily_summary(now)
            done.append("summary")
        return done

    def _summary_due(self, profile: Dict[str, Any], now: datetime) -> bool:
        hour = profile["daily_summary_hour"]
        local = now.astimezone()
        return hour >= 0 and local.hour >= hour and self.store.get_state("last_summary_date") != local.date().isoformat()

    # ── searching ───────────────────────────────────────────────────────────
    def _source_wanted(self, name: str, src: Source, profile: Dict[str, Any]) -> bool:
        return bool(profile["sources"].get(name, src.default_on)) and src.configured(self.env)

    def describe_sources(self, profile: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        profile = profile or self.profile()
        last = self.store.last_run() or {}
        return [{"name": name, "label": s.label, "covers": s.covers, "needs": list(s.needs),
                 "configured": s.configured(self.env), "enabled": self._source_wanted(name, s, profile),
                 "wanted": bool(profile["sources"].get(name, s.default_on)),
                 "last_count": (last.get("per_source") or {}).get(name), "last_error": (last.get("errors") or {}).get(name)}
                for name, s in self.sources.items()]

    def _plan(self, profile: Dict[str, Any], query: Optional[str], location: Optional[str]):
        terms = [query] if query else profile["roles"][:4]
        if location:
            return terms, [location]
        locations = [l for l in profile["locations"] if norm(l) not in ("remote", "anywhere")][:3]
        wants_remote = profile["remote_ok"] or any(norm(l) in ("remote", "anywhere") for l in profile["locations"])
        if wants_remote or not locations:
            locations.append("")
        return terms, locations

    def _extra_feeds(self) -> List[str]:
        try:
            return list(self.extra_feeds())
        except Exception:
            return []

    def search(self, query: Optional[str] = None, location: Optional[str] = None, reason: str = "scheduled",
               notify: bool = True) -> Dict[str, Any]:
        if not self._search_lock.acquire(blocking=False):
            return {"busy": True}
        try:
            return self._search(query, location, reason, notify)
        finally:
            self._search_lock.release()

    def _search(self, query, location, reason, notify) -> Dict[str, Any]:
        profile = self.profile()
        scoring = dict(profile)
        if query:
            scoring["roles"] = [query]
        if location:
            scoring["locations"] = [location]
        now = datetime.now(timezone.utc)
        if not query:
            self.store.set_state("last_search_at", now.isoformat())
        run_id = self.store.start_run(reason)
        terms, locations = self._plan(profile, query, location)
        ctx = {"env": self.env, "profile": profile, "extra_feeds": self._extra_feeds(), "delay": self.request_delay}
        last_runs = self.store.get_state("source_last_run", {}) or {}
        per_source: Dict[str, int] = {}
        errors: Dict[str, str] = {}
        fetched: List[Dict[str, Any]] = []
        for name, src in self.sources.items():
            if not self._source_wanted(name, src, profile) or (src.mode != "once" and not terms):
                continue
            every, max_calls = SOURCE_BUDGETS.get(name, DEFAULT_BUDGET)
            last = _parse_iso(last_runs.get(name))
            if not query and every and last and (now - last).total_seconds() < every * 60:
                continue
            if src.mode == "once":
                calls = [Query("", "", profile["level"])]
            elif src.mode == "query":
                calls = [Query(t, "", profile["level"]) for t in terms]
            else:
                calls = [Query(t, l, profile["level"]) for t in terms for l in locations]
            items: List[Dict[str, Any]] = []
            try:
                for index, call in enumerate(calls[:max_calls]):
                    if index:
                        self._stop.wait(self.request_delay)
                    items.extend(src.fetch(call, ctx))
            except SourceError as exc:
                errors[name] = str(exc)
            except Exception as exc:  # a broken adapter must not stop the others
                errors[name] = f"unexpected error: {exc}"
            per_source[name] = len(items)
            fetched.extend(items)
            last_runs[name] = now.isoformat()
        self.store.set_state("source_last_run", last_runs)
        if ctx.get("company_status"):
            self.store.set_state("company_status", {**(self.store.get_state("company_status", {}) or {}), **ctx["company_status"]})

        new_jobs: List[Dict[str, Any]] = []
        run_scores: Dict[str, int] = {}
        for item in fetched:
            if not item.get("title") or (age_days(item.get("posted_at")) or 0) > MAX_AGE_DAYS:
                continue
            score, reasons, blocked = score_job(item, scoring)
            if blocked or score < STORE_FLOOR:
                continue
            stored, created = self.store.upsert_job(item, score, reasons)
            run_scores[stored["id"]] = max(score, run_scores.get(stored["id"], 0))
            if created:
                new_jobs.append(stored)
        new_jobs = self._enrich(new_jobs, scoring, profile["min_score"], errors, run_scores)

        matches = sorted((j for j in new_jobs if j["score"] >= profile["min_score"]), key=lambda j: -j["score"])
        results = []
        for job_id, score in sorted(run_scores.items(), key=lambda kv: -kv[1]):
            if score < profile["min_score"]:
                break
            job = self.store.get_job(job_id)
            if job["status"] not in ("skipped", "closed", "rejected"):
                results.append(job)
        self.store.finish_run(run_id, len(fetched), len(new_jobs), len(matches), per_source, errors)
        self.store.event("search", f"Search ({reason}): {len(fetched)} jobs checked, {len(new_jobs)} new, "
                                   f"{len(matches)} new matches", errors=errors)
        if notify and not query:
            if matches:
                self.send_digest(matches)
            elif profile["notify_when_empty"]:
                self.notify_owner("No new job matches this time",
                                  f"I checked {len(fetched)} postings on {len(per_source)} sites; nothing new above "
                                  f"{profile['min_score']}%. I'll look again in {profile['search_every_minutes']} minutes.",
                                  kind="notice")
        return {"fetched": len(fetched), "new": len(new_jobs), "matches": matches, "results": results,
                "per_source": per_source, "errors": errors}

    def _enrich(self, jobs: List[Dict[str, Any]], scoring: Dict[str, Any], min_score: int,
                errors: Dict[str, str], run_scores: Dict[str, int]) -> List[Dict[str, Any]]:
        """Fetch full descriptions for promising new jobs from list-only sources, then re-score them."""
        budget, broken, out = self.enrich_limit, set(), []
        for job in sorted(jobs, key=lambda j: -j["score"]):
            enricher = ENRICHERS.get(job["source"])
            if not enricher or budget <= 0 or job["source"] in broken or job["score"] < min_score - 15 or job["description"]:
                out.append(job)
                continue
            budget -= 1
            try:
                self._stop.wait(self.request_delay)
                detailed = enricher(job)
            except SourceError as exc:
                broken.add(job["source"])
                errors.setdefault(job["source"], f"details: {exc}")
                out.append(job)
                continue
            score, reasons, blocked = score_job(detailed, scoring)
            self.store.update_job(job["id"], description=detailed.get("description", ""),
                                  apply_email=detailed.get("apply_email", ""))
            self.store.set_reasons(job["id"], 0 if blocked else score, reasons)
            run_scores[job["id"]] = 0 if blocked else score
            out.append(self.store.get_job(job["id"]))
        return out

    def _ingest(self, items: Iterable[Dict[str, Any]], profile: Dict[str, Any]) -> List[Dict[str, Any]]:
        added = []
        for item in items:
            score, reasons, blocked = score_job(item, profile)
            if blocked or score < STORE_FLOOR:
                continue
            stored, created = self.store.upsert_job(item, score, reasons)
            if created and stored["score"] >= profile["min_score"]:
                added.append(stored)
        return added

    # ── talking to you ──────────────────────────────────────────────────────
    def remember_list(self, ids: Sequence[str], message_id: Optional[str] = None) -> None:
        self.store.set_state("last_list", list(ids))
        if message_id:
            lists = self.store.get_state("lists", {}) or {}
            lists[message_id] = list(ids)
            self.store.set_state("lists", dict(list(lists.items())[-40:]))

    def notify_owner(self, subject: str, text: str, html: Optional[str] = None, kind: str = "notice",
                     list_ids: Optional[Sequence[str]] = None, short: Optional[str] = None,
                     job_id: Optional[str] = None) -> Dict[str, bool]:
        profile = self.profile()
        used: Dict[str, bool] = {}
        mailbox = self.mailbox
        owners = self.owner_emails(profile)
        if profile["notify_email"] and mailbox.configured and owners:
            try:
                message_id = mailbox.send(owners[0], subject, text, html=html, agent_kind=kind)
                self.store.log_mail("out", kind, message_id=message_id, to_addr=owners[0], subject=subject,
                                    job_id=job_id, snippet=text[:300])
                if list_ids:
                    self.remember_list(list_ids, message_id)
                used["email"] = True
            except MailError as exc:
                used["email"] = False
                self.last_error = str(exc)
                self.store.event("error", f"Could not email you: {exc}")
        if list_ids and not used.get("email"):
            self.remember_list(list_ids)
        token, chat = self.env.get("TELEGRAM_BOT_TOKEN", ""), profile["telegram_chat_id"]
        if profile["notify_telegram"] and token and chat:
            used["telegram"] = bool(self._telegram(token, chat, f"{subject}\n\n{text}"))
        if profile["notify_desktop"]:
            used["desktop"] = bool(self._desktop("Job Hunter", short or subject))
        self.store.event("notice", subject, notice=kind, channels=[k for k, v in used.items() if v])
        return used

    def send_digest(self, jobs: List[Dict[str, Any]], intro: Optional[str] = None) -> Dict[str, bool]:
        profile = self.profile()
        shown = jobs[: profile["digest_max"]]
        more = len(jobs) - len(shown)
        intro = intro or (f"I found {len(jobs)} new job{'s' if len(jobs) != 1 else ''} that match you"
                          + (f" (best {len(shown)} below — reply \"jobs 25\" for more)" if more else "") + ":")
        body = writer.digest(shown, profile["name"], intro)
        top = shown[0]
        subject = (f"🔎 {len(jobs)} new job match{'es' if len(jobs) != 1 else ''}: {top['title']}"
                   + (f" at {top['company']}" if top["company"] else ""))
        used = self.notify_owner(subject, body["text"], body["html"], kind="digest", list_ids=[j["id"] for j in shown],
                                 short=f"{len(jobs)} new matches — top: {top['title']} ({top['score']}%)")
        for job in shown:
            if job["status"] == "new":
                self.store.update_job(job["id"], status="notified")
        return used

    def send_daily_summary(self, now: Optional[datetime] = None) -> Dict[str, bool]:
        now = now or datetime.now(timezone.utc)
        profile = self.profile()
        top = self.top_open_jobs(5)
        fresh = self.store.jobs_found_since((now - timedelta(days=1)).isoformat(), profile["min_score"])
        parts = [f"Good morning{', ' + profile['name'].split()[0] if profile['name'] else ''}! Here is your daily job report.",
                 self.status_text(), f"New matches in the last 24 hours: {fresh}"]
        if top:
            parts.append("Best open matches:\n\n" + "\n\n".join(writer.job_line(j, i + 1) for i, j in enumerate(top)))
        parts.append("Reply with commands — \"help\" lists them all.")
        self.store.set_state("last_summary_date", now.astimezone().date().isoformat())
        return self.notify_owner(f"☀️ Daily job report — {fresh} new match{'es' if fresh != 1 else ''}", "\n\n".join(parts),
                                 kind="summary", list_ids=[j["id"] for j in top], short=f"Daily report: {fresh} new matches")

    def handle_text(self, text: str, channel: str = "web", list_ids: Optional[Sequence[str]] = None) -> str:
        return Commands(self).handle(text, channel, list_ids)

    # ── inbox ───────────────────────────────────────────────────────────────
    def check_inbox(self) -> Dict[str, Any]:
        if not self._inbox_lock.acquire(blocking=False):
            return {"busy": True}
        try:
            self.store.set_state("last_inbox_at", utcnow())
            mailbox = self.mailbox
            if not mailbox.configured:
                return {"error": "Email is not connected"}
            try:
                messages, imap_state = mailbox.fetch_new(self.store.get_state("imap_state", {}) or {})
            except MailError as exc:
                self.last_error = str(exc)
                self.store.event("error", f"Inbox check failed: {exc}")
                return {"error": str(exc)}
            kinds: Dict[str, int] = {}
            alert_jobs: List[Dict[str, Any]] = []
            for msg in messages:
                try:
                    kind = self.process_message(msg, alert_jobs)
                except Exception as exc:
                    kind = "error"
                    self.store.event("error", f"Could not process an email: {exc}", trace=traceback.format_exc()[-1500:])
                kinds[kind] = kinds.get(kind, 0) + 1
            self.store.set_state("imap_state", imap_state)
            if alert_jobs:
                self.send_digest(sorted(alert_jobs, key=lambda j: -j["score"]),
                                 intro=f"Your job-alert emails contained {len(alert_jobs)} new matching job"
                                       f"{'s' if len(alert_jobs) != 1 else ''}:")
            if messages:
                self.store.event("inbox", f"Read {len(messages)} new emails", kinds=kinds)
            return {"checked": len(messages), "kinds": kinds}
        finally:
            self._inbox_lock.release()

    def _sender_verified(self, msg: IncomingMail) -> bool:
        results = msg.auth_results.lower()
        if results:
            return "dmarc=fail" not in results and ("dkim=pass" in results or "spf=pass" in results)
        settings = getattr(self.mailbox, "settings", None)
        return msg.from_addr == (self.mailbox.address or "").lower() or bool(getattr(settings, "trust_unverified", False))

    def _is_command_mail(self, msg: IncomingMail, owners: List[str]) -> bool:
        account = (self.mailbox.address or "").lower()
        if account and account not in owners:
            return True  # a dedicated agent mailbox: everything you send it is for the agent
        if self.store.own_message(msg.thread_ids):
            return True  # a reply to one of the agent's emails
        if msg.images:
            return True  # a photo you sent yourself = a business card to save
        return bool(COMMAND_SUBJECT.search(_REPLY_PREFIX.sub("", msg.subject)))

    def process_message(self, msg: IncomingMail, alert_jobs: Optional[List[Dict[str, Any]]] = None) -> str:
        message_id = msg.message_id or f"<uid-{msg.uid}@imap>"
        if self.store.seen_message(message_id):
            return "duplicate"
        if msg.agent_header or self.store.own_message([message_id]):
            self.store.log_mail("in", "own", message_id=message_id)
            return "own"
        profile = self.profile()
        owners = self.owner_emails(profile)
        if msg.from_addr in owners:
            if not self._is_command_mail(msg, owners):
                self.store.log_mail("in", "ignored", message_id=message_id)  # your own mail that isn't for the agent
                return "ignored"
            if not self._sender_verified(msg):
                self.store.log_mail("in", "unverified", message_id=message_id, from_addr=msg.from_addr, subject=msg.subject)
                self.store.event("security", f"Ignored a command email that failed sender checks: {msg.subject[:80]}")
                return "unverified"
            self._handle_command_mail(msg, message_id)
            return "command"
        job_id = self.store.job_for_message_ids(msg.thread_ids)
        if job_id:
            self._employer_reply(job_id, msg, message_id)
            return "reply"
        tracked = self.store.list_jobs(statuses=ACTIVE_STATUSES + ("drafted",), limit=300, order="updated")
        if is_job_alert(msg):
            job = match_company(msg, tracked, header_only=True)
            if job:
                self._employer_reply(job["id"], msg, message_id)
                return "reply"
            items = parse_alert(msg)
            added = self._ingest(items, profile)
            if alert_jobs is not None:
                alert_jobs.extend(added)
            self.store.log_mail("in", "alert", message_id=message_id, from_addr=msg.from_addr, subject=msg.subject,
                                snippet=f"{len(items)} job links, {len(added)} new matches")
            return "alert"
        job = match_company(msg, tracked)
        if job:
            self._employer_reply(job["id"], msg, message_id)
            return "reply"
        if msg.from_addr not in owners and looks_recruiting(msg):
            self.store.log_mail("in", "recruiter", message_id=message_id, from_addr=msg.from_addr, subject=msg.subject,
                                snippet=snippet(msg.text, 300))
            self.notify_owner(f"📨 Possible recruiter email: {msg.subject[:80]}",
                              f"From: {msg.from_name} <{msg.from_addr}>\nSubject: {msg.subject}\n\n{snippet(msg.text, 1200)}\n\n"
                              "It isn't linked to a job I'm tracking. If it's a real opportunity, reply "
                              "\"track <job link>\" and I'll add it.", kind="recruiter", short=f"Recruiter: {msg.subject[:60]}")
            return "recruiter"
        self.store.log_mail("in", "ignored", message_id=message_id)  # no content stored for unrelated mail
        return "ignored"

    def _handle_command_mail(self, msg: IncomingMail, message_id: str) -> None:
        subject = _REPLY_PREFIX.sub("", msg.subject).strip()
        subject_command = COMMAND_SUBJECT.sub("", subject, count=1).strip(" :-")
        body = "\n".join(command_lines(msg.text))
        card_answers = [self.add_card_image(name, data, source="email") for name, data in msg.images]
        text = body or subject_command or ("" if card_answers else "help")
        lists = self.store.get_state("lists", {}) or {}
        list_ids = next((lists[ref] for ref in msg.thread_ids if ref in lists), None)
        before = self.store.get_state("last_list")
        answer = self.handle_text(text, channel="email", list_ids=list_ids) if text else ""
        answer = "\n\n".join(x for x in card_answers + [answer] if x)
        after = self.store.get_state("last_list")
        self.store.log_mail("in", "command", message_id=message_id, from_addr=msg.from_addr, subject=msg.subject,
                            snippet=text[:300])
        reply_subject = msg.subject if msg.subject.lower().startswith("re:") else f"Re: {msg.subject or 'Job Hunter'}"
        try:
            out_id = self.mailbox.send(msg.from_addr, reply_subject, answer, in_reply_to=msg.message_id or None,
                                       references=msg.references, agent_kind="answer")
            self.store.log_mail("out", "answer", message_id=out_id, to_addr=msg.from_addr, subject=reply_subject,
                                snippet=answer[:300])
            if after != before and after:
                self.remember_list(after, out_id)
        except MailError as exc:
            self.store.event("error", f"Could not reply to your email: {exc}")

    def _employer_reply(self, job_id: str, msg: IncomingMail, message_id: str) -> None:
        job = self.store.get_job(job_id)
        label = classify_reply(msg.subject, msg.text)
        changes: Dict[str, Any] = {"last_contact_at": utcnow(), "last_inbound_message_id": msg.message_id,
                                   "last_inbound_from": msg.from_addr, "last_inbound_subject": msg.subject}
        status_map = {"rejected": "rejected", "offer": "offer", "interview": "interview", "assessment": "assessment"}
        if label in status_map and not (job["status"] == "offer" and label != "offer"):
            changes["status"] = status_map[label]
        elif label == "received" and job["status"] in OPEN_STATUSES:
            changes["status"] = "applied"
            changes["applied_at"] = job["applied_at"] or utcnow()
        self.store.update_job(job_id, **changes)
        self.store.log_mail("in", "reply", message_id=message_id, in_reply_to=msg.in_reply_to, from_addr=msg.from_addr,
                            subject=msg.subject, job_id=job_id, classification=label, snippet=snippet(msg.text, 400))
        company = job["company"] or msg.from_name or msg.from_addr
        if label == "received":
            self.store.event("reply", f"{company} confirmed your application for {job['title']}", job_id=job_id)
            return
        tips = {
            "interview": f"🎉 Reply \"reply {job_id} <your availability>\" and I'll draft an answer in the same email thread; then \"send {job_id}\".",
            "assessment": f"Good luck! Reply \"reply {job_id} <message>\" if you need to answer them.",
            "offer": f"🎉 Congratulations! Reply \"reply {job_id} <message>\" to answer them.",
            "rejected": "Sorry — I've marked it rejected and I'll keep looking.",
            "other": f"Reply \"reply {job_id} <message>\" and I'll draft an answer in the same thread.",
        }
        self.notify_owner(
            f"📬 {company}: {LABELS[label]} — {job['title']}",
            f"[{job_id}] {job['title']} — {job['company']}\nFrom: {msg.from_name} <{msg.from_addr}>\nSubject: {msg.subject}\n\n"
            f"{snippet(msg.text, 1500)}\n\n{tips[label]}",
            kind="reply", job_id=job_id, short=f"{company}: {LABELS[label]}")

    # ── actions on a job (all return a human answer) ────────────────────────
    def top_open_jobs(self, count: int = 10) -> List[Dict[str, Any]]:
        return self.store.list_jobs(statuses=("new", "notified", "interested"), min_score=self.profile()["min_score"],
                                    limit=count)

    def prepare_application(self, job_id: str) -> str:
        job = self.store.get_job(job_id)
        profile = self.profile()
        has_master = bool(self.master_cv().strip())
        letter_profile = {**profile, "cv_path": profile["cv_path"] or ("master" if has_master else "")}
        letter = writer.cover_letter(job, letter_profile, self.brain(), self._signature_email(profile))
        letters = self.data_dir / "letters"
        letters.mkdir(parents=True, exist_ok=True)
        (letters / f"{job['id']}.txt").write_text(letter, encoding="utf-8")
        status = "drafted" if job["status"] in OPEN_STATUSES else job["status"]
        self.store.update_job(job["id"], cover_letter=letter, status=status)
        tailored = self.tailored_cv(job["id"])
        cv = tailored or self._cv_path(profile)
        cv_note = (f"{cv.name} (tailored from your master CV)" if tailored else cv.name) if cv else \
            "none (add a master CV or a CV file in Job Hunter settings)"
        header = f"[{job['id']}] {job['title']} — {job['company'] or 'unknown company'}"
        if job["apply_email"]:
            draft = self.store.add_draft(job["id"], "application", job["apply_email"],
                                         writer.application_subject(job, profile), letter, attach_cv=bool(cv),
                                         attachment=str(tailored or ""))
            return (f"✉ Application ready for {header}\nTo: {draft['to_addr']}\nSubject: {draft['subject']}\n"
                    f"Attachment: {cv_note}\n\n{letter}\n\n"
                    f"→ Reply \"send {job['id']}\" to send it, or \"cancel {job['id']}\".")
        opened = ""
        if profile["open_browser_on_apply"] and job["url"] and self._opener(job["url"], self.data_dir / "browser-profile"):
            opened = "\nI opened the page in your laptop's browser."
        cv_line = f"\nCV to upload: {tailored}" if tailored else ""
        return (f"📝 {header} is applied for on the website:\n{job['url'] or '(no link)'}{opened}{cv_line}\n\n"
                f"Tailored cover letter to paste:\n\n{letter}\n\n"
                f"→ After you submit, reply \"applied {job['id']}\" and I'll watch for their answer and follow up.")

    # ── master CV ───────────────────────────────────────────────────────────
    @property
    def master_cv_path(self) -> Path:
        return self.data_dir / "master_cv.md"

    def master_cv(self) -> str:
        try:
            return self.master_cv_path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def save_master_cv(self, text: str) -> Dict[str, Any]:
        text = (text or "").replace("\r\n", "\n")
        if len(text) > 60_000:
            raise ValueError("The master CV is too long (max 60,000 characters)")
        parsed = cvlib.parse(text)
        if text.strip() and not (parsed.name and parsed.sections):
            raise ValueError("Start with '# Your Name' and use '## Section' headings (see the example)")
        self.master_cv_path.write_text(text, encoding="utf-8")
        self.store.event("cv", "Master CV updated")
        return {"sections": [s.title for s in parsed.sections], "name": parsed.name}

    def tailored_cv(self, job_id: str) -> Optional[Path]:
        """Write a job-specific .docx from the master CV (reorders/trims only — never adds facts)."""
        master = self.master_cv()
        if not master.strip():
            return None
        job = self.store.get_job(job_id)
        tailored = cvlib.tailor(cvlib.parse(master), job, self.profile())
        name = cvlib.safe_filename(tailored.name, "CV", job["company"] or job["title"])
        return cvlib.to_docx(tailored, self.data_dir / "cv" / "tailored" / f"{name}_{job['id']}.docx")

    # ── contacts & business cards ───────────────────────────────────────────
    def add_contact(self, fields: Dict[str, Any], source: str = "manual", image_path: str = "") -> str:
        fields = {k: str(v or "").strip() for k, v in fields.items()}
        if not any(fields.get(k) for k in ("name", "email", "company", "website", "phone")):
            return ("📇 I saved the photo but couldn't read the card. Reply with the details, e.g.\n"
                    "card Ahmed Ali, HR Manager, Acme, ahmed@acme.com, 0551234567")
        contact = self.store.add_contact({**fields, "source": source, "image_path": image_path})
        profile = self.profile()
        lines = [f"📇 Saved contact [{contact['id']}]: " + " · ".join(
            x for x in (contact["name"], contact["title"], contact["company"], contact["email"], contact["phone"], contact["website"]) if x)]
        if contact["website"] and contact["website"] not in profile["company_sites"]:
            self.update_profile({"company_sites": profile["company_sites"] + [contact["website"]]})
            lines.append(f"🌐 I'll watch {contact['website']} for open jobs on every search.")
        if contact["email"]:
            role = profile["roles"][0].title() if profile["roles"] else "Open position"
            item = make_job(f"card:{contact['id']}", f"{role} (open application)", contact["company"] or contact["name"],
                            "", contact["website"], apply_email=contact["email"])
            item["description"] = f"Contact from a business card: {contact['name']} {contact['title']}".strip()
            stored, _ = self.store.upsert_job(item, max(profile["min_score"], 60), [f"business card: {contact['name'] or contact['email']}"])
            self.store.update_job(stored["id"], status="interested", apply_email=contact["email"])
            self.store.update_contact(contact["id"], job_id=stored["id"])
            lines.append(self.prepare_application(stored["id"]))
        else:
            lines.append("No email on the card, so there's nobody to send an application to yet.")
        self.store.event("contact", lines[0][:200], contact_id=contact["id"])
        return "\n\n".join(lines)

    def add_card_image(self, filename: str, data: bytes, source: str = "upload") -> str:
        path = cards.save_image(self.data_dir / "cards", filename, data)
        profile = self.profile()
        fields = cards.read_card(path, profile.get("vision_model", ""))
        method = fields.pop("method", "none")
        fields.pop("raw", None)
        answer = self.add_contact(fields, source=f"{source}:{method}", image_path=str(path))
        note = {"ollama": "\n(Read with the local vision model — double-check the details.)",
                "tesseract": "\n(Read with OCR — double-check the details.)"}.get(method, "")
        return answer + note

    def add_card_text(self, text: str) -> str:
        return self.add_contact(cards.parse_text(text), source="typed")

    def contacts_text(self) -> str:
        contacts = self.store.list_contacts(30)
        if not contacts:
            return "No contacts yet — send me a photo of a business card (email attachment, Telegram or the app)."
        return "Your contacts:\n" + "\n".join(
            f"  [{c['id']}] " + " · ".join(x for x in (c["name"], c["title"], c["company"], c["email"], c["phone"]) if x)
            + (f" → job [{c['job_id']}]" if c["job_id"] else "") for c in contacts)

    def cv_text(self, job_id: Optional[str] = None) -> str:
        if not self.master_cv().strip():
            return ("You don't have a master CV yet. Paste it in Job Hunter → CV, or run "
                    "\"python3 -m jobhunter cv import ATS-1.docx\" on your laptop.")
        if job_id:
            path = self.tailored_cv(job_id)
            return f"Tailored CV for [{job_id.upper()}]: {path}"
        parsed = cvlib.parse(self.master_cv())
        return (f"Master CV: {parsed.name} — sections: {', '.join(s.title for s in parsed.sections)}.\n"
                "Every application gets its own tailored copy (reply \"cv <id>\" to make one now).")

    def send_draft(self, job_id: str) -> str:
        job = self.store.get_job(job_id)
        draft = self.store.pending_draft(job["id"])
        if not draft:
            return f"Nothing is waiting to be sent for [{job['id']}]. Reply \"apply {job['id']}\" first."
        mailbox = self.mailbox
        if not mailbox.configured:
            return "Email isn't connected yet — add it in Job Hunter settings, then reply send again."
        profile = self.profile()
        cv = Path(draft["attachment"]) if draft.get("attachment") and Path(draft["attachment"]).is_file() else self._cv_path(profile)
        attachments = [cv] if draft["attach_cv"] and cv else []
        owners = self.owner_emails(profile)
        bcc = [o for o in owners if o != (mailbox.address or "").lower()][:1]
        try:
            message_id = mailbox.send(draft["to_addr"], draft["subject"], draft["body"], attachments=attachments,
                                      in_reply_to=draft["in_reply_to"], bcc=bcc)
        except MailError as exc:
            return f"⚠️ Could not send [{job['id']}]: {exc}"
        now = utcnow()
        self.store.update_draft(draft["id"], status="sent", message_id=message_id, sent_at=now)
        self.store.log_mail("out", draft["kind"], message_id=message_id, to_addr=draft["to_addr"], subject=draft["subject"],
                            job_id=job["id"], snippet=draft["body"][:300])
        if draft["kind"] == "application":
            self.store.update_job(job["id"], status="applied", applied_at=now)
        elif draft["kind"] == "followup":
            self.store.update_job(job["id"], followups=job["followups"] + 1, last_contact_at=now)
        else:
            self.store.update_job(job["id"], last_contact_at=now)
        self.store.event("sent", f"Sent {draft['kind']} for [{job['id']}] to {draft['to_addr']}", job_id=job["id"])
        follow = f" and suggest a follow-up after {profile['follow_up_days']} days" if draft["kind"] == "application" else ""
        return (f"✅ Sent your {draft['kind']} for [{job['id']}] {job['title']} to {draft['to_addr']}"
                f"{' with ' + cv.name if attachments else ''}. I'll watch your inbox for their answer{follow}.")

    def cancel_draft(self, job_id: str) -> str:
        draft = self.store.pending_draft(job_id.upper())
        if not draft:
            return f"There was no pending email for [{job_id.upper()}]."
        self.store.update_draft(draft["id"], status="cancelled")
        return f"Cancelled the {draft['kind']} for [{job_id.upper()}]. Nothing was sent."

    def mark_applied(self, job_id: str) -> str:
        job = self.store.get_job(job_id)
        self.store.update_job(job["id"], status="applied", applied_at=job["applied_at"] or utcnow())
        return (f"👍 Marked [{job['id']}] {job['title']} as applied. I'll watch for {job['company'] or 'their'} reply and "
                f"suggest a follow-up after {self.profile()['follow_up_days']} days.")

    def set_status(self, job_id: str, status: str) -> str:
        job = self.store.update_job(job_id, status=status)
        draft = self.store.pending_draft(job["id"]) if status in ("skipped", "closed", "rejected") else None
        if draft:
            self.store.update_draft(draft["id"], status="cancelled")
        return f"[{job['id']}] {job['title']} → {status}" + (" (its unsent draft was cancelled)" if draft else "")

    def draft_followup(self, job_id: str) -> str:
        job = self.store.get_job(job_id)
        profile = self.profile()
        letter = writer.followup_letter(job, profile, self._signature_email(profile))
        to = job["last_inbound_from"] or job["apply_email"]
        if to:
            original = self.store.sent_message_id(job["id"])
            in_reply_to = job["last_inbound_message_id"] or original
            subject = ("Re: " + (job["last_inbound_subject"] or writer.application_subject(job, profile))).replace("Re: Re: ", "Re: ")
            self.store.add_draft(job["id"], "followup", to, subject, letter, attach_cv=False, in_reply_to=in_reply_to)
            return (f"Follow-up ready for [{job['id']}] (to {to}):\n\n{letter}\n\n→ Reply \"send {job['id']}\" to send it.")
        self.store.update_job(job["id"], followups=job["followups"] + 1, last_contact_at=utcnow())
        return (f"I don't have an email address for {job['company'] or 'this employer'}, so send this through the site "
                f"or LinkedIn:\n\n{letter}\n\n(I'll count it as followed up.)")

    def draft_reply(self, job_id: str, message: str) -> str:
        job = self.store.get_job(job_id)
        if not job["last_inbound_from"]:
            return f"I haven't received an email from {job['company'] or 'this employer'} yet, so there is nothing to reply to."
        profile = self.profile()
        body = writer.reply_letter(job, profile, message, self._signature_email(profile))
        subject = job["last_inbound_subject"] or job["title"]
        subject = subject if subject.lower().startswith("re:") else f"Re: {subject}"
        self.store.add_draft(job["id"], "reply", job["last_inbound_from"], subject, body, attach_cv=False,
                             in_reply_to=job["last_inbound_message_id"])
        return f"Reply ready (to {job['last_inbound_from']}):\n\n{body}\n\n→ Reply \"send {job['id']}\" to send it."

    def open_job(self, job_id: str) -> str:
        job = self.store.get_job(job_id)
        if not job["url"]:
            return f"[{job['id']}] has no link."
        if self._opener(job["url"], self.data_dir / "browser-profile"):
            return f"Opened [{job['id']}] {job['title']} on your laptop."
        return f"I couldn't open a browser on this computer. Link: {job['url']}"

    def track_url(self, url: str, title: str = "") -> str:
        if not title:
            try:
                page = http_get(url, timeout=15, max_bytes=500_000).decode("utf-8", errors="replace")
                match = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
                title = strip_tags(match.group(1)) if match else ""
            except SourceError:
                title = ""
        profile = self.profile()
        item = make_job("manual", title[:200] or url_domain(url) or "Job", url=url)
        score, reasons, _ = score_job(item, profile)
        stored, _ = self.store.upsert_job(item, max(score, profile["min_score"]), reasons or ["added by you"])
        self.store.update_job(stored["id"], status="interested")
        return f"Tracking [{stored['id']}] {stored['title']}. Reply \"apply {stored['id']}\" when you're ready."

    def edit_profile_list(self, field: str, value: str, add: bool) -> str:
        items = list(self.profile()[field])
        if add and value.lower() not in (i.lower() for i in items):
            items.append(value)
        elif not add:
            items = [i for i in items if i.lower() != value.lower()]
        saved = self.update_profile({field: items})[field]
        label = field.replace("_", " ")
        return f"{'Added' if add else 'Removed'} “{value}”. Your {label}: {', '.join(saved) or '(none)'}"

    def set_paused(self, paused: bool) -> str:
        self.update_profile({"paused": paused})
        return ("⏸ Paused. I'll still answer your emails, but I won't search or send digests until you say \"resume\"."
                if paused else "▶️ Resumed. I'll search again shortly.")

    # ── reporting ───────────────────────────────────────────────────────────
    def status_text(self) -> str:
        profile = self.profile()
        counts = self.store.counts()
        state = "paused" if profile["paused"] else ("running" if self.running else "idle")
        lines = [f"Job Hunter is {state} · searching every {profile['search_every_minutes']} min · "
                 f"inbox every {profile['inbox_every_minutes']} min",
                 "Pipeline: " + " · ".join(f"{counts[s]} {s}" for s in
                                           ("new", "notified", "interested", "drafted", "applied", "interview",
                                            "assessment", "offer", "rejected") if counts[s])
                 if counts["total"] else "Pipeline: empty so far"]
        if not is_ready(profile):
            lines.append("⚠️ Add at least one target role (reply \"add role software engineer\").")
        due = self.store.followups_due(profile["follow_up_days"])
        if due:
            lines.append("Follow-ups due:\n" + "\n".join(
                f"  [{j['id']}] {j['title']} — {j['company']} (applied {human_age(j['applied_at'])}) → \"followup {j['id']}\""
                for j in due[:8]))
        drafts = self.store.list_drafts()
        if drafts:
            lines.append("Waiting for your OK:\n" + "\n".join(
                f"  [{d['job_id']}] {d['kind']} to {d['to_addr']} → \"send {d['job_id']}\"" for d in drafts[:8]))
        run = self.store.last_run()
        if run:
            lines.append(f"Last search {human_age(run['finished_at'])}: {run['fetched']} postings checked, "
                         f"{run['new']} new, {run['matches']} matches"
                         + (f" · problems: {', '.join(run['errors'])}" if run["errors"] else ""))
        return "\n".join(lines)

    def context_for_brain(self) -> str:
        jobs = self.store.list_jobs(statuses=OPEN_STATUSES + ACTIVE_STATUSES, limit=15)
        return self.status_text() + "\n\nJOBS\n" + "\n".join(writer.job_line(j) for j in jobs)

    def status(self) -> Dict[str, Any]:
        profile = self.profile()
        mailbox = self.mailbox
        settings = getattr(mailbox, "settings", None)
        last_search = self.store.get_state("last_search_at")
        next_search = None
        if last_search and not profile["paused"]:
            next_search = (_parse_iso(last_search) + timedelta(minutes=profile["search_every_minutes"])).isoformat()
        cv = self._cv_path(profile)
        return {
            "running": self.running, "service": self.service_running_elsewhere(),
            "paused": profile["paused"], "ready": is_ready(profile),
            "email": settings.public() if settings is not None else {"configured": mailbox.configured, "address": mailbox.address},
            "owners": self.owner_emails(profile),
            "telegram": {"token_set": bool(self.env.get("TELEGRAM_BOT_TOKEN")), "chat_id": profile["telegram_chat_id"]},
            "brain": {"provider": profile["brain"], "model": profile["brain_model"]},
            "cv": cv.name if cv else "",
            "last_search_at": last_search, "next_search_at": next_search,
            "last_inbox_at": self.store.get_state("last_inbox_at"),
            "last_run": self.store.last_run(), "counts": self.store.counts(),
            "drafts": self.store.list_drafts(), "followups_due": self.store.followups_due(profile["follow_up_days"]),
            "sources": self.describe_sources(profile), "last_error": self.last_error,
            "master_cv": bool(self.master_cv().strip()),
            "company_status": self.store.get_state("company_status", {}) or {},
            "keys": {k: bool(self.env.get(k)) for k in ("RAPIDAPI_KEY", "SERPAPI_KEY", "ADZUNA_APP_ID", "ADZUNA_APP_KEY")},
        }
