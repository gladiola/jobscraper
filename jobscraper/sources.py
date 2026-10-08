"""Job sources: public job-board APIs and a generic schema.org JobPosting scraper."""

from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Iterator, List, Optional
from urllib.parse import parse_qs, urldefrag, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from .extract import detect_education, detect_experience, html_to_text, parse_date, today_utc
from .fetch import Fetcher
from .models import HYBRID, ONSITE, REMOTE, UNKNOWN, Job

log = logging.getLogger(__name__)


@dataclass
class SearchQuery:
    """Hints passed to sources that support server-side searching."""

    keywords: List[str] = field(default_factory=list)
    locations: List[str] = field(default_factory=list)
    remote_only: bool = False
    include_hybrid: bool = False
    posted_within_days: Optional[int] = None


class Source:
    """Base class for a job source."""

    name = "source"
    domain = ""

    def fetch(self, fetcher: Fetcher, query: SearchQuery) -> Iterator[Job]:  # pragma: no cover - interface
        raise NotImplementedError


def _salary(low: Any = None, high: Any = None, currency: str = "", unit: str = "") -> str:
    def fmt(value: Any) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        return f"{number:,.0f}"

    low = low or None
    high = high or None
    if low is None and high is None:
        return ""
    if low is not None and high is not None and low != high:
        text = f"{fmt(low)}-{fmt(high)}"
    else:
        text = fmt(low if low is not None else high)
    text = f"{currency} {text}".strip()
    return f"{text} per {unit.lower()}" if unit else text


def _date_from_timestamp(value: Any, millis: bool = False) -> str:
    try:
        seconds = float(value) / (1000 if millis else 1)
    except (TypeError, ValueError):
        return ""
    return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%d")


# --------------------------------------------------------------------------- API sources


class RemoteOK(Source):
    """https://remoteok.com - remote jobs (public JSON API)."""

    name = "remoteok"
    domain = "remoteok.com"
    api_url = "https://remoteok.com/api"

    def fetch(self, fetcher: Fetcher, query: SearchQuery) -> Iterator[Job]:
        for item in fetcher.get_json(self.api_url):
            # The first element of the response is a legal notice, not a job.
            if not isinstance(item, dict) or not item.get("position"):
                continue
            yield Job(
                title=item.get("position", ""),
                company=item.get("company", ""),
                location=item.get("location") or "",
                remote=REMOTE,
                url=item.get("url") or f"https://remoteok.com/remote-jobs/{item.get('id', '')}",
                source=self.name,
                posted_date=str(item.get("date") or "")[:10],
                salary=_salary(item.get("salary_min"), item.get("salary_max"), "USD"),
                tags=[str(tag) for tag in item.get("tags") or []],
                description=html_to_text(item.get("description")),
            )


class Remotive(Source):
    """https://remotive.com - remote jobs (public JSON API with server-side search)."""

    name = "remotive"
    domain = "remotive.com"
    api_url = "https://remotive.com/api/remote-jobs"
    # With many search terms one unfiltered request is cheaper than one request per term.
    max_search_terms = 3

    def fetch(self, fetcher: Fetcher, query: SearchQuery) -> Iterator[Job]:
        terms: List[Optional[str]] = list(query.keywords)
        if not terms or len(terms) > self.max_search_terms:
            terms = [None]
        for term in terms:
            params = {"search": term} if term else None
            for item in fetcher.get_json(self.api_url, params=params).get("jobs", []):
                tags = [str(tag) for tag in item.get("tags") or []]
                if item.get("category"):
                    tags.insert(0, item["category"])
                yield Job(
                    title=item.get("title", ""),
                    company=item.get("company_name", ""),
                    location=item.get("candidate_required_location") or "",
                    remote=REMOTE,
                    url=item.get("url", ""),
                    source=self.name,
                    posted_date=str(item.get("publication_date") or "")[:10],
                    employment_type=str(item.get("job_type") or "").replace("_", " ").title(),
                    salary=item.get("salary") or "",
                    tags=tags,
                    description=html_to_text(item.get("description")),
                )


