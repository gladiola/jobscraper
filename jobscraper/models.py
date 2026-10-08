"""Data model for scraped job postings."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

# Work arrangement values used in ``Job.remote``.
REMOTE = "Remote"
HYBRID = "Hybrid"
ONSITE = "On-site"
UNKNOWN = "Unknown"


@dataclass
class Job:
    """A single job posting, normalised across all sources."""

    title: str
    url: str
    company: str = ""
    location: str = ""
    remote: str = UNKNOWN
    source: str = ""
    posted_date: str = ""
    employment_type: str = ""
    salary: str = ""
    tags: List[str] = field(default_factory=list)
    summary: str = ""
    education: str = ""
    certifications: List[str] = field(default_factory=list)
    experience: str = ""
    clearance: List[str] = field(default_factory=list)
    requirements: List[str] = field(default_factory=list)
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# Column order used for tabular output (CSV/TSV/XLSX).
COLUMNS = [
    "title",
    "company",
    "location",
    "remote",
    "url",
    "source",
    "posted_date",
    "employment_type",
    "salary",
    "tags",
    "summary",
    "education",
    "certifications",
    "experience",
    "clearance",
    "requirements",
]
