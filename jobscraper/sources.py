"""Job sources: public job-board APIs and a generic schema.org JobPosting scraper."""

from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Iterator, List, Optional
from urllib.parse import urldefrag, urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from .extract import detect_education, detect_experience, html_to_text
from .fetch import Fetcher
from .models import HYBRID, ONSITE, REMOTE, UNKNOWN, Job

log = logging.getLogger(__name__)


@dataclass
class SearchQuery:
    """Hints passed to sources that support server-side searching."""

    keywords: List[str] = field(default_factory=list)


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
            posted_date=str(info.get("startDate") or "")[:10] or str(summary.get("postedOn") or ""),
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


class SchemaOrgSite(Source):
    """Scrape any website that publishes schema.org ``JobPosting`` data (most career sites/ATSs do).

    Each start URL may be an individual job page or a listing page; for listing pages
    without embedded postings, links that look like job pages on the same site are
    followed (up to ``max_pages``). robots.txt is always honoured.
    """

    def __init__(self, url: str, max_pages: int = 25) -> None:
        self.url = url
        self.max_pages = max_pages
        self.domain = urlsplit(url).hostname or ""
        self.name = self.domain

    def fetch(self, fetcher: Fetcher, query: SearchQuery) -> Iterator[Job]:
        queue = [self.url]
        seen = set()
        pages = 0
        while queue and pages < self.max_pages:
            url = queue.pop(0)
            if url in seen:
                continue
            seen.add(url)
            if not fetcher.allowed(url):
                log.warning("robots.txt disallows %s - skipping", url)
                continue
            try:
                response = fetcher.get(url)
            except requests.RequestException as exc:
                log.warning("Failed to fetch %s: %s", url, exc)
                continue
            pages += 1
            if "html" not in response.headers.get("Content-Type", "text/html"):
                continue
            postings = parse_job_postings(response.text, url, self.name)
            yield from postings
            if not postings and url == self.url:
                queue.extend(discover_job_links(response.text, url))


# --------------------------------------------------------------------------- registry

BUILTIN_SOURCES = {cls.name: cls for cls in (RemoteOK, Remotive, Arbeitnow)}


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


def iter_unique(jobs: Iterable[Job]) -> Iterator[Job]:
    """Drop duplicate postings: same URL, or same title+company listed on another source."""
    seen_urls = set()
    seen_titles: Dict[str, str] = {}
    for job in jobs:
        url = job.url.rstrip("/").lower()
        title_key = f"{job.title.strip().lower()}|{job.company.strip().lower()}"
        if (url and url in seen_urls) or seen_titles.get(title_key, job.source) != job.source:
            continue
        seen_urls.add(url)
        seen_titles.setdefault(title_key, job.source)
        yield job
