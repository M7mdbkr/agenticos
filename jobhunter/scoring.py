"""Deterministic job ↔ profile matching. Explains every point it gives or takes."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from .textutil import age_days, contains, norm

SENIOR_TERMS = ("senior", "sr", "lead", "principal", "staff", "head of", "director", "manager",
                "architect", "vp", "vice president", "chief", "expert")
JUNIOR_TERMS = ("junior", "jr", "graduate", "grad", "entry level", "entry-level", "new grad", "intern",
                "internship", "trainee", "fresh graduate", "fresher", "apprentice", "co-op", "tamheer",
                "خريج", "حديثي التخرج", "متدرب", "تمهير")
REMOTE_TERMS = ("remote", "work from home", "wfh", "anywhere", "distributed", "عن بعد")
OPEN_REGIONS = ("worldwide", "anywhere", "global", "international", "emea", "mena", "middle east",
                "gcc", "remote")
LOCATION_ALIASES = {
    "eastern province": ("eastern", "ash sharqiyah", "sharqiyah", "الشرقية", "المنطقة الشرقية", "dammam", "khobar",
                         "al khobar", "dhahran", "jubail", "al jubail", "qatif", "al ahsa", "hofuf", "ras tanura"),
    "saudi arabia": ("ksa", "saudi", "kingdom of saudi arabia", "السعودية", "المملكة العربية السعودية",
                     "riyadh", "jeddah", "dammam", "khobar", "al khobar", "dhahran", "mecca", "makkah",
                     "medina", "madinah", "taif", "tabuk", "abha", "jubail", "yanbu", "neom", "qassim", "buraydah"),
    "united arab emirates": ("uae", "dubai", "abu dhabi", "sharjah", "الإمارات"),
    "qatar": ("doha",),
    "kuwait": ("kuwait city",),
    "bahrain": ("manama",),
    "oman": ("muscat",),
    "egypt": ("cairo", "alexandria", "giza", "مصر"),
    "jordan": ("amman",),
    "united states": ("usa", "u.s.", "united states of america"),
    "united kingdom": ("uk", "england", "london", "scotland"),
    "germany": ("deutschland", "berlin", "munich"),
    "remote": REMOTE_TERMS,
}
COUNTRY_ONLY = {"saudi arabia", "ksa", "kingdom of saudi arabia", "المملكة العربية السعودية", "السعودية"}
STOPWORDS = {"and", "the", "for", "with", "of", "in", "to", "a", "an", "or"}
_YEARS_RE = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years?|yrs?)\b(?:[^.]{0,40}?experience)?")


# Names that mean the whole country/region (they expand to every city in it). A single city never expands.
REGION_SYNONYMS = {"ksa": "saudi arabia", "saudi": "saudi arabia", "kingdom of saudi arabia": "saudi arabia",
                   "السعودية": "saudi arabia", "المملكة العربية السعودية": "saudi arabia",
                   "uae": "united arab emirates", "الإمارات": "united arab emirates", "usa": "united states",
                   "united states of america": "united states", "uk": "united kingdom", "england": "united kingdom",
                   "eastern": "eastern province", "sharqiyah": "eastern province", "ash sharqiyah": "eastern province",
                   "الشرقية": "eastern province", "المنطقة الشرقية": "eastern province"}


def expand_locations(locations: List[str]) -> List[str]:
    terms: List[str] = []
    for location in locations:
        key = norm(location)
        if not key:
            continue
        terms.append(key)
        region = REGION_SYNONYMS.get(key, key)
        if region in LOCATION_ALIASES:
            terms.append(region)
            terms.extend(norm(a) for a in LOCATION_ALIASES[region])
    return list(dict.fromkeys(t for t in terms if t))


def required_years(text: str) -> int:
    years = [int(m.group(1)) for m in _YEARS_RE.finditer(text or "") if "experience" in m.group(0) or "exp" in m.group(0)]
    years = [y for y in years if 0 < y <= 20]
    return min(years) if years else 0


def score_job(job: Dict[str, Any], profile: Dict[str, Any]) -> Tuple[int, List[str], bool]:
    """Return (score 0-100, human reasons, blocked). Blocked jobs are never stored."""
    title = norm(job.get("title", ""))
    location = norm(job.get("location", ""))
    description = norm(job.get("description", ""))[:20000]
    body = " ".join((title, norm(job.get("company", "")), location, description))
    reasons: List[str] = []
    score = 0

    for term in profile.get("exclude", []):
        term = norm(term)
        if term and contains(title, term):
            return 0, [f'title contains excluded "{term}"'], True

    # Role fit (best single role wins)
    best, best_reason = 0, ""
    for role in profile.get("roles", []):
        key = norm(role)
        if not key:
            continue
        words = [w for w in key.split() if w not in STOPWORDS and len(w) > 1]
        if contains(title, key):
            points, why = 45, f'title matches "{role}"'
        elif words and all(contains(title, w) for w in words):
            points, why = 38, f'title has all of "{role}"'
        elif words and len(words) > 1 and sum(contains(title, w) for w in words) / len(words) >= 0.5:
            points, why = 22, f'title partly matches "{role}"'
        elif contains(body, key):
            points, why = 12, f'mentions "{role}"'
        else:
            continue
        if points > best:
            best, best_reason = points, why
    if best:
        score += best
        reasons.append(best_reason)

    # Skills
    skill_hits = [s for s in profile.get("skills", []) if norm(s) and contains(body, norm(s))]
    title_hits = [s for s in skill_hits if contains(title, norm(s))]
    if skill_hits:
        score += min(30, 6 * len(skill_hits) + 4 * len(title_hits))
        reasons.append("skills: " + ", ".join(skill_hits[:6]))

    # Location
    wanted_raw = [l for l in profile.get("locations", []) if norm(l) not in ("remote", "anywhere")]
    wants_remote = profile.get("remote_ok", True) or any(norm(l) in ("remote", "anywhere") for l in profile.get("locations", []))
    wanted = expand_locations(wanted_raw)
    is_remote = bool(job.get("remote")) or any(contains(location, t) or contains(title, t) for t in REMOTE_TERMS)
    location_hit = next((w for w in wanted if contains(location, w)), None)
    if location_hit:
        score += 20
        reasons.append(f"in {job.get('location') or location_hit}")
    elif is_remote and wants_remote:
        restriction = location.replace("remote", "").strip(" -,/()")
        if not restriction or any(contains(location, r) for r in OPEN_REGIONS if r != "remote") \
                or any(contains(location, w) for w in wanted):
            score += 15
            reasons.append("remote, open to your region")
        else:
            score += 2
            reasons.append(f"remote but limited to {job.get('location')}")
    elif wanted and location in COUNTRY_ONLY and any(w in LOCATION_ALIASES.get(location if location != "ksa" else "saudi arabia", ())
                                                      or w in COUNTRY_ONLY for w in wanted):
        reasons.append("city not specified")  # e.g. "Saudi Arabia" only: could be any of your cities
    elif wanted:
        if profile.get("strict_location"):
            return 0, [f"outside your locations ({job.get('location') or 'unknown'})"], True
        if location:
            score -= 25
            reasons.append(f"outside your locations ({job.get('location')})")

    # Excluded words in the description only cost points
    for term in profile.get("exclude", []):
        if norm(term) and contains(description, norm(term)):
            score -= 15
            reasons.append(f'mentions excluded "{term}"')
            break

    # Seniority
    level = profile.get("level", "entry")
    senior = next((t for t in SENIOR_TERMS if contains(title, t)), None)
    junior = next((t for t in JUNIOR_TERMS if contains(title, norm(t))), None)
    years = required_years(description)
    if level == "entry":
        if senior:
            score -= 40
            reasons.append(f'"{senior}" role (you asked for entry level)')
        elif junior:
            score += 15
            reasons.append("entry-level friendly")
        if years >= 5:
            score -= 30
            reasons.append(f"asks for {years}+ years")
        elif years >= 3:
            score -= 15
            reasons.append(f"asks for {years}+ years")
    elif level == "mid":
        if junior in ("intern", "internship", "trainee"):
            score -= 20
            reasons.append("internship/trainee role")
        if senior in ("principal", "director", "vp", "vice president", "chief", "head of"):
            score -= 20
            reasons.append(f'"{senior}" role')
    elif level == "senior":
        if junior:
            score -= 30
            reasons.append("junior role")
        elif senior:
            score += 10
            reasons.append("senior role")

    # Freshness
    days = age_days(job.get("posted_at"))
    if days is not None:
        if days <= 3:
            score += 5
            reasons.append("posted recently")
        elif days > 30:
            score -= 10
            reasons.append("older than a month")

    if job.get("apply_email"):
        reasons.append(f"apply by email: {job['apply_email']}")
    return max(0, min(100, score)), reasons, False