class Arbeitnow(Source):
    """https://www.arbeitnow.com - jobs in Europe and remote (public JSON API, paginated)."""

    name = "arbeitnow"
    domain = "arbeitnow.com"
    api_url = "https://www.arbeitnow.com/api/job-board-api"
    max_pages = 5

    def fetch(self, fetcher: Fetcher, query: SearchQuery) -> Iterator[Job]:
        for page in range(1, self.max_pages + 1):
            payload = fetcher.get_json(self.api_url, params={"page": page})
            for item in payload.get("data", []):
                yield Job(
                    title=item.get("title", ""),
                    company=item.get("company_name", ""),
                    location=item.get("location") or "",
                    remote=REMOTE if item.get("remote") else UNKNOWN,
                    url=item.get("url", ""),
                    source=self.name,
                    posted_date=_date_from_timestamp(item.get("created_at")),
                    employment_type=", ".join(item.get("job_types") or []),
                    tags=[str(tag) for tag in item.get("tags") or []],
                    description=html_to_text(item.get("description")),
                )
            if not (payload.get("links") or {}).get("next"):
                break


class Greenhouse(Source):
    """Jobs from a company's Greenhouse board (https://boards.greenhouse.io/<board>)."""

    domain = "greenhouse.io"

    def __init__(self, board: str) -> None:
        self.board = board
        self.name = f"greenhouse:{board}"

    def fetch(self, fetcher: Fetcher, query: SearchQuery) -> Iterator[Job]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{self.board}/jobs"
        for item in fetcher.get_json(url, params={"content": "true"}).get("jobs", []):
            departments = [d.get("name", "") for d in item.get("departments") or [] if d.get("name")]
            yield Job(
                title=item.get("title", ""),
                company=item.get("company_name") or self.board,
                location=(item.get("location") or {}).get("name", ""),
                url=item.get("absolute_url", ""),
                source=self.name,
                posted_date=str(item.get("first_published") or item.get("updated_at") or "")[:10],
                tags=departments,
                # Greenhouse returns HTML-escaped HTML in ``content``.
                description=html_to_text(html.unescape(item.get("content") or "")),
            )


class Lever(Source):
    """Jobs from a company's Lever board (https://jobs.lever.co/<company>)."""

    domain = "lever.co"
    _workplace = {"remote": REMOTE, "hybrid": HYBRID, "onsite": ONSITE, "on-site": ONSITE}

    def __init__(self, company: str) -> None:
        self.company = company
        self.name = f"lever:{company}"

    def fetch(self, fetcher: Fetcher, query: SearchQuery) -> Iterator[Job]:
        url = f"https://api.lever.co/v0/postings/{self.company}"
        for item in fetcher.get_json(url, params={"mode": "json"}):
            categories = item.get("categories") or {}
            sections = [item.get("description") or ""]
            for block in item.get("lists") or []:
                sections.append(f"<h3>{html.escape(block.get('text', ''))}</h3><ul>{block.get('content', '')}</ul>")
            sections.append(item.get("additional") or "")
            salary = item.get("salaryRange") or {}
            yield Job(
                title=item.get("text", ""),
                company=self.company,
                location=categories.get("location") or "",
                remote=self._workplace.get(str(item.get("workplaceType") or "").lower(), UNKNOWN),
                url=item.get("hostedUrl", ""),
                source=self.name,
                posted_date=_date_from_timestamp(item.get("createdAt"), millis=True),
                employment_type=categories.get("commitment") or "",
                salary=_salary(salary.get("min"), salary.get("max"), salary.get("currency", ""),
                               re.sub(r"^per-|-salary$", "", str(salary.get("interval") or "")).replace("-", " ")),
                tags=[t for t in (categories.get("team"), categories.get("department")) if t],
                description=html_to_text("".join(sections)),
            )


