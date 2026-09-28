"""Understanding incoming mail: employer replies, job-alert emails and recruiter outreach."""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from .mailbox import IncomingMail
from .sources import job as make_job
from .textutil import base_domain, contains, email_domain, norm, url_domain

REPLY_RULES: List[Tuple[str, Tuple[str, ...]]] = [
    ("rejected", ("unfortunately", "not moving forward", "not to move forward", "not be moving forward",
                  "decided to pursue other candidates", "decided to move forward with other", "regret to inform",
                  "position has been filled", "will not be progressing", "not been successful", "not been selected",
                  "we are unable to offer", "no longer under consideration", "للأسف", "نعتذر", "لم يتم اختيار")),
    ("offer", ("offer letter", "pleased to offer", "job offer", "offer of employment", "extend an offer", "عرض وظيفي")),
    ("interview", ("interview", "schedule a call", "schedule a time", "your availability", "phone screen",
                   "meet with our", "calendly.com", "invite you to", "مقابلة")),
    ("assessment", ("assessment", "coding challenge", "hackerrank", "codility", "take-home", "take home",
                    "online test", "technical test", "assignment", "اختبار")),
    ("received", ("received your application", "thank you for applying", "thanks for applying",
                  "application has been received", "we have received", "application received",
                  "thank you for your application", "thank you for your interest", "تم استلام")),
]
LABELS = {"rejected": "Rejection", "offer": "Offer!", "interview": "Interview invitation",
          "assessment": "Assessment / test", "received": "Application received", "other": "New message"}

JOB_ALERT_DOMAINS = ("linkedin.com", "indeed.com", "bayt.com", "glassdoor.com", "naukrigulf.com", "gulftalent.com",
                     "ziprecruiter.com", "monster.com", "wuzzuf.net", "tanqeeb.com", "wellfound.com", "dice.com",
                     "jooble.org", "careerjet.com", "himalayas.app", "remotive.com", "weworkremotely.com",
                     "talent.com", "simplyhired.com", "jobs.ac.uk", "drjobpro.com", "akhtaboot.com")
NON_COMPANY_DOMAINS = JOB_ALERT_DOMAINS + (
    "greenhouse.io", "lever.co", "myworkdayjobs.com", "workday.com", "smartrecruiters.com", "icims.com", "taleo.net",
    "successfactors.com", "bamboohr.com", "ashbyhq.com", "jobvite.com", "recruitee.com", "workable.com",
    "teamtailor.com", "breezy.hr", "gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com",
    "yahoo.com", "icloud.com", "me.com", "google.com", "sendgrid.net", "mailchimp.com", "amazonses.com")
RECRUITING_WORDS = ("interview", "your application", "job opportunity", "position", "recruiter", "recruiting",
                    "hiring", "candidate", "your cv", "your resume", "role at", "وظيفة", "توظيف")
_JOB_LINK = re.compile(r"(/jobs?/view/|/comm/jobs/view/|viewjob|[?&]jk=|/rc/clk|/job-listing/|joblisting|"
                       r"/jobs?/[^/?#]*\d{4,}|/careers?/[^?#]+|jobid=|/job/)", re.I)
_GENERIC_ANCHOR = re.compile(r"^(view|see|apply|show|search|unsubscribe|manage|more|all|save|open|jobs? alert|"
                             r"learn more|help|privacy|settings|click here|here|\d+ new jobs?)\b", re.I)


def classify_reply(subject: str, text: str) -> str:
    haystack = f"{subject}\n{text[:6000]}".lower()
    for label, phrases in REPLY_RULES:
        if any(p in haystack for p in phrases):
            return label
    return "other"


def is_job_alert(msg: IncomingMail) -> bool:
    domain = email_domain(msg.from_addr)
    return any(domain == d or domain.endswith("." + d) for d in JOB_ALERT_DOMAINS)


def _canonical(url: str) -> str:
    match = re.search(r"linkedin\.com/(?:comm/)?jobs/view/(?:[^/?#]*-)?(\d{6,})", url)
    if match:
        return f"https://www.linkedin.com/jobs/view/{match.group(1)}"
    return url.split("#")[0]


def parse_alert(msg: IncomingMail) -> List[Dict[str, Any]]:
    """Pull job links (and nearby company/location lines) out of a job-alert email."""
    site = base_domain(email_domain(msg.from_addr)).split(".")[0] or "email"
    lines = [line.strip() for line in msg.text.splitlines() if line.strip()]
    found: Dict[str, Dict[str, Any]] = {}
    for href, anchor in msg.links:
        if not href.startswith("http") or not _JOB_LINK.search(href):
            continue
        title = " ".join(anchor.split())
        if not (4 <= len(title) <= 120) or _GENERIC_ANCHOR.search(title):
            continue
        url = _canonical(href)
        if url in found:
            continue
        company = location = ""
        if title in lines:
            idx = lines.index(title)
            following = [l for l in lines[idx + 1: idx + 4] if len(l) < 80 and not l.startswith("http")]
            if following:
                parts = [p.strip() for p in re.split(r"\s[·•|-]\s", following[0]) if p.strip()]
                company = parts[0]
                location = parts[1] if len(parts) > 1 else (following[1] if len(following) > 1 and "," in following[1] else "")
        found[url] = make_job(f"email:{site}", title, company, location, url)
    return list(found.values())[:40]


def looks_recruiting(msg: IncomingMail) -> bool:
    if msg.list_unsubscribe or msg.auto_submitted.startswith("auto-generated"):
        return False
    haystack = f"{msg.subject}\n{msg.text[:3000]}".lower()
    return sum(word in haystack for word in RECRUITING_WORDS) >= 2


def match_company(msg: IncomingMail, jobs: List[Dict[str, Any]], header_only: bool = False) -> Optional[Dict[str, Any]]:
    """Find the tracked application an email most likely belongs to.

    header_only: for job-board mail (e.g. "Your application was sent to Acme") only the
    subject/sender may match — the body of an alert lists many unrelated companies.
    """
    sender_domain = base_domain(email_domain(msg.from_addr))
    sender_is_company = bool(sender_domain) and not any(sender_domain.endswith(d) for d in NON_COMPANY_DOMAINS)
    header = norm(f"{msg.subject} {msg.from_name}")
    body = norm(msg.text[:4000])
    best, best_points = None, 0
    for job in jobs:
        points = 0
        company = norm(job.get("company", ""))
        if len(company) >= 3 and contains(header, company):
            points += 3
        elif not header_only and len(company) >= 4 and contains(body, company) and contains(body, norm(job.get("title", ""))):
            points += 2
        if sender_is_company and not header_only:
            for known in (email_domain(job.get("apply_email", "")), url_domain(job.get("url", ""))):
                if known and base_domain(known) == sender_domain:
                    points += 3
        if points > best_points:
            best, best_points = job, points
    return best if best_points >= (3 if header_only else 2) else None
