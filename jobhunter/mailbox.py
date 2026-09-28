"""Read and send email over IMAP/SMTP (works with Gmail/Outlook/Yahoo/iCloud app passwords).

Reading never marks mail as read: the inbox is opened read-only and bodies are
fetched with BODY.PEEK.
"""
from __future__ import annotations

import imaplib
import mimetypes
import re
import smtplib
import ssl
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import formatdate, getaddresses, make_msgid, parseaddr
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .config import MailSettings
from .textutil import html_to_text_and_links

AGENT_HEADER = "X-JobHunter"


class MailError(RuntimeError):
    pass


@dataclass
class IncomingMail:
    uid: int
    message_id: str
    subject: str
    from_name: str
    from_addr: str
    to_addrs: List[str]
    date: str
    text: str
    html: str = ""
    links: List[Tuple[str, str]] = field(default_factory=list)
    in_reply_to: str = ""
    references: List[str] = field(default_factory=list)
    auth_results: str = ""
    agent_header: str = ""
    auto_submitted: str = ""
    list_unsubscribe: bool = False

    @property
    def thread_ids(self) -> List[str]:
        return [x for x in [self.in_reply_to, *self.references] if x]


def _decode_part(part) -> str:
    try:
        return part.get_content()
    except (LookupError, UnicodeDecodeError, KeyError):
        payload = part.get_payload(decode=True) or b""
        return payload.decode("utf-8", errors="replace")


def parse_message(raw: bytes, uid: int = 0) -> IncomingMail:
    msg = message_from_bytes(raw, policy=policy.default)
    text_parts: List[str] = []
    html_parts: List[str] = []
    for part in msg.walk():
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        ctype = part.get_content_type()
        if ctype == "text/plain":
            text_parts.append(_decode_part(part))
        elif ctype == "text/html":
            html_parts.append(_decode_part(part))
    html_body = "\n".join(html_parts)
    html_text, links = html_to_text_and_links(html_body) if html_body else ("", [])
    text = "\n".join(text_parts).strip() or html_text
    if not links and text:
        links = [(u, "") for u in re.findall(r"https?://[^\s<>\")\]]+", text)]
    from_name, from_addr = parseaddr(str(msg.get("From", "")))
    auth = msg.get_all("Authentication-Results") or []
    refs = str(msg.get("References", "") or "")
    return IncomingMail(
        uid=uid,
        message_id=str(msg.get("Message-ID", "") or "").strip(),
        subject=" ".join(str(msg.get("Subject", "") or "").split()),
        from_name=from_name,
        from_addr=from_addr.lower(),
        to_addrs=[a.lower() for _, a in getaddresses([str(v) for v in (msg.get_all("To") or []) + (msg.get_all("Cc") or [])]) if a],
        date=str(msg.get("Date", "") or ""),
        text=text,
        html=html_body,
        links=links,
        in_reply_to=str(msg.get("In-Reply-To", "") or "").strip(),
        references=re.findall(r"<[^>]+>", refs),
        auth_results=str(auth[0]) if auth else "",
        agent_header=str(msg.get(AGENT_HEADER, "") or ""),
        auto_submitted=str(msg.get("Auto-Submitted", "") or "").lower(),
        list_unsubscribe=bool(msg.get("List-Unsubscribe")),
    )


