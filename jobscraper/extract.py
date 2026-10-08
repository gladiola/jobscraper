"""Text helpers: HTML to text, summaries, remote detection and requirement extraction."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional, Tuple

from bs4 import BeautifulSoup

from .models import HYBRID, ONSITE, REMOTE, UNKNOWN, Job

_BLOCK_TAGS = [
    "p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
    "tr", "table", "section", "article", "header", "footer", "blockquote", "pre",
]


def html_to_text(html: Optional[str]) -> str:
    """Convert an HTML fragment to plain text, keeping one line per block element."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.insert_before("\n")
        tag.insert_after("\n")
    lines = (re.sub(r"\s+", " ", line).strip() for line in soup.get_text().splitlines())
    return "\n".join(line for line in lines if line)


def summarize(text: str, max_chars: int = 300) -> str:
    """Return a short summary built from the first sentences of ``text``."""
    # Use the intro: skip short heading-like lines ("About the role", ...) and stop at the
    # first requirements/benefits/... section once some text has been collected.
    lines: List[str] = []
    for line in text.splitlines():
        if lines and _is_heading(line) and (_REQ_HEADING.match(line) or _OTHER_HEADING.match(line)):
            break
        if len(line.split()) >= 4:
            lines.append(line)
    body = " ".join(lines) if lines else " ".join(text.split())
    if not body:
        return ""
    summary = ""
    for sentence in re.split(r"(?<=[.!?])\s+", body):
        candidate = f"{summary} {sentence}".strip()
        if len(candidate) > max_chars:
            break
        summary = candidate
    if not summary:
        cut = body[:max_chars].rsplit(" ", 1)[0]
        summary = cut.rstrip(" ,;:-") + "…"
    return summary


# --------------------------------------------------------------------------- remote

_NOT_REMOTE = re.compile(r"\b(?:not|no|non)[- ]remote\b|\bon[- ]?site only\b|\bin[- ]office only\b", re.I)
_HYBRID = re.compile(r"\bhybrid\b", re.I)
_REMOTE_SHORT = re.compile(r"\bremote\b|\banywhere\b|\bwork from home\b|\bwfh\b|\btelecommut", re.I)
# Description text needs stronger phrases: "remote access" etc. is common in security jobs.
_REMOTE_LONG = re.compile(
    r"\b(?:fully|100%|completely|full[- ]time)\s+remote\b"
    r"|\bremote[- ](?:first|friendly|position|role|job|opportunity|work(?:ing)?|eligible|option)\b"
    r"|\b(?:position|role|job) is remote\b"
    r"|\bwork(?:ing)? (?:from home|remotely)\b"
    r"|\btelecommut",
    re.I,
)
_ONSITE = re.compile(r"\bon[- ]?site\b|\bin[- ]office\b|\bin[- ]person\b", re.I)


def detect_remote(title: str = "", location: str = "", description: str = "", tags: Optional[List[str]] = None) -> str:
    """Classify a posting as Remote / Hybrid / On-site / Unknown."""
    short = " ".join([title or "", location or "", " ".join(tags or [])])
    if _NOT_REMOTE.search(short) or _NOT_REMOTE.search(description or ""):
        return HYBRID if _HYBRID.search(short) else ONSITE
    if _HYBRID.search(short):
        return HYBRID
    if _REMOTE_SHORT.search(short) or _REMOTE_LONG.search(description or ""):
        return REMOTE
    if _ONSITE.search(short):
        return ONSITE
    return UNKNOWN


# --------------------------------------------------------------------------- education

_EDUCATION: List[Tuple[str, re.Pattern]] = [
    ("Doctorate", re.compile(r"\bph\.?\s?d\b|\bdoctorate\b|\bdoctoral degree\b", re.I)),
    ("Master's", re.compile(
        r"\bmaster(?:['’]?s)?\s+(?:degree|of|in)\b|\bmasters?['’]? degree\b|\bmba\b|\bm\.s\.(?=[\s,;)])|\bmsc\b", re.I)),
    ("Bachelor's", re.compile(
        r"\bbachelor(?:['’]?s)?\b|\bb\.[sa]\.(?=[\s,;)])|\bbsc\b|\bundergraduate degree\b|\b4[- ]year degree\b", re.I)),
    ("Associate's", re.compile(r"\bassociate(?:['’]?s)?\s+degree\b|\b2[- ]year degree\b", re.I)),
    ("High school diploma/GED", re.compile(r"\bhigh school (?:diploma|degree|education)\b|\bGED\b")),
]
_GENERIC_DEGREE = re.compile(
    r"\b(?:college|university|academic) degree\b|\bdegree (?:in|required)\b|\b(?:relevant|related|technical) degree\b", re.I)
