"""Turn short text commands (from email, Telegram or the web UI) into agent actions."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Callable, List, Optional, Sequence, Tuple

from .store import ID_ALPHABET
from .writer import COMMAND_HELP, answer_question, job_details, job_line

if TYPE_CHECKING:  # pragma: no cover
    from .agent import JobHunter

_ID = re.compile(rf"^[{ID_ALPHABET}]{{5}}$")
_QUOTE_START = re.compile(r"^(>|on .+wrote:?$|-----\s*original message|from:\s|sent from my|في .+ كتب|-- ?$|__+$)", re.I)
_PREFIX = re.compile(r"^/?(?:job ?hunter|jobs?|jh|agent)\s*[:,\-]\s*", re.I)
FIELDS = {"role": "roles", "roles": "roles", "skill": "skills", "skills": "skills", "keyword": "skills",
          "keywords": "skills", "location": "locations", "locations": "locations", "city": "locations",
          "country": "locations", "exclude": "exclude", "excludes": "exclude", "board": "greenhouse_boards",
          "lever": "lever_boards", "feed": "rss_feeds", "rss": "rss_feeds", "email": "owner_emails"}


def command_lines(text: str) -> List[str]:
    """Non-empty lines before the quoted part / signature of a reply."""
    out = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if _QUOTE_START.search(line):
            break
        if line:
            out.append(_PREFIX.sub("", line).strip())
    return [l for l in out if l]


class Commands:
    def __init__(self, hunter: "JobHunter"):
        self.hunter = hunter
        self.routes: List[Tuple[re.Pattern, Callable[..., str]]] = [
            (re.compile(r"^/?(help|commands|\?|start)$", re.I), lambda m, c: COMMAND_HELP),
            (re.compile(r"^/?(status|summary|report|pipeline)$", re.I), lambda m, c: self.hunter.status_text()),
            (re.compile(r"^/?(jobs|list|top|matches|show jobs)(?:\s+(\d{1,2}))?$", re.I), self.list_jobs),
            (re.compile(r"^/?(run|check|refresh|search now|find jobs|find)$", re.I), self.run_now),
            (re.compile(r"^/?search\s+(.+?)(?:\s+in\s+(.+))?$", re.I), self.search),
            (re.compile(r"^/?(details?|info|more|show)\s+(.+)$", re.I), self.details),
            (re.compile(r"^/?(apply|draft)\s+(.+)$", re.I), self.each(lambda jid: self.hunter.prepare_application(jid))),
            (re.compile(r"^/?(send|approve|confirm)\s+(.+)$", re.I), self.each(lambda jid: self.hunter.send_draft(jid))),
            (re.compile(r"^/?(cancel|discard)\s+(.+)$", re.I), self.each(lambda jid: self.hunter.cancel_draft(jid))),
            (re.compile(r"^/?(applied|done)\s+(.+)$", re.I), self.each(lambda jid: self.hunter.mark_applied(jid))),
            (re.compile(r"^/?(skip|hide|not interested|no)\s+(.+)$", re.I), self.each(lambda jid: self.hunter.set_status(jid, "skipped"))),
            (re.compile(r"^/?(save|interested|like|yes)\s+(.+)$", re.I), self.each(lambda jid: self.hunter.set_status(jid, "interested"))),
            (re.compile(r"^/?(interview|offer|rejected|reject|assessment|closed|close)\s+(.+)$", re.I), self.set_status),
            (re.compile(r"^/?(follow ?up|nudge)\s+(.+)$", re.I), self.each(lambda jid: self.hunter.draft_followup(jid))),
            (re.compile(r"^/?reply\s+(\S+)\s+(.+)$", re.I), self.reply),
            (re.compile(r"^/?open\s+(.+)$", re.I), self.open),
            (re.compile(r"^/?note\s+(\S+)\s+(.+)$", re.I), self.note),
            (re.compile(r"^/?(pause|stop)$", re.I), lambda m, c: self.hunter.set_paused(True)),
            (re.compile(r"^/?(resume|unpause|go)$", re.I), lambda m, c: self.hunter.set_paused(False)),
            (re.compile(r"^/?(add|remove)\s+(\w+)\s+(.+)$", re.I), self.edit_profile),
            (re.compile(r"^/?set\s+(min(?:imum)?\s*score|level)\s+(\S+)$", re.I), self.set_setting),
            (re.compile(r"^/?(?:track|add job)\s+(https?://\S+)(?:\s+(.+))?$", re.I), self.track),
            (re.compile(r"^(https?://\S+)$", re.I), self.track),
        ]

    # ── entry point ─────────────────────────────────────────────────────────
    def handle(self, text: str, channel: str = "web", list_ids: Optional[Sequence[str]] = None) -> str:
        self._list_ids = list(list_ids or self.hunter.store.get_state("last_list", []) or [])
        replies, question = [], []
        for line in command_lines(text)[:15]:
            for pattern, handler in self.routes:
                match = pattern.match(line)
                if match and (handler != self.edit_profile or match.group(2).lower() in FIELDS):
                    try:
                        replies.append(handler(match, channel))
                    except (KeyError, ValueError) as exc:
                        replies.append(f"⚠️ {line}: {str(exc).strip(chr(39))}")
                    break
            else:
                question.append(line)
        if replies:
            return "\n\n".join(r for r in replies if r)
        if question:
            asked = " ".join(question)
            answer = answer_question(asked, self.hunter.context_for_brain(), self.hunter.brain())
            if answer:
                return answer
            return (f"I didn't recognise “{asked[:120]}” as a command.\n\n" + self.hunter.status_text()
                    + "\n\n" + COMMAND_HELP)
        return COMMAND_HELP

    # ── helpers ─────────────────────────────────────────────────────────────
    def resolve(self, token: str) -> str:
        token = token.strip().strip("#[](),.").upper()
        if token.isdigit():
            index = int(token)
            if 1 <= index <= len(self._list_ids):
                return self._list_ids[index - 1]
            raise KeyError(f"there is no #{index} in the last list I sent — use the 5-letter job id")
        if _ID.match(token):
            return token
        raise KeyError(f"“{token}” is not a job id (ids look like 7K2QX)")

    def ids(self, text: str) -> List[str]:
        return [self.resolve(t) for t in re.split(r"[\s,]+", text.strip()) if t]

    def each(self, action: Callable[[str], str]) -> Callable:
        def run(match, channel):
            return "\n\n".join(action(jid) for jid in self.ids(match.group(2)))
        return run

    # ── handlers ────────────────────────────────────────────────────────────
    def list_jobs(self, match, channel) -> str:
        count = int(match.group(2) or 10)
        jobs = self.hunter.top_open_jobs(count)
        if not jobs:
            return "No open matches right now. Reply \"run\" to search every site again, or \"add role <title>\" to widen the search."
        self.hunter.remember_list([j["id"] for j in jobs])
        self._list_ids = [j["id"] for j in jobs]
        return "Your best open matches:\n\n" + "\n\n".join(job_line(j, i + 1) for i, j in enumerate(jobs))

    def run_now(self, match, channel) -> str:
        report = self.hunter.search(reason=f"requested via {channel}")
        if report.get("busy"):
            return "A search is already running — results will arrive shortly."
        return (f"Searched {len(report['per_source'])} sources: {report['fetched']} jobs checked, "
                f"{report['new']} new, {len(report['matches'])} new matches"
                + (" (sent to you as a separate digest)." if report["matches"] else ".")
                + (f"\nSource problems: {', '.join(report['errors'])}" if report["errors"] else ""))

    def search(self, match, channel) -> str:
        terms, location = match.group(1).strip(), (match.group(2) or "").strip()
        report = self.hunter.search(query=terms, location=location or None, reason=f"search via {channel}", notify=False)
        if report.get("busy"):
            return "A search is already running — try again in a minute."
        results = report["results"][:10]
        if not results:
            return f"No matches for “{terms}”{' in ' + location if location else ''} right now across {len(report['per_source'])} sources." + (
                f"\nSource problems: {', '.join(report['errors'])}" if report["errors"] else "")
        self.hunter.remember_list([j["id"] for j in results])
        self._list_ids = [j["id"] for j in results]
        return (f"Top results for “{terms}”{' in ' + location if location else ''}:\n\n"
                + "\n\n".join(job_line(j, i + 1) for i, j in enumerate(results)))

    def details(self, match, channel) -> str:
        return "\n\n".join(job_details(self.hunter.store.get_job(jid)) for jid in self.ids(match.group(2)))

    def set_status(self, match, channel) -> str:
        status = {"reject": "rejected", "close": "closed"}.get(match.group(1).lower(), match.group(1).lower())
        return "\n".join(self.hunter.set_status(jid, status) for jid in self.ids(match.group(2)))

    def reply(self, match, channel) -> str:
        return self.hunter.draft_reply(self.resolve(match.group(1)), match.group(2))

    def open(self, match, channel) -> str:
        return "\n".join(self.hunter.open_job(jid) for jid in self.ids(match.group(1)))

    def note(self, match, channel) -> str:
        jid = self.resolve(match.group(1))
        job = self.hunter.store.get_job(jid)
        notes = (job.get("notes", "") + "\n" + match.group(2)).strip()
        self.hunter.store.update_job(jid, notes=notes[-4000:])
        return f"Noted on [{jid}]."

    def edit_profile(self, match, channel) -> str:
        action, field, value = match.group(1).lower(), FIELDS[match.group(2).lower()], match.group(3).strip()
        return self.hunter.edit_profile_list(field, value, add=(action == "add"))

    def set_setting(self, match, channel) -> str:
        key = "level" if match.group(1).lower() == "level" else "min_score"
        value = match.group(2).lower()
        if key == "min_score":
            if not value.isdigit():
                raise ValueError("min score must be a number 0-100")
            value = int(value)
        elif value not in ("entry", "mid", "senior", "any"):
            raise ValueError("level must be entry, mid, senior or any")
        self.hunter.update_profile({key: value})
        return f"Updated {key.replace('_', ' ')} to {value}."

    def track(self, match, channel) -> str:
        return self.hunter.track_url(match.group(1), (match.group(2) or "").strip() if match.lastindex and match.lastindex > 1 else "")
