"""Paths and secrets for the job hunter.

Secrets (mail password, API keys, bot token) only ever live in the process
environment or the git-ignored ``.env`` file — never in SQLite or the profile.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Mapping, Optional

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"

# domain → (imap host, smtp host, smtp port). 465 = implicit TLS, 587 = STARTTLS.
MAIL_PRESETS = {
    "gmail.com": ("imap.gmail.com", "smtp.gmail.com", 465),
    "googlemail.com": ("imap.gmail.com", "smtp.gmail.com", 465),
    "outlook.com": ("outlook.office365.com", "smtp.office365.com", 587),
    "hotmail.com": ("outlook.office365.com", "smtp.office365.com", 587),
    "live.com": ("outlook.office365.com", "smtp.office365.com", 587),
    "msn.com": ("outlook.office365.com", "smtp.office365.com", 587),
    "yahoo.com": ("imap.mail.yahoo.com", "smtp.mail.yahoo.com", 465),
    "icloud.com": ("imap.mail.me.com", "smtp.mail.me.com", 587),
    "me.com": ("imap.mail.me.com", "smtp.mail.me.com", 587),
}


def load_env_file(path: Path = ENV_FILE) -> None:
    """Load KEY=value lines without overriding variables that are already set."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"":
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def save_env_values(values: Mapping[str, str], path: Path = ENV_FILE) -> None:
    """Replace or append KEY=value lines in the git-ignored .env file."""
    for key, value in values.items():
        if "\n" in value or "\r" in value:
            raise ValueError(f"{key} must be a single line")
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    remaining = dict(values)
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip()
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    out.extend(f"{key}={value}" for key, value in remaining.items())
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    os.environ.update(values)


@dataclass
class MailSettings:
    address: str = ""
    password: str = ""
    imap_host: str = ""
    imap_port: int = 993
    smtp_host: str = ""
    smtp_port: int = 465
    trust_unverified: bool = False

    @property
    def configured(self) -> bool:
        return bool(self.address and self.password and self.imap_host and self.smtp_host)

    def public(self) -> Dict[str, object]:
        return {"address": self.address, "imap_host": self.imap_host, "smtp_host": self.smtp_host,
                "configured": self.configured, "password_set": bool(self.password)}


def mail_settings(env: Optional[Mapping[str, str]] = None) -> MailSettings:
    env = os.environ if env is None else env
    address = env.get("JOBHUNTER_EMAIL", "").strip()
    domain = address.rsplit("@", 1)[-1].lower() if "@" in address else ""
    imap_default, smtp_default, port_default = MAIL_PRESETS.get(domain, ("", "", 465))

    def _int(name: str, default: int) -> int:
        try:
            return int(env.get(name, "") or default)
        except ValueError:
            return default

    return MailSettings(
        address=address,
        password=env.get("JOBHUNTER_EMAIL_PASSWORD", "").replace(" ", ""),
        imap_host=env.get("JOBHUNTER_IMAP_HOST", "").strip() or imap_default,
        imap_port=_int("JOBHUNTER_IMAP_PORT", 993),
        smtp_host=env.get("JOBHUNTER_SMTP_HOST", "").strip() or smtp_default,
        smtp_port=_int("JOBHUNTER_SMTP_PORT", port_default),
        trust_unverified=env.get("JOBHUNTER_TRUST_UNVERIFIED", "") == "1",
    )


def data_dir(env: Optional[Mapping[str, str]] = None) -> Path:
    env = os.environ if env is None else env
    if env.get("JOBHUNTER_DATA_DIR"):
        return Path(env["JOBHUNTER_DATA_DIR"])
    base = Path(env.get("PERSONAL_OS_DATA_DIR", str(ROOT / "data")))
    return base / "jobhunter"