_EQUIVALENT = re.compile(
    r"\bor equivalent (?:\w+ ){0,2}experience\b|\bequivalent (?:combination|experience)\b|\bin lieu of (?:a )?degree\b",
    re.I)


def detect_education(text: str) -> str:
    """Return the education levels mentioned in ``text`` (e.g. "Bachelor's, Master's")."""
    found = [name for name, pattern in _EDUCATION if pattern.search(text)]
    if not found and _GENERIC_DEGREE.search(text):
        found.append("Degree (level unspecified)")
    if not found:
        return ""
    result = ", ".join(found)
    if _EQUIVALENT.search(text):
        result += " (or equivalent experience)"
    return result


# --------------------------------------------------------------------------- certifications

_CERTS: List[Tuple[str, str]] = [
    ("CISSP", r"\bCISSP\b"),
    ("CISM", r"\bCISM\b"),
    ("CISA", r"\bCISA\b"),
    ("CRISC", r"\bCRISC\b"),
    ("CGEIT", r"\bCGEIT\b"),
    ("CCSP", r"\bCCSP\b"),
    ("SSCP", r"\bSSCP\b"),
    ("CSSLP", r"\bCSSLP\b"),
    ("CCSK", r"\bCCSK\b"),
    ("CDPSE", r"\bCDPSE\b"),
    ("CIPP", r"\bCIPP\b"),
    ("CEH", r"\bC\|?EH\b|(?i:\bcertified ethical hacker\b)"),
    ("CHFI", r"\bCHFI\b"),
    ("OSCP", r"\bOSCP\b"),
    ("OSCE", r"\bOSCE3?\b"),
    ("OSWE", r"\bOSWE\b"),
    ("OSEP", r"\bOSEP\b"),
    ("GIAC", r"\bGIAC\b"),
    ("GSEC", r"\bGSEC\b"),
    ("GCIH", r"\bGCIH\b"),
    ("GCIA", r"\bGCIA\b"),
    ("GPEN", r"\bGPEN\b"),
    ("GCFA", r"\bGCFA\b"),
    ("GCFE", r"\bGCFE\b"),
    ("GREM", r"\bGREM\b"),
    ("GWAPT", r"\bGWAPT\b"),
    ("GXPN", r"\bGXPN\b"),
    ("GICSP", r"\bGICSP\b"),
    ("CompTIA Security+", r"(?i:\bsec(?:urity)?\s?\+)"),
    ("CompTIA Network+", r"(?i:\bnet(?:work)?\s?\+)"),
    ("CompTIA A+", r"(?<![\w+])A\+(?![\w+])"),
    ("CompTIA CySA+", r"\bCySA\b"),
    ("CompTIA PenTest+", r"(?i:\bpentest\s?\+)"),
    ("CompTIA CASP+", r"\bCASP\b"),
    ("CompTIA Linux+", r"(?i:\blinux\s?\+)"),
    ("CompTIA Cloud+", r"(?i:\bcloud\s?\+)"),
    ("CCNA", r"\bCCNA\b"),
    ("CCNP", r"\bCCNP\b"),
    ("CCIE", r"\bCCIE\b"),
    ("AWS Certification", r"\bAWS[- ](?i:certifi(?:ed|cation))"),
    ("Azure Certification", r"\bAZ-\d{3}\b|\bAzure (?i:certifi(?:ed|cation))"),
    ("Google Cloud Certification", r"\b(?:Google Cloud|GCP) (?i:professional|certifi(?:ed|cation))"),
    ("CKA", r"\bCKA\b"),
    ("CKAD", r"\bCKAD\b"),
    ("CKS", r"\bCKS\b"),
    ("RHCSA", r"\bRHCSA\b"),
    ("RHCE", r"\bRHCE\b"),
    ("PMP", r"\bPMP\b"),
    ("Certified ScrumMaster", r"\bCSM\b|(?i:\bcertified scrum ?master\b)"),
    ("ITIL", r"\bITIL\b"),
    ("CPA", r"\bCPA\b"),
    ("Six Sigma", r"(?i:\bsix sigma\b)"),
    ("DoD 8570/8140", r"\b(?:DoDD? ?)?8570\b|\b(?:DoDD? ?)8140\b|\b8140\.0?3\b"),
    ("ISO 27001 Auditor/Implementer", r"\bISO\s?27001 (?i:(?:lead )?(?:auditor|implementer))"),
]
_CERT_PATTERNS = [(name, re.compile(pattern)) for name, pattern in _CERTS]