class Workday(Source):
    """Jobs from a Workday career site (https://<tenant>.wd<N>.myworkdayjobs.com/<site>)."""

    domain = "myworkdayjobs.com"
    page_size = 20  # the largest page size Workday accepts
    max_search_terms = 3

    def __init__(self, url: str, max_pages: int = 25) -> None:
        parts = urlsplit(url if "://" in url else f"https://{url}")
        self.host = (parts.hostname or "").lower()
        if not self.host.endswith(".myworkdayjobs.com"):
            raise ValueError(f"Not a Workday career site URL: {url!r}")
        self.tenant = self.host.split(".")[0]
        # Path is /<site> or /<locale>/<site>, optionally followed by /job/...
        segments = [s for s in parts.path.split("/") if s]
        if segments and re.fullmatch(r"[a-z]{2}(?:-[A-Z]{2})?", segments[0]):
            segments = segments[1:]
        if not segments or segments[0] in ("job", "details"):
            raise ValueError(f"Workday URL must include the career site name, e.g. "
                             f"https://{self.host}/<site>: {url!r}")
        self.site = segments[0]
        self.max_pages = max_pages
        self.name = f"workday:{self.tenant}/{self.site}"
        self.api_base = f"https://{self.host}/wday/cxs/{self.tenant}/{self.site}"

    @staticmethod
    def _remote(value: str) -> str:
        value = value.lower()
        if "hybrid" in value:
            return HYBRID
        if "remote" in value:
            return REMOTE
        if "site" in value or "office" in value:
            return ONSITE
        return UNKNOWN

    def _listing(self, fetcher: Fetcher, term: Optional[str]) -> Iterator[Dict[str, Any]]:
        total = None
        for page in range(self.max_pages):
            payload = {"appliedFacets": {}, "limit": self.page_size, "offset": page * self.page_size,
                       "searchText": term or ""}
            data = fetcher.post_json(f"{self.api_base}/jobs", payload)
            postings = data.get("jobPostings") or []
            if total is None:
                total = data.get("total") or 0  # only reliable on the first page
            yield from postings
            if not postings or (page + 1) * self.page_size >= total:
                break

    def fetch(self, fetcher: Fetcher, query: SearchQuery) -> Iterator[Job]:
        terms: List[Optional[str]] = list(query.keywords)
        if not terms or len(terms) > self.max_search_terms:
            terms = [None]
        seen = set()
        for term in terms:
            for summary in self._listing(fetcher, term):
                path = summary.get("externalPath") or ""
                if not path or path in seen:
                    continue
                seen.add(path)
                yield self._job(fetcher, summary, path)

    @staticmethod
    def _posted(info: Dict[str, Any], summary: Dict[str, Any]) -> str:
        # ``startDate`` is when the posting went live; ignore it if it lies in the future.
        start = parse_date(info.get("startDate"))
        if start is not None and start <= today_utc():
            return start.isoformat()
        return str(info.get("postedOn") or summary.get("postedOn") or "")

    def _job(self, fetcher: Fetcher, summary: Dict[str, Any], path: str) -> Job:
        try:
            detail = fetcher.get_json(f"{self.api_base}{path}")
        except (requests.RequestException, ValueError) as exc:
            log.warning("Workday detail fetch failed for %s: %s", path, exc)
            detail = {}
        info = detail.get("jobPostingInfo") or {}
        locations = [info.get("location")] + list(info.get("additionalLocations") or [])
        location = "; ".join(loc for loc in locations if loc) or summary.get("locationsText", "")
        return Job(
            title=info.get("title") or summary.get("title", ""),
            company=(detail.get("hiringOrganization") or {}).get("name") or self.tenant,
            location=location,
            remote=self._remote(str(info.get("remoteType") or summary.get("remoteType") or "")),
            url=info.get("externalUrl") or f"https://{self.host}/{self.site}{path}",
            source=self.name,
            posted_date=self._posted(info, summary),
            employment_type=info.get("timeType") or "",
            tags=[str(f) for f in summary.get("bulletFields") or []],
            description=html_to_text(info.get("jobDescription")),
        )


