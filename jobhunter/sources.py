"""Job-site adapters. Each returns normalised job dicts; none of them log in anywhere.

Free sources work out of the box. JSearch (RapidAPI), SerpAPI and Adzuna need a
free/paid API key in .env — JSearch and SerpAPI read Google for Jobs, which covers
LinkedIn, Indeed, Bayt, Glassdoor, company sites and many local boards at once.
"""
from __future__ import annotations

import html
import json
import re
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Mapping, Optional
from urllib.parse import quote_plus, urlencode

from .textutil import extract_emails, html_to_text, parse_date, strip_tags

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")
MAX_PER_CALL = 150


class SourceError(RuntimeError):
    pass


@dataclass
class Query:
    terms: str = ""
    location: str = ""
    level: str = "any"


@dataclass
class Source:
    name: str
    label: str
    fetch: Callable[[Query, Dict[str, Any]], List[Dict[str, Any]]]
    mode: str  # "once" | "query" | "query_location"
    needs: tuple = ()
    default_on: bool = True
    covers: str = ""

    def configured(self, env: Mapping[str, str]) -> bool:
        return all(env.get(key) for key in self.needs)


SOURCES: Dict[str, Source] = {}


def source(name: str, label: str, mode: str, needs: tuple = (), default_on: bool = True, covers: str = ""):
    def register(fn):
        SOURCES[name] = Source(name, label, fn, mode, needs, default_on, covers)
        return fn
    return register


# ── HTTP ─────────────────────────────────────────────────────────────────────

def http_get(url: str, headers: Optional[Dict[str, str]] = None, timeout: int = 25, max_bytes: int = 8_000_000) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": BROWSER_UA, "Accept": "*/*",
                                                   "Accept-Language": "en-US,en;q=0.9,ar;q=0.8", **(headers or {})})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read(max_bytes)
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise SourceError("rate limited (HTTP 429) — will retry next cycle") from None
        raise SourceError(f"HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise SourceError(f"network error: {reason}") from None


def get_json(url: str, headers: Optional[Dict[str, str]] = None) -> Any:
    raw = http_get(url, {"Accept": "application/json", **(headers or {})})
    try:
        return json.loads(raw.decode("utf-8", errors="replace"))
    except ValueError:
        raise SourceError("unexpected (non-JSON) response") from None


def job(source: str, title: str, company: str = "", location: str = "", url: str = "", description: str = "",
        external_id: Any = "", posted_at: Any = None, salary: str = "", remote: bool = False,
        apply_email: str = "") -> Dict[str, Any]:
    description = description or ""
    if not apply_email:
        emails = extract_emails(description)
        apply_email = emails[0] if emails else ""
    return {
        "source": source, "title": strip_tags(title)[:300], "company": strip_tags(company)[:200],
        "location": strip_tags(location)[:200], "url": (url or "").strip(), "description": description[:20000],
        "external_id": str(external_id or "")[:120], "posted_at": parse_date(posted_at), "salary": (salary or "")[:120],
        "remote": bool(remote), "apply_email": apply_email,
    }


def _salary(low: Any, high: Any, currency: str = "") -> str:
    try:
        low_i, high_i = int(float(low or 0)), int(float(high or 0))
    except (TypeError, ValueError):
        return ""
    if not low_i and not high_i:
        return ""
    cur = f"{currency} " if currency else ""
    if low_i and high_i and low_i != high_i:
        return f"{cur}{low_i:,}–{high_i:,}"
    return f"{cur}{max(low_i, high_i):,}"


# ── LinkedIn (public guest search — no login, no account risk) ─────────────

_LI_LEVEL = {"entry": "1,2", "mid": "3,4", "senior": "4,5,6"}


def _tag_attr(tag: str, attr: str) -> str:
    match = re.search(attr + r'\s*=\s*"([^"]*)"', tag)
    return html.unescape(match.group(1)) if match else ""


def parse_linkedin(markup: str) -> List[Dict[str, Any]]:
    jobs = []
    for chunk in re.split(r"<li[\s>]", markup)[1:]:
        urn = re.search(r"urn:li:jobPosting:(\d+)", chunk)
        link_tag = re.search(r"<a\b[^>]*base-card__full-link[^>]*>", chunk) or re.search(r"<a\b[^>]*/jobs/view/[^>]*>", chunk)
        title = re.search(r'<h3[^>]*base-search-card__title[^>]*>(.*?)</h3>', chunk, re.S)
        company = re.search(r'<h4[^>]*base-search-card__subtitle[^>]*>(.*?)</h4>', chunk, re.S)
        location = re.search(r'<span[^>]*job-search-card__location[^>]*>(.*?)</span>', chunk, re.S)
        posted = re.search(r'<time[^>]*datetime="([^"]+)"', chunk)
        salary = re.search(r'<span[^>]*job-search-card__salary-info[^>]*>(.*?)</span>', chunk, re.S)
        if not (title and link_tag):
            continue
        url = _tag_attr(link_tag.group(0), "href").split("?")[0]
        job_id = urn.group(1) if urn else (re.search(r"(\d{6,})/?$", url).group(1) if re.search(r"(\d{6,})/?$", url) else "")
        jobs.append(job("linkedin", title.group(1), company.group(1) if company else "",
                        location.group(1) if location else "", url, external_id=job_id,
                        posted_at=posted.group(1) if posted else None,
                        salary=strip_tags(salary.group(1)) if salary else ""))
    return jobs