def detect_certifications(text: str) -> List[str]:
    """Return known professional certifications mentioned in ``text``."""
    return [name for name, pattern in _CERT_PATTERNS if pattern.search(text)]


# --------------------------------------------------------------------------- experience / clearance

_EXPERIENCE = re.compile(
    r"\b(\d{1,2})\s*(\+|plus)?\s*(?:(?:-|–|—|to)\s*(\d{1,2})\s*\+?\s*)?"
    r"(?:years?|yrs?)['’]?\s+(?:of\s+)?(?:[\w/&,+.-]+\s+){0,5}?(?:experience|exp)\b",
    re.I,
)


def detect_experience(text: str) -> str:
    """Return the years of experience asked for, e.g. "3+ years" or "2-4 years"."""
    found: List[str] = []
    for low, plus, high in _EXPERIENCE.findall(text):
        if high:
            value = f"{int(low)}-{int(high)} years"
        else:
            value = f"{int(low)}{'+' if plus else ''} years"
        if value not in found:
            found.append(value)
    return "; ".join(found[:3])


_CLEARANCES: List[Tuple[str, re.Pattern]] = [
    ("TS/SCI", re.compile(r"\bTS\s*/\s*SCI\b")),
    ("Top Secret", re.compile(r"\btop[- ]secret\b", re.I)),
    ("Secret", re.compile(r"(?<!top )(?<!top-)\bsecret (?:security )?clearance\b", re.I)),
    ("Public Trust", re.compile(r"\bpublic trust\b", re.I)),
    ("Polygraph", re.compile(r"\bpolygraph\b|\b(?:full[- ]scope|CI) poly\b", re.I)),
]
_GENERIC_CLEARANCE = re.compile(
    r"\b(?:security|active|government|federal|dod) clearance\b|\bclearance (?:is )?required\b"
    r"|\bability to obtain (?:and maintain )?(?:a )?clearance\b",
    re.I,
)


def detect_clearance(text: str) -> List[str]:
    """Return any government security clearances mentioned in ``text``."""
    found = [name for name, pattern in _CLEARANCES if pattern.search(text)]
    if not found and _GENERIC_CLEARANCE.search(text):
        found.append("Security clearance")
    return found


# --------------------------------------------------------------------------- requirement bullets

_REQ_HEADING = re.compile(
    r"^\W*(?:(?:minimum|basic|required|preferred|key|desired|technical|essential|job|candidate|position)\s+){0,2}"
    r"(?:requirements?|qualifications?|skills?(?:\s+(?:and|&)\s+(?:experience|qualifications))?"
    r"|experience\s+(?:and|&)\s+(?:skills|qualifications)|education(?:\s+(?:and|&)\s+experience)?"
    r"|what\s+you['’]?ll\s+need|what\s+you\s+(?:need|bring|have)|what\s+we['’]?re\s+looking\s+for"
    r"|who\s+you\s+are|about\s+you|must[- ]haves?|you\s+(?:have|should\s+have|will\s+need)|your\s+profile"
    r"|the\s+ideal\s+candidate)\W*$",
    re.I,
)
_OTHER_HEADING = re.compile(
    r"^\W*(?:benefits?|perks|what\s+we\s+offer|compensation|salary|pay\b|about\b|(?:key\s+|your\s+)?responsibilities"
    r"|what\s+you['’]?ll\s+do|duties|the\s+role|role\s+overview|how\s+to\s+apply|equal\s+(?:employment\s+)?opportunity"
    r"|why\b|our\b|nice[- ]to[- ]haves?|bonus|job\s+description|overview|who\s+we\s+are|location|apply)",
    re.I,
)
_REQ_CUE = re.compile(
    r"\b(?:required|requirements?|must (?:have|be|possess)|degree|certifi(?:ed|cation)|clearance"
    r"|years?['’]? (?:of )?(?:\w+ )?experience|proficien(?:t|cy)|experience (?:with|in))\b",
    re.I,
)


def _is_heading(line: str) -> bool:
    return len(line) <= 80 and (line.endswith(":") or (len(line.split()) <= 6 and not line.endswith(".")))