def is_workday_url(url: str) -> bool:
    return (urlsplit(url if "://" in url else f"https://{url}").hostname or "").lower().endswith(".myworkdayjobs.com")


# --------------------------------------------------------------------------- generic web scraping

_JOB_LINK = re.compile(
    r"/(?:jobs?|careers?|positions?|openings?|vacanc(?:y|ies)|postings?|opportunit(?:y|ies)|requisitions?)(?:[/_?-]|$)",
    re.I,
)


def _as_text(value: Any) -> str:
    """Flatten a schema.org value (string, object or list) to text."""
    if value is None:
        return ""
    if isinstance(value, list):
        return "; ".join(filter(None, (_as_text(v) for v in value)))
    if isinstance(value, dict):
        for key in ("credentialCategory", "name", "description", "value"):
            if value.get(key):
                return _as_text(value[key])
        return ""
    return str(value).strip()


def _location(value: Any) -> str:
    places = value if isinstance(value, list) else [value]
    names = []
    for place in places:
        if not place:
            continue
        address = place.get("address", place) if isinstance(place, dict) else place
        if isinstance(address, dict):
            parts = [_as_text(address.get(k)) for k in ("addressLocality", "addressRegion", "addressCountry")]
            text = ", ".join(p for p in parts if p) or _as_text(place)
        else:
            text = _as_text(address)
        if text and text not in names:
            names.append(text)
    return "; ".join(names)


def _base_salary(value: Any) -> str:
    if not isinstance(value, dict):
        return _as_text(value)
    amount = value.get("value")
    currency = _as_text(value.get("currency"))
    if isinstance(amount, dict):
        return _salary(amount.get("minValue", amount.get("value")), amount.get("maxValue"), currency,
                       _as_text(amount.get("unitText")))
    return _salary(amount, None, currency)


def _iter_jsonld(data: Any) -> Iterator[Dict[str, Any]]:
    if isinstance(data, list):
        for item in data:
            yield from _iter_jsonld(item)
    elif isinstance(data, dict):
        yield data
        if "@graph" in data:
            yield from _iter_jsonld(data["@graph"])


def _is_job_posting(obj: Dict[str, Any]) -> bool:
    types = obj.get("@type")
    types = types if isinstance(types, list) else [types]
    return "JobPosting" in types


def parse_job_postings(page_html: str, page_url: str, source: str = "") -> List[Job]:
    """Extract schema.org ``JobPosting`` objects embedded as JSON-LD in an HTML page."""
    soup = BeautifulSoup(page_html, "html.parser")
    source = source or (urlsplit(page_url).hostname or "")
    jobs: List[Job] = []
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or script.get_text() or "")
        except ValueError:
            continue
        for obj in _iter_jsonld(data):
            if not _is_job_posting(obj):
                continue
            organisation = obj.get("hiringOrganization")
            telecommute = str(obj.get("jobLocationType") or "").upper() == "TELECOMMUTE"
            education_raw = _as_text(obj.get("educationRequirements"))
            experience = obj.get("experienceRequirements")
            months = experience.get("monthsOfExperience") if isinstance(experience, dict) else None
            if months:
                experience_text = f"{float(months) / 12:g}+ years"
            else:
                experience_text = detect_experience(_as_text(experience)) or _as_text(experience)[:120]
            qualifications = html_to_text(_as_text(obj.get("qualifications")) or _as_text(obj.get("skills")))
            jobs.append(Job(
                title=html.unescape(_as_text(obj.get("title") or obj.get("name"))),
                company=html.unescape(_as_text(organisation)),
                location=_location(obj.get("jobLocation")),
                remote=REMOTE if telecommute else UNKNOWN,
                url=urljoin(page_url, _as_text(obj.get("url")) or page_url),
                source=source,
                posted_date=_as_text(obj.get("datePosted"))[:10],
                employment_type=_as_text(obj.get("employmentType")),
                salary=_base_salary(obj.get("baseSalary")),
                tags=[t for t in (_as_text(obj.get("industry")), _as_text(obj.get("occupationalCategory"))) if t],
                education=detect_education(education_raw) or education_raw[:120],
                experience=experience_text,
                requirements=qualifications.splitlines()[:15],
                description=html_to_text(_as_text(obj.get("description"))),
            ))
    return jobs


