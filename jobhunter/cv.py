"""Master CV → a tailored, ATS-friendly CV for every job.

The master CV is a plain-text file (data/jobhunter/master_cv.md) in a simple format:

    # Mohammed Bakr
    Computer Engineer · Riyadh · +966 5x xxx xxxx · you@gmail.com · linkedin.com/in/you
    ## Summary
    Computer Engineering graduate ...
    ## Experience
    ### IT Intern — Company (Jun 2025 – Aug 2025)
    - Did something measurable
    ## Projects
    ### Smart Black Box — Graduation project (Team Leader)
    - Built ...
    ## Skills
    Python, SQL, Networking, Linux
    ## Certifications
    - Fundamentals of Artificial Intelligence — SDAIA (2025)

Tailoring only REORDERS and TRIMS what is already in the master CV (most relevant
bullets, projects and skills first) and adds a "Target role" line. It never adds
facts, so every tailored CV stays truthful.
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

from .textutil import contains, norm

STOP = {"and", "the", "for", "with", "our", "you", "your", "are", "will", "who", "this", "that", "from", "have",
        "has", "job", "role", "team", "work", "able", "years", "year", "experience", "skills", "strong", "good",
        "knowledge", "including", "ability", "using", "within", "about", "their", "they", "all", "any", "not",
        "must", "should", "can", "also", "etc", "such", "other", "new", "more", "well", "per", "into", "out"}
REORDERABLE = ("project", "مشاريع", "المشاريع")
SKILL_SECTIONS = ("skill", "مهارات", "المهارات", "technical")
MAX_BULLETS = 5
MAX_PROJECTS = 4


@dataclass
class Entry:
    heading: str = ""
    lines: List[str] = field(default_factory=list)   # free text lines
    bullets: List[str] = field(default_factory=list)


@dataclass
class Section:
    title: str
    entries: List[Entry] = field(default_factory=list)


@dataclass
class CV:
    name: str = ""
    contact: List[str] = field(default_factory=list)
    sections: List[Section] = field(default_factory=list)


def parse(text: str) -> CV:
    cv = CV()
    section: Optional[Section] = None
    entry: Optional[Entry] = None
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        stripped = line.strip()
        if stripped.startswith("# ") and not cv.name:
            cv.name = stripped[2:].strip()
        elif stripped.startswith("## "):
            section = Section(stripped[3:].strip())
            cv.sections.append(section)
            entry = None
        elif section is None:
            cv.contact.append(stripped)
        elif stripped.startswith("### "):
            entry = Entry(stripped[4:].strip())
            section.entries.append(entry)
        else:
            if entry is None:
                entry = Entry()
                section.entries.append(entry)
            if re.match(r"^[-*•]\s+", stripped):
                entry.bullets.append(re.sub(r"^[-*•]\s+", "", stripped))
            else:
                entry.lines.append(stripped)
    return cv


def to_text(cv: CV) -> str:
    out = [f"# {cv.name}"] if cv.name else []
    out += cv.contact
    for section in cv.sections:
        out.append(f"\n## {section.title}")
        for entry in section.entries:
            if entry.heading:
                out.append(f"### {entry.heading}")
            out += entry.lines
            out += [f"- {b}" for b in entry.bullets]
    return "\n".join(out).strip() + "\n"


# ── tailoring ─────────────────────────────────────────────────────────────────

def keywords(job: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, int]:
    """Weighted keywords: job title words ×3, profile skills the job mentions ×3, description words ×1."""
    weights: Dict[str, int] = {}
    title = norm(job.get("title", ""))
    description = norm(job.get("description", ""))
    for word in title.split():
        if len(word) > 2 and word not in STOP:
            weights[word] = weights.get(word, 0) + 3
    for skill in profile.get("skills", []):
        key = norm(skill)
        if key and (contains(description, key) or contains(title, key)):
            weights[key] = weights.get(key, 0) + 3
    counts: Dict[str, int] = {}
    for word in description.split():
        if len(word) > 3 and word not in STOP and not word.isdigit():
            counts[word] = counts.get(word, 0) + 1
    for word, count in sorted(counts.items(), key=lambda kv: -kv[1])[:40]:
        weights[word] = weights.get(word, 0) + min(count, 3)
    return weights


def relevance(text: str, weights: Dict[str, int]) -> int:
    key = norm(text)
    return sum(weight for word, weight in weights.items() if contains(key, word))


def _is(section: Section, names) -> bool:
    title = section.title.lower()
    return any(n in title for n in names)


def tailor(master: CV, job: Dict[str, Any], profile: Dict[str, Any]) -> CV:
    weights = keywords(job, profile)
    out = CV(master.name, list(master.contact), [])
    for section in master.sections:
        entries = []
        for entry in section.entries:
            bullets = sorted(entry.bullets, key=lambda b: -relevance(b, weights))  # stable: ties keep master order
            lines = list(entry.lines)
            if _is(section, SKILL_SECTIONS):
                lines = [_order_list(line, weights) for line in lines]
            entries.append(Entry(entry.heading, lines, bullets[:MAX_BULLETS]))
        if _is(section, REORDERABLE):
            entries.sort(key=lambda e: -relevance(" ".join([e.heading, *e.lines, *e.bullets]), weights))
            entries = entries[:MAX_PROJECTS]
        out.sections.append(Section(section.title, entries))
    if job.get("title"):
        target = f"Target role: {job['title']}" + (f" at {job['company']}" if job.get("company") else "")
        summary = next((s for s in out.sections if "summary" in s.title.lower() or "profile" in s.title.lower()
                        or "نبذة" in s.title), None)
        if summary and summary.entries:
            summary.entries[0].lines.insert(0, target)
        else:
            out.contact.append(target)
    return out


def _order_list(line: str, weights: Dict[str, int]) -> str:
    """Put the skills this job asks for first in a comma/· separated line (label prefix kept)."""
    label, sep, rest = line.partition(":") if ":" in line[:40] else ("", "", line)
    parts = [p.strip() for p in re.split(r"\s*[,·|•]\s*", rest) if p.strip()]
    if len(parts) < 2:
        return line
    ordered = sorted(parts, key=lambda p: -relevance(p, weights))
    return f"{label}{sep} " + ", ".join(ordered) if sep else ", ".join(ordered)


# ── output ────────────────────────────────────────────────────────────────────

def _run(text: str, bold: bool = False, size: int = 0) -> str:
    props = ("<w:b/>" if bold else "") + (f'<w:sz w:val="{size}"/><w:szCs w:val="{size}"/>' if size else "")
    rtl = "<w:rtl/>" if re.search(r"[؀-ۿ]", text) else ""
    return f'<w:r><w:rPr>{props}{rtl}</w:rPr><w:t xml:space="preserve">{escape(text)}</w:t></w:r>'


def _para(runs: str, space_after: int = 60, space_before: int = 0, align: str = "", border: bool = False) -> str:
    ppr = f'<w:spacing w:before="{space_before}" w:after="{space_after}"/>'
    if align:
        ppr += f'<w:jc w:val="{align}"/>'
    if border:
        ppr += '<w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="444444"/></w:pBdr>'
    return f"<w:p><w:pPr>{ppr}</w:pPr>{runs}</w:p>"


def to_docx(cv: CV, path: Path) -> Path:
    """Single-column, no tables/images/text boxes: the format applicant-tracking systems parse best."""
    body = [_para(_run(cv.name, bold=True, size=32), 40, align="center")]
    if cv.contact:
        body.append(_para(_run(" · ".join(cv.contact), size=19), 120, align="center"))
    for section in cv.sections:
        body.append(_para(_run(section.title.upper(), bold=True, size=22), 60, 160, border=True))
        for entry in section.entries:
            if entry.heading:
                body.append(_para(_run(entry.heading, bold=True, size=21), 20, 60))
            for line in entry.lines:
                body.append(_para(_run(line, size=20), 40))
            for bullet in entry.bullets:
                body.append(_para(_run("• " + bullet, size=20), 20))
    document = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
                + "".join(body) +
                '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
                '<w:pgMar w:top="850" w:right="850" w:bottom="850" w:left="850" w:header="0" w:footer="0" w:gutter="0"/>'
                '</w:sectPr></w:body></w:document>')
    styles = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
              '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:docDefaults>'
              '<w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Arial"/>'
              '<w:sz w:val="20"/><w:lang w:val="en-US" w:bidi="ar-SA"/></w:rPr></w:rPrDefault></w:docDefaults></w:styles>')
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    files = {
        "[Content_Types].xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
            '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '</Types>',
        "_rels/.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>'
            '</Relationships>',
        "word/_rels/document.xml.rels": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
            '</Relationships>',
        "word/document.xml": document,
        "word/styles.xml": styles,
        "docProps/core.xml": '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{escape(cv.name)} CV</dc:title><dc:creator>{escape(cv.name)}</dc:creator>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{now}</dcterms:created></cp:coreProperties>',
    }
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return path


def docx_to_master(path: Path) -> str:
    """Import an existing .docx CV (e.g. ATS-1.docx) into the master-CV text format to review and edit."""
    with zipfile.ZipFile(path) as archive:
        xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    lines, first = [], True
    for para in re.findall(r"<w:p[ >].*?</w:p>", xml, re.S):
        text = "".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", para, re.S))
        text = re.sub(r"<[^>]+>", "", text)
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"').strip()
        if not text:
            continue
        style = re.search(r'<w:pStyle w:val="([^"]+)"', para)
        style = style.group(1).lower() if style else ""
        is_list = "<w:numPr>" in para or "list" in style or text[:1] in "•-▪●"
        letters = re.sub(r"[^A-Za-z]", "", text)
        if first:
            lines.append(f"# {text}")
            first = False
        elif "heading1" in style or "heading 1" in style or (letters and letters.isupper() and len(text) < 40):
            lines.append(f"## {text.title() if text.isupper() else text}")
        elif "heading" in style:
            lines.append(f"### {text}")
        elif is_list:
            lines.append("- " + text.lstrip("•-▪● ").strip())
        else:
            lines.append(text)
    return "\n".join(lines) + "\n"


def safe_filename(*parts: str) -> str:
    joined = "_".join(p for p in parts if p)
    return re.sub(r"[^A-Za-z0-9؀-ۿ]+", "_", joined).strip("_")[:80] or "CV"