class Mailbox:
    def __init__(self, settings: MailSettings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return self.settings.configured

    @property
    def address(self) -> str:
        return self.settings.address

    # ── IMAP ────────────────────────────────────────────────────────────────
    def _imap(self) -> imaplib.IMAP4_SSL:
        if not self.configured:
            raise MailError("Email is not connected yet")
        try:
            conn = imaplib.IMAP4_SSL(self.settings.imap_host, self.settings.imap_port,
                                     ssl_context=ssl.create_default_context(), timeout=30)
            conn.login(self.settings.address, self.settings.password)
            return conn
        except imaplib.IMAP4.error as exc:
            raise MailError(f"IMAP login failed: {exc}. For Gmail use a 16-letter App Password, not your normal password.") from None
        except OSError as exc:
            raise MailError(f"Cannot reach {self.settings.imap_host}: {exc}") from None

    def fetch_new(self, state: Optional[Dict] = None, first_run_days: int = 2, limit: int = 60
                  ) -> Tuple[List[IncomingMail], Dict]:
        """Return messages newer than state['last_uid'] and the new state to persist."""
        state = dict(state or {})
        conn = self._imap()
        try:
            typ, _ = conn.select("INBOX", readonly=True)
            if typ != "OK":
                raise MailError("Cannot open INBOX")
            validity = (conn.response("UIDVALIDITY")[1] or [b""])[0]
            validity = validity.decode() if isinstance(validity, bytes) else str(validity or "")
            last_uid = int(state.get("last_uid", 0)) if state.get("uidvalidity") == validity else 0
            if last_uid:
                typ, data = conn.uid("SEARCH", None, f"UID {last_uid + 1}:*")
            else:
                since = (datetime.now(timezone.utc) - timedelta(days=first_run_days)).strftime("%d-%b-%Y")
                typ, data = conn.uid("SEARCH", None, "SINCE", since)
            uids = sorted(int(x) for x in (data[0] or b"").split() if int(x) > last_uid) if typ == "OK" else []
            messages = []
            for uid in uids[:limit]:
                typ, parts = conn.uid("FETCH", str(uid), "(BODY.PEEK[])")
                raw = next((p[1] for p in parts or [] if isinstance(p, tuple) and len(p) > 1), None)
                if typ == "OK" and raw:
                    messages.append(parse_message(raw, uid))
            processed = uids[:limit]
            new_last = processed[-1] if processed else last_uid
            if not last_uid and not processed:
                # Remember where "now" is so the next run only reads newer mail.
                typ, data = conn.uid("SEARCH", None, "ALL")
                all_uids = [int(x) for x in (data[0] or b"").split()] if typ == "OK" else []
                new_last = max(all_uids) if all_uids else 0
            return messages, {"uidvalidity": validity, "last_uid": new_last}
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    # ── SMTP ────────────────────────────────────────────────────────────────
    def send(self, to: Sequence[str] | str, subject: str, text: str, html: Optional[str] = None,
             attachments: Iterable[Path] = (), in_reply_to: Optional[str] = None,
             references: Optional[Sequence[str]] = None, bcc: Sequence[str] = (),
             agent_kind: Optional[str] = None) -> str:
        if not self.configured:
            raise MailError("Email is not connected yet")
        recipients = [to] if isinstance(to, str) else list(to)
        msg = EmailMessage()
        msg["From"] = self.settings.address
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg["Date"] = formatdate(localtime=True)
        domain = self.settings.address.rsplit("@", 1)[-1] if "@" in self.settings.address else None
        message_id = make_msgid(idstring="jobhunter", domain=domain)
        msg["Message-ID"] = message_id
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = " ".join(list(references or []) + [in_reply_to])
        if agent_kind:
            msg[AGENT_HEADER] = agent_kind
        msg.set_content(text)
        if html:
            msg.add_alternative(html, subtype="html")
        for path in attachments:
            path = Path(path)
            ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
            maintype, subtype = ctype.split("/", 1)
            msg.add_attachment(path.read_bytes(), maintype=maintype, subtype=subtype, filename=path.name)
        all_rcpt = recipients + [b for b in bcc if b and b not in recipients]
        try:
            context = ssl.create_default_context()
            if self.settings.smtp_port == 465:
                with smtplib.SMTP_SSL(self.settings.smtp_host, 465, context=context, timeout=30) as smtp:
                    smtp.login(self.settings.address, self.settings.password)
                    smtp.send_message(msg, to_addrs=all_rcpt)
            else:
                with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=30) as smtp:
                    smtp.starttls(context=context)
                    smtp.login(self.settings.address, self.settings.password)
                    smtp.send_message(msg, to_addrs=all_rcpt)
        except smtplib.SMTPAuthenticationError:
            raise MailError("SMTP login failed. For Gmail use an App Password.") from None
        except (smtplib.SMTPException, OSError) as exc:
            raise MailError(f"Sending failed: {exc}") from None
        return message_id

    def test(self) -> Dict[str, object]:
        """Log in to IMAP and SMTP without sending anything."""
        result: Dict[str, object] = {"imap": False, "smtp": False}
        conn = self._imap()
        try:
            result["imap"] = conn.select("INBOX", readonly=True)[0] == "OK"
        finally:
            try:
                conn.logout()
            except Exception:
                pass
        try:
            context = ssl.create_default_context()
            if self.settings.smtp_port == 465:
                with smtplib.SMTP_SSL(self.settings.smtp_host, 465, context=context, timeout=30) as smtp:
                    smtp.login(self.settings.address, self.settings.password)
            else:
                with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=30) as smtp:
                    smtp.starttls(context=context)
                    smtp.login(self.settings.address, self.settings.password)
            result["smtp"] = True
        except (smtplib.SMTPException, OSError) as exc:
            raise MailError(f"SMTP check failed: {exc}") from None
        return result