def discover_job_links(page_html: str, page_url: str, limit: int = 50) -> List[str]:
    """Return links on a careers/listing page that look like individual job pages on the same site."""
    base = urlsplit(page_url)
    site = (base.hostname or "").lower()
    site = site[4:] if site.startswith("www.") else site
    links: List[str] = []
    for anchor in BeautifulSoup(page_html, "html.parser").find_all("a", href=True):
        url = urldefrag(urljoin(page_url, anchor["href"]))[0]
        parts = urlsplit(url)
        host = (parts.hostname or "").lower()
        if parts.scheme not in ("http", "https") or not (host == site or host.endswith("." + site)):
            continue
        if url.rstrip("/") == page_url.rstrip("/") or url in links or not _JOB_LINK.search(parts.path):
            continue
        links.append(url)
        if len(links) >= limit:
            break
    return links


def parse_html_job(page_html: str, page_url: str, source: str = "") -> Optional[Job]:
    """Best-effort extraction of a single job from a page without schema.org data.

    Uses ``og:title``/``<h1>``/``<title>`` for the title and the main content block for the
    description. Returns None if the page does not look like a job posting.
    """
    soup = BeautifulSoup(page_html, "html.parser")

    def meta(*names: str) -> str:
        for name in names:
            tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
            if tag and tag.get("content"):
                return tag["content"].strip()
        return ""

    site_name = meta("og:site_name")
    host = (urlsplit(page_url).hostname or "").lower()
    host_label = (host[4:] if host.startswith("www.") else host).split(".")[0]
    h1 = soup.find("h1")
    h1_text = h1.get_text(" ", strip=True) if h1 else ""
    page_title = soup.title.get_text(" ", strip=True) if soup.title else ""
    # Prefer <title> when it is the <h1> plus extra detail such as the company name.
    title = meta("og:title") or (page_title if h1_text and h1_text in page_title else h1_text or page_title)
    # Drop a trailing " - Site Name" / " | Site Name".
    parts = re.split(r"\s+[|–—-]\s+", title)
    if len(parts) > 1 and parts[-1].strip().lower().replace(" ", "") in {site_name.lower().replace(" ", ""), host_label}:
        title = " - ".join(parts[:-1])
    company = ""
    if " : " in title:  # "Security Engineer : Acme" (NinjaJobs and others)
        title, company = (p.strip() for p in title.split(" : ", 1))
    elif re.search(r"\s+at\s+", title):
        title, company = (p.strip() for p in re.split(r"\s+at\s+", title, maxsplit=1))

    for tag in soup(["script", "style", "nav", "header", "footer", "form", "noscript"]):
        tag.decompose()
    container = (
        soup.find(attrs={"class": re.compile(r"(?:job|posting)[-_]?(?:description|details|body|content)", re.I)})
        or soup.find(attrs={"id": re.compile(r"(?:job|posting)[-_]?(?:description|details|body|content)", re.I)})
        or soup.find("article") or soup.find("main") or soup.body or soup
    )
    description = html_to_text(str(container))
    if not title or len(description) < 100:
        return None

    time_tag = soup.find("time")
    posted = meta("article:published_time", "datePosted", "date") or (
        (time_tag.get("datetime") or time_tag.get_text(" ", strip=True)) if time_tag else "")
    if not posted:
        match = re.search(r"\b(?:posted|published)\b[^\n]{0,40}", description, re.I)
        posted = match.group(0) if match else ""
    return Job(
        title=html.unescape(title),
        company=html.unescape(company or site_name),
        url=urldefrag(page_url)[0],
        source=source or host,
        posted_date=posted,
        description=description,
    )


