"""Laptop + Telegram side channels: desktop notifications, opening pages, Telegram messages."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import urllib.request
import webbrowser
from pathlib import Path
from typing import Optional

CHROME_PATHS = (
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
)


def telegram_send(token: str, chat_id: str, text: str) -> bool:
    """Plain-text Telegram message (split into 4000-char chunks). Returns True on success."""
    if not token or not chat_id:
        return False
    ok = True
    for start in range(0, len(text), 4000):
        body = json.dumps({"chat_id": chat_id, "text": text[start:start + 4000],
                           "disable_web_page_preview": True}).encode("utf-8")
        request = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=body,
                                         headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                ok = ok and bool(json.loads(response.read()).get("ok"))
        except Exception:
            ok = False
    return ok


def desktop_notify(title: str, message: str) -> bool:
    """Best-effort native notification on the laptop running the agent."""
    title, message = title[:120], message[:240]
    system = platform.system()
    try:
        if system == "Darwin" and shutil.which("osascript"):
            script = f"display notification {json.dumps(message)} with title {json.dumps(title)}"
            subprocess.run(["osascript", "-e", script], timeout=10, capture_output=True)
            return True
        has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
        if system == "Linux" and has_display and shutil.which("notify-send"):
            subprocess.run(["notify-send", title, message], timeout=10, capture_output=True)
            return True
    except (OSError, subprocess.SubprocessError):
        pass
    return False


def _chrome() -> Optional[str]:
    for path in CHROME_PATHS:
        if Path(path).exists():
            return path
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def open_url(url: str, profile_dir: Optional[Path] = None) -> bool:
    """Open a job page on the laptop — in the job agent's own Chrome profile when Chrome exists."""
    if not url.startswith(("https://", "http://")):
        return False
    chrome = _chrome()
    try:
        if chrome and profile_dir:
            Path(profile_dir).mkdir(parents=True, exist_ok=True)
            subprocess.Popen([chrome, f"--user-data-dir={profile_dir}", "--no-first-run", url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            return True
        return bool(webbrowser.open(url, new=2))
    except (OSError, webbrowser.Error):
        return False
