"""Small text helpers shared by sources, scoring and the mailbox (stdlib only)."""
from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from functools import lru_cache
from html.parser import HTMLParser
from typing import List, Optional, Tuple
from urllib.parse import urlparse

_BLOCK_TAGS = {"p", "div", "br", "li", "ul", "ol", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"}
_SKIP_TAGS = {"script", "style", "head", "title"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self.links: List[Tuple[str, str]] = []
        self._skip = 0
        self._href: Optional[str] = None
        self._link_text: List[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "li":
            self.parts.append("• ")
        if tag == "a":
            self._href = dict(attrs).get("href") or ""
            self._link_text = []

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1
        if tag in _BLOCK_TAGS:
            self.parts.append("\n")
        if tag == "a" and self._href is not None:
            text = " ".join("".join(self._link_text).split())
            if self._href:
                self.links.append((self._href, text))
            self._href = None

    def handle_data(self, data):
        if self._skip:
            return
        self.parts.append(data)
        if self._href is not None:
            self._link_text.append(data)


def html_to_text(value: str) -> str:
    """Readable plain text from an HTML fragment."""
    return html_to_text_and_links(value)[0]


def html_to_text_and_links(value: str) -> Tuple[str, List[Tuple[str, str]]]:
    if not value:
        return "", []
    parser = _TextExtractor()
    try:
        parser.feed(value)
        parser.close()
    except Exception:  # malformed markup: fall back to a crude strip
        return clean_space(re.sub(r"<[^>]+>", " ", html.unescape(value))), []
    text = "".join(parser.parts)
    lines = [" ".join(line.split()) for line in text.splitlines()]
    out, blank = [], False
    for line in lines:
        if not line:
            if not blank and out:
                out.append("")
            blank = True
            continue
        out.append(line)
        blank = False
    return "\n".join(out).strip(), parser.links


def clean_space(value: str) -> str:
    return " ".join((value or "").split())


def strip_tags(value: str) -> str:
    """Inline HTML → single-line text (for titles and company names)."""
    return clean_space(html.unescape(re.sub(r"<[^>]+>", " ", value or "")))


def norm(value: str) -> str:
    """Lower-case text for matching; keeps + # . so c++, c# and .net survive."""
    value = (value or "").lower()
    value = re.sub(r"[^\w+#./\-؀-ۿ ]+", " ", value)
    return " ".join(value.split())


@lru_cache(maxsize=2048)
def _term_pattern(term: str) -> "re.Pattern[str]":
    return re.compile(r"(?<![a-z0-9؀-ۿ])" + re.escape(term) + r"(?![a-z0-9؀-ۿ])")


def contains(text: str, term: str) -> bool:
    """Whole-word/phrase match of an already-normalised term in normalised text."""
    term = term.strip()
    return bool(term) and bool(_term_pattern(term).search(text))


def snippet(value: str, limit: int = 280) -> str:
    value = clean_space(value)
    return value if len(value) <= limit else value[: limit - 1].rsplit(" ", 1)[0] + "…"


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_IGNORED_EMAIL = re.compile(r"(no-?reply|donotreply|do-not-reply|example\.|sentry|wixpress|\.png|\.jpg|privacy@|abuse@)", re.I)


def extract_emails(value: str) -> List[str]:
    found = []
    for match in _EMAIL_RE.findall(value or ""):
        email = match.strip(".").lower()
        if _IGNORED_EMAIL.search(email) or email in found:
            continue
        found.append(email)
    return found


def email_domain(address: str) -> str:
    return address.rsplit("@", 1)[-1].lower().strip(">") if "@" in (address or "") else ""


def url_domain(url: str) -> str:
    try:
        host = urlparse(url or "").hostname or ""
    except ValueError:
        return ""
    return host.lower()[4:] if host.lower().startswith("www.") else host.lower()


def base_domain(host: str) -> str:
    """acme.co.uk → acme.co.uk, jobs.acme.com → acme.com (good enough for matching)."""
    parts = [p for p in (host or "").lower().split(".") if p]
    if len(parts) <= 2:
        return ".".join(parts)
    if len(parts[-1]) == 2 and parts[-2] in {"co", "com", "net", "org", "gov", "edu", "ac"}:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def parse_date(value) -> Optional[str]:
    """Best-effort conversion of feed/API dates to an ISO-8601 UTC string."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        seconds = value / 1000 if value > 10_000_000_000 else value
        try:
            return datetime.fromtimestamp(seconds, timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if text.isdigit():
        return parse_date(int(text))
    from email.utils import parsedate_to_datetime
    for attempt in (
        lambda t: datetime.fromisoformat(t.replace("Z", "+00:00")),
        lambda t: datetime.strptime(t, "%Y-%m-%d %H:%M:%S"),
        lambda t: datetime.strptime(t[:10], "%Y-%m-%d"),
        parsedate_to_datetime,
    ):
        try:
            parsed = attempt(text)
        except (TypeError, ValueError, IndexError):
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat()
    return None


def age_days(iso: Optional[str], now: Optional[datetime] = None) -> Optional[float]:
    if not iso:
        return None
    try:
        then = datetime.fromisoformat(iso)
    except ValueError:
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - then).total_seconds() / 86400


def human_age(iso: Optional[str]) -> str:
    days = age_days(iso)
    if days is None:
        return ""
    if days < 1:
        return "today"
    if days < 2:
        return "yesterday"
    return f"{int(days)} days ago"