# Links to applicant tracking systems that we have dedicated sources for.
_ATS_HOSTS = re.compile(r"(?:^|\.)(?:myworkdayjobs\.com|greenhouse\.io|lever\.co)$", re.I)


def discover_ats_links(page_html: str, page_url: str) -> List[str]:
    """Return Workday/Greenhouse/Lever board URLs linked or embedded on a careers page."""
    found: Dict[str, str] = {}
    soup = BeautifulSoup(page_html, "html.parser")
    for tag in soup.find_all(["a", "iframe", "script"]):
        ref = tag.get("href") or tag.get("src")
        if not ref:
            continue
        url = urljoin(page_url, ref)
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not _ATS_HOSTS.search(parts.hostname or ""):
            continue
        board = site_source(url)
        if board is not None and not isinstance(board, SchemaOrgSite):
            found.setdefault(board.name, url)
    return list(found.values())


class SchemaOrgSite(Source):
    """Scrape any website/domain: schema.org ``JobPosting`` data, embedded ATS boards, or plain HTML job pages.

    Each start URL may be an individual job page or a listing page. Listing pages are
    expanded by following links that look like job pages on the same site; job boards
    hosted on Workday, Greenhouse or Lever that the site links to are scraped through
    their APIs. robots.txt is always honoured.
    """

    max_depth = 2
    listing_threshold = 3  # a page with this many job links is a listing, not a posting

    def __init__(self, url: str, max_pages: int = 25, start_urls: Optional[List[str]] = None) -> None:
        self.url = url
        self.start_urls = start_urls or [url]
        self.max_pages = max_pages
        self.domain = urlsplit(url).hostname or ""
        self.name = self.domain

    def fetch(self, fetcher: Fetcher, query: SearchQuery) -> Iterator[Job]:
        queue = [(u, 0) for u in self.start_urls]
        seen = set()
        boards_done = set()
        pages = 0
        while queue and pages < self.max_pages:
            url, depth = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            if not fetcher.allowed(url):
                log.warning("robots.txt disallows %s - skipping", url)
                continue
            try:
                response = fetcher.get(url)
            except requests.RequestException as exc:
                (log.info if url in self.start_urls[1:] else log.warning)("Failed to fetch %s: %s", url, exc)
                continue
            pages += 1
            if "html" not in response.headers.get("Content-Type", "text/html"):
                continue
            page = response.text
            postings = parse_job_postings(page, url, self.name)
            if postings:
                yield from postings
                continue
            if depth == 0:
                for board_url in discover_ats_links(page, url):
                    board = site_source(board_url, self.max_pages)
                    if board is not None and board.name not in boards_done:
                        boards_done.add(board.name)
                        log.info("%s links to %s", url, board.name)
                        yield from board.fetch(fetcher, query)
            links = [link for link in discover_job_links(page, url) if link not in seen]
            if len(links) >= self.listing_threshold or (depth == 0 and links):
                if depth < self.max_depth:
                    queue.extend((link, depth + 1) for link in links)
            elif depth > 0 or not boards_done:
                job = parse_html_job(page, url, self.name)
                if job:
                    yield job


class NinjaJobs(SchemaOrgSite):
    """https://ninjajobs.org - vetted cybersecurity jobs (crawled; robots.txt honoured)."""

    name = "ninjajobs"
    domain = "ninjajobs.org"

    def __init__(self, max_pages: int = 25) -> None:
        super().__init__("https://ninjajobs.org/jobs", max_pages=max_pages,
                         start_urls=["https://ninjajobs.org/jobs", "https://ninjajobs.org/"])
        self.name = "ninjajobs"


