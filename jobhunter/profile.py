"""The candidate profile: what to search for and how the agent should behave.

Stored as JSON in the data directory (git-ignored). It holds no secrets.
"""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Dict

LEVELS = ("entry", "mid", "senior", "any")
BRAINS = ("none", "ollama", "claude-code", "codex-cli")
LIST_FIELDS = ("roles", "skills", "locations", "exclude", "owner_emails",
               "greenhouse_boards", "lever_boards", "rss_feeds", "company_sites")

DEFAULT_PROFILE: Dict[str, Any] = {
    # Who you are — used in cover letters. Keep it truthful; the agent never invents facts.
    "name": "",
    "phone": "",
    "headline": "",
    "summary": "",
    "cv_path": "",
    # What you want
    "roles": [],
    "skills": [],
    "locations": [],
    "exclude": [],
    "level": "entry",
    "remote_ok": True,
    "strict_location": False,
    "min_score": 50,
    # Where to look (per-source on/off; sources that need API keys also need the key in .env)
    "sources": {},
    "greenhouse_boards": [],
    "lever_boards": [],
    "rss_feeds": [],
    "company_sites": [],
    # How to reach you
    "owner_emails": [],
    "telegram_chat_id": "",
    "notify_email": True,
    "notify_telegram": True,
    "notify_desktop": True,
    "notify_when_empty": False,
    "daily_summary_hour": 9,
    "digest_max": 15,
    # Rhythm
    "search_every_minutes": 180,
    "inbox_every_minutes": 10,
    "follow_up_days": 7,
    "paused": False,
    "autostart": False,
    "open_browser_on_apply": True,
    "organize_inbox": True,  # Gmail: label job mail and move ads/newsletters out of the Inbox
    # Optional writing brain for cover letters and free-form questions
    "brain": "none",
    "brain_model": "",
    # Local Ollama vision model that reads business-card photos ("" = use tesseract only)
    "vision_model": "llama3.2-vision",
}

_INT_LIMITS = {
    "min_score": (0, 100),
    "daily_summary_hour": (-1, 23),  # -1 disables the daily summary
    "digest_max": (1, 50),
    "search_every_minutes": (30, 7 * 24 * 60),
    "inbox_every_minutes": (2, 24 * 60),
    "follow_up_days": (1, 60),
}
_BOOL_FIELDS = ("remote_ok", "strict_location", "notify_email", "notify_telegram", "notify_desktop",
                "notify_when_empty", "paused", "autostart", "open_browser_on_apply", "organize_inbox")
_TEXT_LIMITS = {"name": 120, "phone": 60, "headline": 200, "summary": 2000, "cv_path": 500,
                "telegram_chat_id": 40, "brain_model": 80, "vision_model": 80}


def _clean_list(value: Any) -> list:
    if isinstance(value, str):
        value = value.replace("\n", ",").split(",")
    if not isinstance(value, (list, tuple)):
        return []
    out = []
    for item in value:
        text = " ".join(str(item).split())[:200]
        if text and text.lower() not in {x.lower() for x in out}:
            out.append(text)
    return out[:60]


def validate(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Return a normalised copy; unknown keys are dropped, bad values fall back to defaults."""
    clean = copy.deepcopy(DEFAULT_PROFILE)
    for key, default in DEFAULT_PROFILE.items():
        if key not in profile:
            continue
        value = profile[key]
        if key in LIST_FIELDS:
            clean[key] = _clean_list(value)
        elif key in _INT_LIMITS:
            low, high = _INT_LIMITS[key]
            try:
                clean[key] = max(low, min(high, int(value)))
            except (TypeError, ValueError):
                pass
        elif key in _BOOL_FIELDS:
            clean[key] = value if isinstance(value, bool) else str(value).lower() in {"1", "true", "yes", "on"}
        elif key == "level":
            clean[key] = value if value in LEVELS else default
        elif key == "brain":
            clean[key] = value if value in BRAINS else default
        elif key == "sources":
            if isinstance(value, dict):
                clean[key] = {str(k): bool(v) for k, v in value.items()}
        elif key in _TEXT_LIMITS:
            clean[key] = str(value or "").strip()[: _TEXT_LIMITS[key]]
    clean["owner_emails"] = [e.lower() for e in clean["owner_emails"] if "@" in e]
    return clean


def load_profile(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return validate(data if isinstance(data, dict) else {})


def save_profile(path: Path, profile: Dict[str, Any]) -> Dict[str, Any]:
    clean = validate(profile)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    return clean


def update_profile(path: Path, changes: Dict[str, Any]) -> Dict[str, Any]:
    current = load_profile(path)
    for key, value in (changes or {}).items():
        if key == "sources" and isinstance(value, dict):
            current["sources"] = {**current.get("sources", {}), **value}
        elif key in DEFAULT_PROFILE:
            current[key] = value
    return save_profile(path, current)


def is_ready(profile: Dict[str, Any]) -> bool:
    return bool(profile.get("roles"))