def extract_requirements(text: str, max_items: int = 15) -> List[str]:
    """Return requirement bullet points found in a job description.

    Lines under headings like "Requirements" / "Qualifications" / "What you'll need"
    are collected; if no such section exists, sentences containing requirement cue
    words (degree, certification, years of experience, ...) are used instead.
    """
    items: List[str] = []
    capturing = False
    for line in text.splitlines():
        line = line.strip(" \t•·*-–—")
        if not line:
            continue
        if _is_heading(line) and _REQ_HEADING.match(line):
            capturing = True
            continue
        if _is_heading(line) and _OTHER_HEADING.match(line):
            capturing = False
            continue
        if capturing and line not in items:
            items.append(line[:300])
            if len(items) >= max_items:
                break
    if items:
        return items

    for sentence in re.split(r"(?<=[.!?])\s+|\n", text):
        sentence = sentence.strip(" \t•·*-–—")
        if sentence and _REQ_CUE.search(sentence) and sentence not in items:
            items.append(sentence[:300])
            if len(items) >= max_items:
                break
    return items


# --------------------------------------------------------------------------- dates

_ISO_DATE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})")
_RELATIVE = re.compile(r"\b(\d+)\+?\s*(minute|min|hour|hr|day|week|wk|month|mo)s?\b\s*ago", re.I)
_DATE_FORMATS = ("%b %d, %Y", "%B %d, %Y", "%d %b %Y", "%d %B %Y", "%m/%d/%Y", "%b %d %Y", "%B %d %Y", "%Y/%m/%d")
# Dates inside longer text, e.g. "Posted Oct 5, 2026 by Acme".
_EMBEDDED_DATE = re.compile(
    r"\b[A-Z][a-z]{2,8} \d{1,2},? \d{4}\b|\b\d{1,2} [A-Z][a-z]{2,8},? \d{4}\b|\b\d{1,2}/\d{1,2}/\d{4}\b")
_UNIT_DAYS = {"minute": 0, "min": 0, "hour": 0, "hr": 0, "day": 1, "week": 7, "wk": 7, "month": 30, "mo": 30}


def today_utc() -> date:
    return datetime.now(timezone.utc).date()


def parse_date(value: object, today: Optional[date] = None) -> Optional[date]:
    """Parse ISO dates, "Oct 1, 2026", "Posted 3 Days Ago", "yesterday", "30+ days ago", ..."""
    text = str(value or "").strip()
    if not text:
        return None
    match = _ISO_DATE.search(text)
    if match:
        try:
            return date(*map(int, match.groups()))
        except ValueError:
            return None
    today = today or today_utc()
    lowered = text.lower()
    if re.search(r"\b(?:today|just (?:now|posted))\b", lowered):
        return today
    if "yesterday" in lowered:
        return today - timedelta(days=1)
    match = _RELATIVE.search(lowered)
    if match:
        return today - timedelta(days=int(match.group(1)) * _UNIT_DAYS[match.group(2).lower()])
    cleaned = re.sub(r"^(?:posted|published|date posted)\s*(?:on)?:?\s*", "", text, flags=re.I)
    cleaned = re.sub(r"(\d)(?:st|nd|rd|th)\b", r"\1", cleaned).replace(".", "")
    candidates = [cleaned] + [m.group(0) for m in _EMBEDDED_DATE.finditer(cleaned)]
    for candidate in candidates:
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(candidate.strip(), fmt).date()
            except ValueError:
                continue
    return None


def normalize_date(value: object, today: Optional[date] = None) -> str:
    """Return ``value`` as YYYY-MM-DD; unparseable values are returned unchanged."""
    parsed = parse_date(value, today)
    return parsed.isoformat() if parsed else str(value or "").strip()


def enrich(job: Job, summary_chars: int = 300) -> Job:
    """Fill in derived fields (summary, requirements, ...) from ``job.description``."""
    text = job.description or ""
    job.posted_date = normalize_date(job.posted_date)
    if not job.summary:
        job.summary = summarize(text, summary_chars)
    if not job.education:
        job.education = detect_education(text)
    if not job.certifications:
        job.certifications = detect_certifications(text)
    if not job.experience:
        job.experience = detect_experience(text)
    if not job.clearance:
        job.clearance = detect_clearance(text)
    if not job.requirements:
        job.requirements = extract_requirements(text)
    if job.remote == UNKNOWN:
        job.remote = detect_remote(job.title, job.location, text, job.tags)
    return job