class LinkedIn(Source):
    """https://www.linkedin.com/jobs - public (logged-out) job search; opt-in, heavily rate limited.

    Uses LinkedIn's guest job-search pages. LinkedIn's User Agreement restricts automated
    access - make sure your use is permitted, keep request volumes low and use --limit.
    """

    name = "linkedin"
    domain = "linkedin.com"
    search_url = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
    detail_url = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{id}"
    max_pages = 10
    fetch_details = True

    @staticmethod
    def _keywords(terms: List[str]) -> str:
        if len(terms) == 1:
            return terms[0]
        return " OR ".join(f'"{t}"' for t in terms)

    def _params(self, query: SearchQuery, location: Optional[str]) -> Dict[str, Any]:
        params: Dict[str, Any] = {}
        if query.keywords:
            params["keywords"] = self._keywords(query.keywords)
        if location:
            params["location"] = location
        if query.remote_only:
            params["f_WT"] = "2,3" if query.include_hybrid else "2"
        if query.posted_within_days is not None:
            params["f_TPR"] = f"r{max(1, query.posted_within_days) * 86400}"
        return params

    def fetch(self, fetcher: Fetcher, query: SearchQuery) -> Iterator[Job]:
        details_ok = self.fetch_details
        for location in query.locations or [None]:
            params = self._params(query, location)
            start = 0
            for _ in range(self.max_pages):
                try:
                    page = fetcher.get(self.search_url, params={**params, "start": start}).text
                except requests.HTTPError as exc:
                    log.warning("LinkedIn search stopped (%s); LinkedIn rate-limits guest searches", exc)
                    return
                cards = parse_linkedin_cards(page)
                if not cards:
                    break
                for job, job_id in cards:
                    if params.get("f_WT") == "2":
                        job.remote = REMOTE
                    if details_ok and job_id:
                        try:
                            apply_linkedin_detail(job, fetcher.get(self.detail_url.format(id=job_id)).text)
                        except requests.HTTPError as exc:
                            log.warning("LinkedIn job details unavailable (%s); continuing with search cards only",
                                        exc)
                            details_ok = False
                    yield job
                start += len(cards)


def _text_of(node: Any) -> str:
    return node.get_text(" ", strip=True) if node is not None else ""


def parse_linkedin_cards(page_html: str) -> List[Any]:
    """Parse LinkedIn guest search results into ``(Job, job_id)`` pairs."""
    soup = BeautifulSoup(page_html, "html.parser")
    cards = soup.select("[data-entity-urn*='jobPosting']") or soup.select(".base-card")
    results = []
    for card in cards:
        link = card.select_one("a.base-card__full-link") or card.select_one("a[href*='/jobs/view/']") or (
            card if card.name == "a" else None)
        href = link.get("href", "") if link is not None else ""
        urn = card.get("data-entity-urn", "")
        match = re.search(r"jobPosting:(\d+)", urn) or re.search(r"(?:-|/view/)(\d{6,})(?:[/?]|$)", href)
        job_id = match.group(1) if match else ""
        url = f"https://www.linkedin.com/jobs/view/{job_id}/" if job_id else href.split("?")[0]
        title = _text_of(card.select_one(".base-search-card__title"))
        if not title or not url:
            continue
        time_tag = card.select_one("time")
        results.append((Job(
            title=title,
            company=_text_of(card.select_one(".base-search-card__subtitle")),
            location=_text_of(card.select_one(".job-search-card__location")),
            url=url,
            source="linkedin",
            posted_date=(time_tag.get("datetime") or _text_of(time_tag)) if time_tag is not None else "",
            salary=_text_of(card.select_one(".job-search-card__salary-info")),
        ), job_id))
    return results


