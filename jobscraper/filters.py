"""Filtering of jobs by keywords / field, work arrangement, location and domain."""

from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Dict, Iterable, List, Optional, Sequence
from urllib.parse import urlsplit

from .extract import parse_date, today_utc
from .models import HYBRID, REMOTE, Job

# Search terms used for ``--field``; each field expands to several common phrasings.
FIELDS: Dict[str, List[str]] = {
    "cybersecurity": [
        "cybersecurity", "cyber security", "cyber", "information security", "infosec", "security engineer",
        "security analyst", "security architect", "SOC", "SOC analyst", "security operations", "penetration tester",
        "penetration testing", "pentest", "application security", "appsec", "network security", "cloud security",
        "incident response", "threat intelligence", "vulnerability management", "GRC", "DevSecOps",
    ],
    "software-engineering": [
        "software engineer", "software developer", "backend", "back-end", "frontend", "front-end",
        "full stack", "fullstack", "web developer", "mobile developer",
    ],
    "data": [
        "data scientist", "data science", "data engineer", "data analyst", "machine learning", "ML engineer",
        "analytics engineer", "business intelligence",
    ],
    "devops": [
        "devops", "site reliability", "SRE", "platform engineer", "infrastructure engineer", "cloud engineer",
        "kubernetes",
    ],
    "it-support": [
        "IT support", "help desk", "helpdesk", "service desk", "desktop support", "system administrator",
        "sysadmin", "technical support",
    ],
}


def expand_fields(fields: Iterable[str]) -> List[str]:
    """Return the search terms for the given field names."""
    terms: List[str] = []
    for name in fields:
        key = name.lower().strip().replace(" ", "-").replace("_", "-")
        if key not in FIELDS:
            raise KeyError(f"Unknown field {name!r}; choose from: {', '.join(FIELDS)}")
        terms.extend(t for t in FIELDS[key] if t not in terms)
    return terms


def keyword_pattern(keyword: str) -> "re.Pattern[str]":
    """Case-insensitive whole-word pattern; spaces/hyphens in the keyword match space, hyphen or nothing."""
    parts = [re.escape(p) for p in re.split(r"[\s-]+", keyword.strip()) if p]
    body = r"[\s-]*".join(parts)
    return re.compile(rf"(?<!\w){body}(?!\w)", re.I)


def domain_matches(url: str, domain: str) -> bool:
    """True if ``url``'s host is ``domain`` or one of its subdomains."""
    domain = domain.strip().lower()
    if "://" in domain:
        domain = urlsplit(domain).hostname or ""
    domain = domain.strip(".")
    if domain.startswith("www."):
        domain = domain[4:]
    host = (urlsplit(url).hostname or "").lower()
    return bool(domain) and (host == domain or host.endswith("." + domain))


class JobFilter:
    """Decide whether a job matches the user's search criteria."""

    def __init__(
        self,
        keywords: Sequence[str] = (),
        require: Sequence[str] = (),
        exclude: Sequence[str] = (),
        remote_only: bool = False,
        include_hybrid: bool = False,
        locations: Sequence[str] = (),
        domains: Sequence[str] = (),
        exclude_domains: Sequence[str] = (),
        title_only: bool = False,
        posted_within_days: Optional[int] = None,
        include_undated: bool = False,
        today: Optional[date] = None,
    ) -> None:
        self.keywords = [keyword_pattern(k) for k in keywords if k.strip()]
        self.require = [keyword_pattern(k) for k in require if k.strip()]
        self.exclude = [keyword_pattern(k) for k in exclude if k.strip()]
        self.remote_only = remote_only
        self.include_hybrid = include_hybrid
        self.locations = [loc.lower() for loc in locations if loc.strip()]
        self.domains = list(domains)
        self.exclude_domains = list(exclude_domains)
        self.title_only = title_only
        self.include_undated = include_undated
        self.cutoff: Optional[date] = None
        if posted_within_days is not None:
            self.cutoff = (today or today_utc()) - timedelta(days=posted_within_days)

    def _search_text(self, job: Job) -> str:
        if self.title_only:
            return job.title
        return "\n".join([job.title, " ".join(job.tags), job.description])

    def matches(self, job: Job, text: Optional[str] = None) -> bool:
        if self.remote_only:
            allowed = {REMOTE, HYBRID} if self.include_hybrid else {REMOTE}
            if job.remote not in allowed:
                return False
        if self.cutoff is not None:
            posted = parse_date(job.posted_date)
            if posted is None:
                if not self.include_undated:
                    return False
            elif posted < self.cutoff:
                return False
        if self.locations and not any(loc in job.location.lower() for loc in self.locations):
            return False
        if self.domains and not any(domain_matches(job.url, d) for d in self.domains):
            return False
        if any(domain_matches(job.url, d) for d in self.exclude_domains):
            return False
        text = self._search_text(job) if text is None else text
        if self.keywords and not any(p.search(text) for p in self.keywords):
            return False
        if not all(p.search(text) for p in self.require):
            return False
        if any(p.search(text) for p in self.exclude):
            return False
        return True
