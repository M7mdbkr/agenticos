"""Business-card photos → contacts.

Reading the photo happens on your laptop:
  1. a local Ollama vision model (default llama3.2-vision; `ollama pull llama3.2-vision`), else
  2. the `tesseract` OCR command (brew install tesseract tesseract-lang), else
  3. the photo is kept and you type the details ("card C1234 Ahmed, HR, Acme, ahmed@acme.com").
iPhone HEIC photos are converted with macOS `sips` first.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

from .textutil import email_domain, extract_emails

OLLAMA = "http://localhost:11434"
FIELDS = ("name", "title", "company", "email", "phone", "website")
_PHONE = re.compile(r"(?:\+|00)?\d[\d\s\-()]{7,}\d")
_WEB = re.compile(r"\b((?:https?://)?(?:www\.)?[a-z0-9\-]+(?:\.[a-z0-9\-]+)*\.(?:com|sa|net|org|io|co|ai|gov|edu|me)(?:\.[a-z]{2})?(?:/\S*)?)", re.I)
_TITLE_WORDS = ("manager", "director", "engineer", "specialist", "officer", "recruit", "talent", "hr", "human resources",
                "head", "lead", "consultant", "coordinator", "ceo", "cto", "founder", "partner", "analyst", "executive",
                "مدير", "مهندس", "أخصائي", "اخصائي", "رئيس", "مسؤول", "الموارد البشرية", "مستشار")
_COMPANY_WORDS = ("company", "co.", "ltd", "llc", "inc", "group", "holding", "solutions", "technologies", "tech",
                  "systems", "bank", "شركة", "مجموعة", "للتقنية", "القابضة", "بنك")
PROMPT = ("Read this business card. Reply with JSON only: {\"name\":\"\",\"title\":\"\",\"company\":\"\",\"email\":\"\","
          "\"phone\":\"\",\"website\":\"\"}. Copy text exactly as printed (Arabic or English). Use \"\" when missing.")


def normalise_image(path: Path) -> Path:
    """Convert HEIC/HEIF (iPhone) to JPEG when macOS `sips` is available."""
    if path.suffix.lower() in (".heic", ".heif") and shutil.which("sips"):
        target = path.with_suffix(".jpg")
        subprocess.run(["sips", "-s", "format", "jpeg", str(path), "--out", str(target)], capture_output=True, timeout=60)
        if target.exists():
            return target
    return path


def _ollama_vision(path: Path, model: str) -> Optional[Dict[str, str]]:
    body = json.dumps({"model": model, "prompt": PROMPT, "images": [base64.b64encode(path.read_bytes()).decode()],
                       "format": "json", "stream": False, "options": {"temperature": 0}}).encode()
    request = urllib.request.Request(f"{OLLAMA}/api/generate", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            answer = json.loads(response.read()).get("response", "")
        data = json.loads(answer)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return {k: str(data.get(k) or "").strip() for k in FIELDS}


def _tesseract(path: Path) -> str:
    if not shutil.which("tesseract"):
        return ""
    for langs in ("eng+ara", "eng"):
        try:
            result = subprocess.run(["tesseract", str(path), "stdout", "-l", langs], capture_output=True, text=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            return ""
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    return ""


def parse_text(text: str) -> Dict[str, str]:
    """Pull card fields out of OCR text or something you typed ("Ahmed Ali, HR Manager, Acme, ahmed@acme.com")."""
    parts = [p.strip() for p in re.split(r"[\n,|;]+", text or "") if p.strip()]
    emails = extract_emails(text)
    result = {k: "" for k in FIELDS}
    result["email"] = emails[0] if emails else ""
    phone = _PHONE.search(text or "")
    result["phone"] = " ".join(phone.group(0).split()) if phone else ""
    for match in _WEB.finditer(text or ""):
        candidate = match.group(1)
        if "@" not in text[max(0, match.start() - 1):match.start()] and not any(candidate in e for e in emails):
            result["website"] = candidate if candidate.startswith("http") else "https://" + candidate
            break
    rest = [p for p in parts if "@" not in p and not _PHONE.fullmatch(p) and not _WEB.fullmatch(p)
            and not re.fullmatch(r"[\d\s+\-()]+", p)]
    for part in rest:
        low = part.lower()
        if not result["company"] and any(w in low for w in _COMPANY_WORDS):
            result["company"] = part
        elif not result["title"] and any(w in low for w in _TITLE_WORDS):
            result["title"] = part
    for part in rest:
        if part not in (result["company"], result["title"]) and len(part.split()) <= 5 and not any(c.isdigit() for c in part):
            result["name"] = part
            break
    if not result["company"]:
        domain = email_domain(result["email"]) or re.sub(r"^https?://(www\.)?", "", result["website"]).split("/")[0]
        if domain and domain.split(".")[0] not in ("gmail", "hotmail", "outlook", "yahoo", "icloud"):
            result["company"] = domain.split(".")[0].replace("-", " ").title()
    return result


def read_card(path: Path, vision_model: str = "llama3.2-vision") -> Dict[str, Any]:
    """Best-effort extraction; returns fields plus how they were read ('ollama', 'tesseract' or 'none')."""
    path = normalise_image(Path(path))
    data = _ollama_vision(path, vision_model) if vision_model else None
    if data and (data["email"] or data["name"] or data["company"]):
        return {**data, "method": "ollama"}
    text = _tesseract(path)
    if text:
        return {**parse_text(text), "method": "tesseract", "raw": text[:2000]}
    return {**{k: "" for k in FIELDS}, "method": "none"}


def save_image(folder: Path, filename: str, data: bytes) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", Path(filename).name).strip("._") or "card.jpg"
    handle = tempfile.NamedTemporaryFile(dir=folder, prefix="card-", suffix="-" + safe, delete=False)
    with handle:
        handle.write(data)
    return Path(handle.name)