def apply_linkedin_detail(job: Job, page_html: str) -> Job:
    """Add the description and job criteria from a LinkedIn guest job page to ``job``."""
    soup = BeautifulSoup(page_html, "html.parser")
    markup = soup.select_one(".show-more-less-html__markup") or soup.select_one(".description__text")
    if markup is not None:
        job.description = html_to_text(markup.decode_contents())
    for item in soup.select(".description__job-criteria-item"):
        header = _text_of(item.select_one(".description__job-criteria-subheader")).lower()
        value = _text_of(item.select_one(".description__job-criteria-text"))
        if not value:
            continue
        if "employment type" in header:
            job.employment_type = value
        elif value not in job.tags:
            job.tags.append(value)
    return job


# --------------------------------------------------------------------------- registry

BUILTIN_SOURCES = {cls.name: cls for cls in (RemoteOK, Remotive, Arbeitnow, NinjaJobs, LinkedIn)}
DEFAULT_SOURCES = ("remoteok", "remotive", "arbeitnow")


def builtin_source(name_or_domain: str) -> Source:
    """Look up a built-in source by name (``remotive``) or domain (``remotive.com``)."""
    key = name_or_domain.lower().strip()
    if "://" in key:
        key = urlsplit(key).hostname or key
    key = key[4:] if key.startswith("www.") else key
    for cls in BUILTIN_SOURCES.values():
        if key in (cls.name, cls.domain):
            return cls()
    raise KeyError(f"Unknown source {name_or_domain!r}; choose from: {', '.join(BUILTIN_SOURCES)}")


def site_source(site: str, max_pages: int = 25) -> Optional[Source]:
    """Pick the right source for an operator-supplied domain or URL.

    Workday, Greenhouse, Lever, LinkedIn, NinjaJobs and the built-in boards are recognised
    by host name; anything else is crawled with :class:`SchemaOrgSite`.
    """
    site = site.strip()
    if not site:
        return None
    url = site if "://" in site else f"https://{site}"
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    bare = host[4:] if host.startswith("www.") else host
    segments = [s for s in parts.path.split("/") if s]
    if parts.scheme not in ("http", "https") or not host:
        raise ValueError(f"Not a valid site or URL: {site!r}")
    if host.endswith(".myworkdayjobs.com"):
        return Workday(url, max_pages=max_pages)
    if host == "greenhouse.io" or host.endswith(".greenhouse.io"):
        board = parse_qs(parts.query).get("for", [""])[0] or (
            segments[0] if segments and segments[0] != "embed" else "")
        if board:
            return Greenhouse(board)
    if (host == "lever.co" or host.endswith(".lever.co")) and segments and host != "api.lever.co":
        return Lever(segments[0])
    if bare == LinkedIn.domain or bare.endswith("." + LinkedIn.domain):
        return LinkedIn()
    if bare == NinjaJobs.domain:
        return NinjaJobs(max_pages=max_pages)
    for cls in (RemoteOK, Remotive, Arbeitnow):
        if bare == cls.domain:
            return cls()
    if not segments:
        # A bare domain: try the usual careers pages.
        root = f"{parts.scheme}://{parts.netloc}"
        return SchemaOrgSite(root + "/", max_pages=max_pages,
                             start_urls=[root + "/", root + "/careers", root + "/jobs"])
    return SchemaOrgSite(url, max_pages=max_pages)


def iter_unique(jobs: Iterable[Job]) -> Iterator[Job]:
    """Drop duplicate postings: same URL, or same title+company listed on another source."""
    seen_urls = set()
    seen_titles: Dict[str, str] = {}
    for job in jobs:
        url = job.url.rstrip("/").lower()
        title_key = f"{job.title.strip().lower()}|{job.company.strip().lower()}"
        # Title-based matching needs a company name, otherwise unrelated jobs would collide.
        cross_source_dup = bool(job.company.strip()) and seen_titles.get(title_key, job.source) != job.source
        if (url and url in seen_urls) or cross_source_dup:
            continue
        seen_urls.add(url)
        if job.company.strip():
            seen_titles.setdefault(title_key, job.source)
        yield job