@source("linkedin", "LinkedIn", "query_location", covers="LinkedIn public job search (all countries)")
def fetch_linkedin(query: Query, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    params = {"keywords": query.terms, "location": query.location or "Worldwide", "f_TPR": "r604800", "start": "0"}
    if query.level in _LI_LEVEL:
        params["f_E"] = _LI_LEVEL[query.level]
    if not query.location:
        params["f_WT"] = "2"  # remote
    out: List[Dict[str, Any]] = []
    for start in (0, 25):
        params["start"] = str(start)
        url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?" + urlencode(params)
        page = parse_linkedin(http_get(url, {"Accept": "text/html"}).decode("utf-8", errors="replace"))
        out.extend(page)
        if len(page) < 20:
            break
        time.sleep(ctx.get("delay", 1.5))
    return out


def enrich_linkedin(item: Dict[str, Any]) -> Dict[str, Any]:
    """Fetch the public job page for a description (improves scoring and finds apply emails)."""
    if not item.get("external_id"):
        return item
    markup = http_get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{item['external_id']}",
                      {"Accept": "text/html"}).decode("utf-8", errors="replace")
    body = re.search(r'<div[^>]*show-more-less-html__markup[^>]*>(.*?)</div>', markup, re.S)
    if body:
        item = dict(item)
        item["description"] = html_to_text(body.group(1))[:20000]
        emails = extract_emails(item["description"])
        if emails and not item.get("apply_email"):
            item["apply_email"] = emails[0]
    return item


ENRICHERS = {"linkedin": enrich_linkedin}


# ── Bayt (largest Gulf job board; public search pages, gently rate-limited) ──

_BAYT_COUNTRIES = {"saudi arabia": "saudi-arabia", "ksa": "saudi-arabia", "saudi": "saudi-arabia",
                   "riyadh": "saudi-arabia", "jeddah": "saudi-arabia", "dammam": "saudi-arabia", "khobar": "saudi-arabia",
                   "eastern": "saudi-arabia", "dhahran": "saudi-arabia", "jubail": "saudi-arabia", "taif": "saudi-arabia",
                   "mecca": "saudi-arabia", "makkah": "saudi-arabia", "medina": "saudi-arabia",
                   "united arab emirates": "uae", "uae": "uae", "dubai": "uae", "abu dhabi": "uae", "qatar": "qatar",
                   "kuwait": "kuwait", "bahrain": "bahrain", "oman": "oman", "egypt": "egypt", "jordan": "jordan"}


def parse_bayt(markup: str) -> List[Dict[str, Any]]:
    jobs = []
    for chunk in re.split(r"<li\b", markup)[1:]:
        if "data-js-job" not in chunk[:600]:
            continue
        heading = re.search(r"<h2[^>]*>(.*?)</h2>", chunk, re.S)
        link = re.search(r'<a\b[^>]*href="([^"]+)"', heading.group(1)) if heading else None
        if not (heading and link):
            continue
        company = re.search(r'<div[^>]*class="[^"]*t-nowrap p10l[^"]*"[^>]*>.*?<span[^>]*>(.*?)</span>', chunk, re.S)
        location = re.search(r'<div[^>]*class="[^"]*t-mute t-small[^"]*"[^>]*>(.*?)</div>', chunk, re.S)
        href = html.unescape(link.group(1)).strip()
        url = href if href.startswith("http") else "https://www.bayt.com" + href
        job_id = re.search(r"-(\d{5,})/?$", url.split("?")[0])
        jobs.append(job("bayt", heading.group(1), company.group(1) if company else "",
                        location.group(1) if location else "", url.split("?")[0],
                        external_id=job_id.group(1) if job_id else url))
    return jobs


