"""Command line interface: ``jobscraper`` / ``python -m jobscraper``."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Iterable, Iterator, List, Optional, Sequence

from .extract import enrich
from .fetch import DEFAULT_USER_AGENT, Fetcher
from .filters import FIELDS, JobFilter, expand_fields
from .models import Job
from .output import FORMATS, write_jobs
from .sources import (
    BUILTIN_SOURCES,
    Greenhouse,
    Lever,
    SchemaOrgSite,
    SearchQuery,
    Source,
    Workday,
    builtin_source,
    is_workday_url,
    iter_unique,
)

log = logging.getLogger("jobscraper")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="jobscraper",
        description="Search job sites and export matching postings (title, link, summary, "
                    "requirements, degrees, certifications, ...) to CSV, TSV, XLSX or JSON.",
        epilog="Example: jobscraper --field cybersecurity --remote -o jobs.xlsx",
    )
    search = parser.add_argument_group("search")
    search.add_argument("-k", "--keyword", action="append", default=[], metavar="TEXT",
                        help="match jobs mentioning any of these keywords (repeatable)")
    search.add_argument("--field", action="append", default=[], metavar="FIELD",
                        help=f"match a job field using built-in synonyms: {', '.join(FIELDS)} (repeatable)")
    search.add_argument("--require", action="append", default=[], metavar="TEXT",
                        help="only keep jobs mentioning ALL of these terms, e.g. 'full-time' (repeatable)")
    search.add_argument("--exclude", action="append", default=[], metavar="TEXT",
                        help="drop jobs mentioning any of these terms, e.g. 'senior' (repeatable)")
    search.add_argument("--title-only", action="store_true",
                        help="match keyword/field/require/exclude terms against the job title only")
    search.add_argument("--remote", action="store_true", help="only keep remote jobs")
    search.add_argument("--include-hybrid", action="store_true", help="with --remote, also keep hybrid jobs")
    search.add_argument("--location", action="append", default=[], metavar="TEXT",
                        help="only keep jobs whose location contains this text (repeatable)")

    sites = parser.add_argument_group("sites / domains")
    sites.add_argument("--source", action="append", default=[], metavar="NAME",
                       help=f"built-in job board by name or domain: {', '.join(BUILTIN_SOURCES)} (repeatable; "
                            "default: all built-in boards unless --url/--greenhouse/--lever/--workday is given)")
    sites.add_argument("--url", action="append", default=[], metavar="URL",
                       help="scrape any careers/job page that publishes schema.org JobPosting data (repeatable)")
    sites.add_argument("--greenhouse", action="append", default=[], metavar="BOARD",
                       help="company board token on boards.greenhouse.io (repeatable)")
    sites.add_argument("--lever", action="append", default=[], metavar="COMPANY",
                       help="company name on jobs.lever.co (repeatable)")
    sites.add_argument("--workday", action="append", default=[], metavar="URL",
                       help="Workday career site, e.g. https://acme.wd5.myworkdayjobs.com/External (repeatable)")
    sites.add_argument("--domain", action="append", default=[], metavar="DOMAIN",
                       help="only keep jobs whose link is on this domain or its subdomains (repeatable)")
    sites.add_argument("--exclude-domain", action="append", default=[], metavar="DOMAIN",
                       help="drop jobs whose link is on this domain (repeatable)")
    sites.add_argument("--max-pages", type=int, default=25,
                       help="maximum pages to fetch per --url, or result pages of 20 jobs per --workday site "
                            "(default: %(default)s)")

    out = parser.add_argument_group("output")
    out.add_argument("-o", "--output", default="jobs.csv",
                     help="output file, '-' for stdout (default: %(default)s)")
    out.add_argument("-f", "--format", choices=FORMATS,
                     help="output format (default: from the file extension, else csv)")
    out.add_argument("--include-description", action="store_true", help="add the full description column")
    out.add_argument("--limit", type=int, help="stop after this many matching jobs")

    net = parser.add_argument_group("network")
    net.add_argument("--delay", type=float, default=1.0,
                     help="seconds between requests to the same host (default: %(default)s)")
    net.add_argument("--timeout", type=float, default=20.0, help="request timeout in seconds (default: %(default)s)")
    net.add_argument("--user-agent", default=DEFAULT_USER_AGENT, help="User-Agent header to send")

    parser.add_argument("--list-sources", action="store_true", help="list built-in sources and exit")
    parser.add_argument("--list-fields", action="store_true", help="list --field values and their terms and exit")
    parser.add_argument("-v", "--verbose", action="store_true", help="verbose logging")
    return parser


def build_sources(args: argparse.Namespace) -> List[Source]:
    sources: List[Source] = [builtin_source(name) for name in args.source]
    sources += [Greenhouse(board) for board in args.greenhouse]
    sources += [Lever(company) for company in args.lever]
    workday_urls = args.workday + [url for url in args.url if is_workday_url(url)]
    sources += [Workday(url, max_pages=args.max_pages) for url in workday_urls]
    sources += [SchemaOrgSite(url, max_pages=args.max_pages) for url in args.url if not is_workday_url(url)]
    if not sources:
        sources = [cls() for cls in BUILTIN_SOURCES.values()]
    return sources


def _safe_fetch(source: Source, fetcher: Fetcher, query: SearchQuery) -> Iterator[Job]:
    log.info("Searching %s", source.name)
    try:
        yield from source.fetch(fetcher, query)
    except Exception as exc:  # one broken source must not abort the whole run
        log.warning("Source %s failed: %s", source.name, exc)


def scrape(sources: Sequence[Source], fetcher: Fetcher, job_filter: JobFilter,
           query: SearchQuery, limit: Optional[int] = None) -> List[Job]:
    """Fetch from every source, enrich, de-duplicate and filter jobs."""
    def all_jobs() -> Iterable[Job]:
        for source in sources:
            yield from _safe_fetch(source, fetcher, query)

    jobs: List[Job] = []
    for job in iter_unique(all_jobs()):
        if job_filter.matches(enrich(job)):
            jobs.append(job)
            if limit and len(jobs) >= limit:
                break
    return jobs


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s: %(message)s", stream=sys.stderr)

    if args.list_sources:
        for cls in BUILTIN_SOURCES.values():
            print(f"{cls.name:<10} {cls.domain:<16} {(cls.__doc__ or '').strip()}")
        print(f"{'(custom)':<10} {'--greenhouse':<16} {(Greenhouse.__doc__ or '').strip()}")
        print(f"{'(custom)':<10} {'--lever':<16} {(Lever.__doc__ or '').strip()}")
        print(f"{'(custom)':<10} {'--workday':<16} {(Workday.__doc__ or '').strip()}")
        print(f"{'(custom)':<10} {'--url':<16} {(SchemaOrgSite.__doc__ or '').strip().splitlines()[0]}")
        return 0
    if args.list_fields:
        for name, terms in FIELDS.items():
            print(f"{name}: {', '.join(terms)}")
        return 0

    try:
        sources = build_sources(args)
        keywords = args.keyword + expand_fields(args.field)
    except (KeyError, ValueError) as exc:
        parser.error(exc.args[0])
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be a positive number")

    job_filter = JobFilter(
        keywords=keywords,
        require=args.require,
        exclude=args.exclude,
        remote_only=args.remote,
        include_hybrid=args.include_hybrid,
        locations=args.location,
        domains=args.domain,
        exclude_domains=args.exclude_domain,
        title_only=args.title_only,
    )
    fetcher = Fetcher(user_agent=args.user_agent, timeout=args.timeout, delay=args.delay)
    jobs = scrape(sources, fetcher, job_filter, SearchQuery(keywords=keywords), args.limit)

    try:
        fmt = write_jobs(jobs, args.output, args.format, args.include_description)
    except (OSError, ValueError) as exc:
        log.error("Could not write output: %s", exc)
        return 1
    if args.output != "-":
        print(f"Wrote {len(jobs)} job(s) to {args.output} ({fmt})", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
