"""Watch the career pages of companies you care about.

Give it any company link — the homepage, the careers page, or a Greenhouse / Lever /
Ashby / Workable / SmartRecruiters board. It finds the careers page, detects the job
system behind it and pulls every open role (checked on every search cycle).
Sites that only render jobs with JavaScript portals (SAP SuccessFactors, Oracle, Taleo…)
are reported so you can open them in the browser instead.
"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, List, Tuple
from urllib.parse import urljoin, urlparse

from .sources import SourceError, get_json, http_get, job
from .textutil import base_domain, html_to_text, html_to_text_and_links, strip_tags, url_domain

ATS_PATTERNS = [
    ("greenhouse", re.compile(r"(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io/(?:embed/job_board\?for=)?([A-Za-z0-9_-]+)")),
    ("lever", re.compile(r"jobs\.(?:eu\.)?lever\.co/([A-Za-z0-9_.-]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.%-]+)")),
    ("workable", re.compile(r"apply\.workable\.com/([A-Za-z0-9_-]+)")),
    ("smartrecruiters", re.compile(r"(?:careers|jobs)\.smartrecruiters\.com/([A-Za-z0-9_-]+)")),
]
BROWSER_ONLY = ("successfactors", "oraclecloud.com", "taleo.net", "myworkdayjobs.com", "icims.com", "jadarat",
                "zohorecruit", "bamboohr.com", "careers.sap", "recruitee.com")
CAREER_LINK = re.compile(r"(career|jobs|vacanc|join[- ]?us|work[- ]?with[- ]?us|opportunit|hiring|وظائف|الوظائف|التوظيف|انضم)", re.I)
JOB_HREF = re.compile(r"(/jobs?/|/careers?/.+|/vacanc|/position|/opening|/requisition|jobid=|job_id=|/apply/|/o/|/j/)", re.I)
GENERIC = re.compile(r"^(apply|apply now|view|view all|see all|jobs|careers|learn more|read more|more|home|about|contact|"
                     r"privacy|terms|login|sign in|register|search|filter|back|next|previous|english|عربي|العربية|"
                     r"التقديم|تقدم الآن|المزيد)$", re.I)


def detect_ats(text: str) -> Tuple[str, str]:
    for name, pattern in ATS_PATTERNS:
        match = pattern.search(text)
        if match and match.group(1).lower() not in ("embed", "js", "api"):
            return name, match.group(1)
    return "", ""


def fetch_ats(kind: str, token: str, company: str) -> List[Dict[str, Any]]:
    if kind == "greenhouse":
        data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
        return [job("company:greenhouse", j.get("title", ""), company, (j.get("location") or {}).get("name", ""),
                    j.get("absolute_url", ""), html_to_text(html.unescape(j.get("content") or "")),
                    j.get("id"), j.get("updated_at")) for j in data.get("jobs") or []]
    if kind == "lever":
        data = get_json(f"https://api.lever.co/v0/postings/{token}?mode=json")
        return [job("company:lever", j.get("text", ""), company, (j.get("categories") or {}).get("location", ""),
                    j.get("hostedUrl", ""), j.get("descriptionPlain", ""), j.get("id"), j.get("createdAt"),
                    remote=j.get("workplaceType") == "remote") for j in (data if isinstance(data, list) else [])]
    if kind == "ashby":
        data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=false")
        return [job("company:ashby", j.get("title", ""), company, j.get("location", ""), j.get("jobUrl", ""),
                    j.get("descriptionPlain", ""), j.get("id"), j.get("publishedAt"), remote=bool(j.get("isRemote")))
                for j in data.get("jobs") or []]
    if kind == "workable":
        data = get_json(f"https://apply.workable.com/api/v1/widget/accounts/{token}")
        return [job("company:workable", j.get("title", ""), data.get("name") or company,
                    ", ".join(x for x in (j.get("city"), j.get("country")) if x), j.get("url") or j.get("shortlink", ""),
                    "", j.get("shortcode"), j.get("published_on"), remote=bool(j.get("telecommuting")))
                for j in data.get("jobs") or []]
    if kind == "smartrecruiters":
        data = get_json(f"https://api.smartrecruiters.com/v1/companies/{token}/postings?limit=100")
        return [job("company:smartrecruiters", j.get("name", ""), (j.get("company") or {}).get("name") or company,
                    ", ".join(x for x in ((j.get("location") or {}).get("city"), (j.get("location") or {}).get("country")) if x),
                    f"https://jobs.smartrecruiters.com/{token}/{j.get('id')}", "", j.get("id"), j.get("releasedDate"),
                    remote=bool((j.get("location") or {}).get("remote"))) for j in data.get("content") or []]
    return []


def company_name(url: str, page: str = "") -> str:
    title = re.search(r"<title[^>]*>(.*?)</title>", page or "", re.S | re.I)
    if title:
        text = strip_tags(title.group(1))
        piece = re.split(r"\s[|\-–—:]\s", text)
        generic = re.compile(r"^(home|homepage|welcome|official (web)?site|الرئيسية|الصفحة الرئيسية)$", re.I)
        candidates = [p.strip() for p in piece if p.strip() and not CAREER_LINK.search(p) and not generic.match(p.strip())]
        if candidates and len(candidates[0]) <= 60:
            return candidates[0]
    host = url_domain(url).split(".")
    return (host[-2] if len(host) >= 2 else host[0]).replace("-", " ").title()


def jobs_from_page(page: str, base_url: str, company: str) -> List[Dict[str, Any]]:
    _, links = html_to_text_and_links(page)
    host = url_domain(base_url)
    found: Dict[str, Dict[str, Any]] = {}
    for href, text in links:
        url = urljoin(base_url, href)
        title = " ".join(text.split())
        if not url.startswith("http") or not (4 <= len(title) <= 120) or GENERIC.match(title):
            continue
        same_site = base_domain(url_domain(url)) == base_domain(host)
        if not same_site or not JOB_HREF.search(urlparse(url).path + "?" + urlparse(url).query):
            continue
        if url.rstrip("/") == base_url.rstrip("/"):
            continue
        found.setdefault(url.split("#")[0], job("company:site", title, company, "", url.split("#")[0]))
    return list(found.values())[:100]


def _load(url: str) -> str:
    return http_get(url, {"Accept": "text/html"}, timeout=25, max_bytes=3_000_000).decode("utf-8", errors="replace")


def scan_site(url: str, follow: bool = True, company: str = "") -> Tuple[List[Dict[str, Any]], str]:
    """Return (jobs, human status) for one company link: homepage, careers page or ATS board."""
    kind, token = detect_ats(url)
    if kind:
        jobs = fetch_ats(kind, token, company or token.replace("-", " ").title())
        return jobs, f"{len(jobs)} open roles via {kind.title()}"
    if any(marker in url.lower() for marker in BROWSER_ONLY):
        return [], "career portal needs a browser (SAP/Oracle/Workday/Taleo…) — check it manually"
    page = _load(url)
    company = company or company_name(url, page)
    kind, token = detect_ats(page)
    if kind:
        jobs = fetch_ats(kind, token, company)
        return jobs, f"{len(jobs)} open roles via {kind.title()}"
    if any(marker in page.lower() for marker in BROWSER_ONLY):
        return [], "career portal needs a browser (SAP/Oracle/Workday/Taleo…) — check it manually"
    jobs = jobs_from_page(page, url, company)
    if not jobs and follow:
        _, links = html_to_text_and_links(page)
        careers = next((urljoin(url, h) for h, t in links if CAREER_LINK.search(t or "") or CAREER_LINK.search(h or "")), None)
        if careers and careers.rstrip("/") != url.rstrip("/") and careers.startswith("http"):
            return scan_site(careers, follow=False, company=company)
    return jobs, (f"{len(jobs)} job links found" if jobs else "no job links found (the page may load jobs with JavaScript)")


def fetch_company_sites(query, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    sites = ctx.get("profile", {}).get("company_sites", [])
    status = ctx.setdefault("company_status", {})
    out, failures = [], []
    for url in sites[:60]:
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        try:
            jobs, note = scan_site(url)
        except SourceError as exc:
            jobs, note = [], f"error: {exc}"
            failures.append(url)
        status[url] = note
        out.extend(jobs)
    if failures and len(failures) == len(sites) and sites:
        raise SourceError(f"could not reach {len(failures)} company site(s)")
    return out


from .sources import SOURCES, Source  # noqa: E402  (registered here to avoid a circular import)

SOURCES["companies"] = Source("companies", "Your company websites", fetch_company_sites, "once",
                              covers="Career pages of the companies you send me (auto-detects Greenhouse, Lever, Ashby, Workable, SmartRecruiters)")