@source("bayt", "Bayt.com", "query_location", covers="Saudi Arabia, UAE and the Gulf")
def fetch_bayt(query: Query, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    location = (query.location or "").lower()
    country = next((slug for key, slug in _BAYT_COUNTRIES.items() if key in location), "international")
    slug = re.sub(r"[^a-z0-9]+", "-", query.terms.lower()).strip("-")
    if not slug:
        return []
    markup = http_get(f"https://www.bayt.com/en/{country}/jobs/{slug}-jobs/", {"Accept": "text/html"})
    return parse_bayt(markup.decode("utf-8", errors="replace"))


# ── Free remote-job boards ──────────────────────────────────────────────────

@source("remotive", "Remotive", "query", covers="Remote tech jobs")
def fetch_remotive(query: Query, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = get_json("https://remotive.com/api/remote-jobs?" + urlencode({"search": query.terms, "limit": 60}))
    return [job("remotive", j.get("title", ""), j.get("company_name", ""), j.get("candidate_required_location") or "Remote",
                j.get("url", ""), html_to_text(j.get("description", "")), j.get("id"), j.get("publication_date"),
                j.get("salary") or "", True)
            for j in (data.get("jobs") or [])[:MAX_PER_CALL]]


@source("remoteok", "RemoteOK", "once", covers="Remote jobs")
def fetch_remoteok(query: Query, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = get_json("https://remoteok.com/api")
    rows = [j for j in data if isinstance(j, dict) and j.get("position")] if isinstance(data, list) else []
    return [job("remoteok", j.get("position", ""), j.get("company", ""), j.get("location") or "Remote",
                j.get("url") or j.get("apply_url", ""), html_to_text(j.get("description", "")), j.get("id"),
                j.get("date") or j.get("epoch"), _salary(j.get("salary_min"), j.get("salary_max"), "USD"), True)
            for j in rows[:MAX_PER_CALL]]


@source("jobicy", "Jobicy", "query", covers="Remote jobs")
def fetch_jobicy(query: Query, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = get_json("https://jobicy.com/api/v2/remote-jobs?" + urlencode({"count": 50, "tag": query.terms}))
    return [job("jobicy", j.get("jobTitle", ""), j.get("companyName", ""), j.get("jobGeo") or "Remote", j.get("url", ""),
                html_to_text(j.get("jobDescription") or j.get("jobExcerpt", "")), j.get("id"), j.get("pubDate"),
                _salary(j.get("annualSalaryMin"), j.get("annualSalaryMax"), j.get("salaryCurrency", "")), True)
            for j in (data.get("jobs") or [])[:MAX_PER_CALL]]


@source("himalayas", "Himalayas", "once", covers="Remote jobs")
def fetch_himalayas(query: Query, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = get_json("https://himalayas.app/jobs/api?limit=100")
    out = []
    for j in (data.get("jobs") or [])[:MAX_PER_CALL]:
        where = ", ".join(j.get("locationRestrictions") or []) or "Remote (worldwide)"
        out.append(job("himalayas", j.get("title", ""), j.get("companyName", ""), where,
                       j.get("applicationLink") or j.get("guid", ""), html_to_text(j.get("description") or j.get("excerpt", "")),
                       j.get("guid"), j.get("pubDate"), _salary(j.get("minSalary"), j.get("maxSalary"), j.get("currency", "")), True))
    return out


@source("arbeitnow", "Arbeitnow", "once", covers="Europe + remote jobs")
def fetch_arbeitnow(query: Query, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    data = get_json("https://www.arbeitnow.com/api/job-board-api")
    return [job("arbeitnow", j.get("title", ""), j.get("company_name", ""), j.get("location", ""), j.get("url", ""),
                html_to_text(j.get("description", "")), j.get("slug"), j.get("created_at"), "", bool(j.get("remote")))
            for j in (data.get("data") or [])[:MAX_PER_CALL]]


def parse_feed(raw: bytes, source_name: str) -> List[Dict[str, Any]]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        raise SourceError("feed is not valid RSS/Atom") from None
    out = []
    for node in root.findall(".//item")[:MAX_PER_CALL]:
        title = (node.findtext("title") or "").strip()
        company = ""
        if ": " in title and source_name == "weworkremotely":
            company, title = title.split(": ", 1)
        elif " at " in title:
            title, company = title.rsplit(" at ", 1)
        region = node.findtext("region") or node.findtext("location") or ""
        out.append(job(source_name, title, company, region or ("Remote" if source_name == "weworkremotely" else ""),
                       (node.findtext("link") or "").strip(), html_to_text(node.findtext("description") or ""),
                       node.findtext("guid") or node.findtext("link"), node.findtext("pubDate"),
                       remote=source_name == "weworkremotely" or "remote" in region.lower()))
    ns = {"a": "http://www.w3.org/2005/Atom"}
    for node in root.findall(".//a:entry", ns)[:MAX_PER_CALL]:
        link = node.find("a:link", ns)
        title = (node.findtext("a:title", default="", namespaces=ns) or "").strip()
        company = ""
        if " at " in title:
            title, company = title.rsplit(" at ", 1)
        out.append(job(source_name, title, company, "", link.attrib.get("href", "") if link is not None else "",
                       html_to_text(node.findtext("a:summary", default="", namespaces=ns)
                                    or node.findtext("a:content", default="", namespaces=ns)),
                       node.findtext("a:id", default="", namespaces=ns),
                       node.findtext("a:updated", default="", namespaces=ns)))
    return [j for j in out if j["title"] and j["url"]]


@source("weworkremotely", "We Work Remotely", "once", covers="Remote jobs")
def fetch_wwr(query: Query, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    return parse_feed(http_get("https://weworkremotely.com/remote-jobs.rss"), "weworkremotely")


# ── Company career pages (Greenhouse / Lever boards you list in the profile) ─

@source("greenhouse", "Greenhouse boards", "once", covers="Career pages of companies you list")
def fetch_greenhouse(query: Query, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for board in ctx.get("profile", {}).get("greenhouse_boards", [])[:30]:
        token = re.sub(r"[^a-z0-9_-]", "", board.lower())
        if not token:
            continue
        data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
        for j in (data.get("jobs") or [])[:MAX_PER_CALL]:
            out.append(job("greenhouse", j.get("title", ""), j.get("company_name") or board.title(),
                           (j.get("location") or {}).get("name", ""), j.get("absolute_url", ""),
                           html_to_text(html.unescape(j.get("content") or "")), j.get("id"), j.get("updated_at")))
    return out


@source("lever", "Lever boards", "once", covers="Career pages of companies you list")
def fetch_lever(query: Query, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for board in ctx.get("profile", {}).get("lever_boards", [])[:30]:
        token = re.sub(r"[^a-z0-9_-]", "", board.lower())
        if not token:
            continue
        data = get_json(f"https://api.lever.co/v0/postings/{token}?mode=json")
        for j in (data if isinstance(data, list) else [])[:MAX_PER_CALL]:
            cats = j.get("categories") or {}
            out.append(job("lever", j.get("text", ""), board.title(), cats.get("location", ""), j.get("hostedUrl", ""),
                           j.get("descriptionPlain") or html_to_text(j.get("description", "")), j.get("id"),
                           j.get("createdAt"), remote=(j.get("workplaceType") == "remote")))
    return out


@source("rss", "Your RSS feeds", "once", covers="Any job feed URL you add (Bayt/company/Telegram-to-RSS feeds…)")
def fetch_rss(query: Query, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    feeds = list(ctx.get("profile", {}).get("rss_feeds", [])) + list(ctx.get("extra_feeds", []))
    out, errors = [], []
    for url in dict.fromkeys(feeds):
        if not url.startswith(("http://", "https://")):
            continue
        try:
            out.extend(parse_feed(http_get(url), "rss"))
        except SourceError as exc:
            errors.append(f"{url}: {exc}")
    if errors and not out:
        raise SourceError("; ".join(errors)[:300])
    return out


# ── Aggregators that need an API key (cover Indeed, Bayt, Glassdoor, …) ───

@source("jsearch", "JSearch (Google for Jobs)", "query_location", needs=("RAPIDAPI_KEY",),
        covers="LinkedIn, Indeed, Glassdoor, Bayt, ZipRecruiter, company sites")
def fetch_jsearch(query: Query, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    env = ctx.get("env", {})
    text = f"{query.terms} in {query.location}" if query.location else f"{query.terms} remote"
    params = {"query": text, "page": 1, "num_pages": 1, "date_posted": "week"}
    if not query.location:
        params["remote_jobs_only"] = "true"
    data = get_json("https://jsearch.p.rapidapi.com/search?" + urlencode(params),
                    {"X-RapidAPI-Key": env.get("RAPIDAPI_KEY", ""), "X-RapidAPI-Host": "jsearch.p.rapidapi.com"})
    out = []
    for j in (data.get("data") or [])[:MAX_PER_CALL]:
        where = j.get("job_location") or ", ".join(x for x in (j.get("job_city"), j.get("job_state"), j.get("job_country")) if x)
        publisher = (j.get("job_publisher") or "").lower().replace(" ", "")
        out.append(job(f"jsearch:{publisher}" if publisher else "jsearch", j.get("job_title", ""), j.get("employer_name", ""),
                       where, j.get("job_apply_link") or j.get("job_google_link", ""), j.get("job_description", ""),
                       j.get("job_id"), j.get("job_posted_at_datetime_utc"),
                       _salary(j.get("job_min_salary"), j.get("job_max_salary"), j.get("job_salary_currency") or ""),
                       bool(j.get("job_is_remote"))))
    return out


@source("serpapi", "SerpAPI (Google for Jobs)", "query_location", needs=("SERPAPI_KEY",),
        covers="Google for Jobs: LinkedIn, Bayt, Indeed, company sites")
def fetch_serpapi(query: Query, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    env = ctx.get("env", {})
    data = get_json("https://serpapi.com/search.json?" + urlencode({
        "engine": "google_jobs", "q": f"{query.terms} {query.location or 'remote'}".strip(), "hl": "en",
        "api_key": env.get("SERPAPI_KEY", "")}))
    out = []
    for j in (data.get("jobs_results") or [])[:MAX_PER_CALL]:
        options = j.get("apply_options") or []
        link = options[0].get("link") if options else j.get("share_link", "")
        ext = j.get("detected_extensions") or {}
        via = (j.get("via") or "").replace("via ", "").lower().replace(" ", "")
        out.append(job(f"google:{via}" if via else "google", j.get("title", ""), j.get("company_name", ""),
                       j.get("location", ""), link, j.get("description", ""), j.get("job_id"), None,
                       ext.get("salary", ""), bool(ext.get("work_from_home"))))
    return out


@source("adzuna", "Adzuna", "query_location", needs=("ADZUNA_APP_ID", "ADZUNA_APP_KEY"),
        covers="UK, US, EU, India, Singapore… (set ADZUNA_COUNTRY)")
def fetch_adzuna(query: Query, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    env = ctx.get("env", {})
    country = (env.get("ADZUNA_COUNTRY") or "gb").lower()[:2]
    params = {"app_id": env.get("ADZUNA_APP_ID", ""), "app_key": env.get("ADZUNA_APP_KEY", ""),
              "what": query.terms, "results_per_page": 50, "max_days_old": 14, "content-type": "application/json"}
    if query.location:
        params["where"] = query.location
    data = get_json(f"https://api.adzuna.com/v1/api/jobs/{country}/search/1?" + urlencode(params))
    return [job("adzuna", j.get("title", ""), (j.get("company") or {}).get("display_name", ""),
                (j.get("location") or {}).get("display_name", ""), j.get("redirect_url", ""), j.get("description", ""),
                j.get("id"), j.get("created"), _salary(j.get("salary_min"), j.get("salary_max")))
            for j in (data.get("results") or [])[:MAX_PER_CALL]]


# ── helpers for the agent/UI ────────────────────────────────────────────────

def source_enabled(name: str, profile: Dict[str, Any], env: Mapping[str, str]) -> bool:
    src = SOURCES[name]
    wanted = profile.get("sources", {}).get(name, src.default_on)
    return bool(wanted) and src.configured(env)


def describe_sources(profile: Dict[str, Any], env: Mapping[str, str]) -> List[Dict[str, Any]]:
    return [{"name": s.name, "label": s.label, "covers": s.covers, "needs": list(s.needs),
             "configured": s.configured(env), "enabled": source_enabled(s.name, profile, env),
             "wanted": bool(profile.get("sources", {}).get(s.name, s.default_on))}
            for s in SOURCES.values()]


def search_url(site: str, terms: str, location: str) -> str:
    """Deep links for boards without an API (used in digests as 'also check')."""
    q, loc = quote_plus(terms), quote_plus(location)
    return {
        "Indeed": f"https://www.indeed.com/jobs?q={q}&l={loc}",
        "Bayt": f"https://www.bayt.com/en/international/jobs/{q.replace('+', '-')}-jobs/?q={q}&location={loc}",
        "Glassdoor": f"https://www.glassdoor.com/Job/jobs.htm?sc.keyword={q}&locKeyword={loc}",
        "Google Jobs": f"https://www.google.com/search?q={q}+jobs+{loc}&ibp=htl;jobs",
    }.get(site, "")
