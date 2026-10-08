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
    DEFAULT_SOURCES,
    Greenhouse,
    Lever,
    SchemaOrgSite,
    SearchQuery,
    Source,
    Workday,
    builtin_source,
    iter_unique,
    site_source,
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
    search.add_argument("--posted-within", type=int, metavar="DAYS",
                        help="only keep jobs posted within the last DAYS days, e.g. 5")
    search.add_argument("--include-undated", action="store_true",
                        help="with --posted-within, also keep jobs whose posting date is unknown")

    sites = parser.add_argument_group("sites / domains")
    sites.add_argument("--source", action="append", default=[], metavar="NAME",
                       help=f"built-in job board by name or domain: {', '.join(BUILTIN_SOURCES)}, or 'all' (includes linkedin) "
                            f"(repeatable; default: {', '.join(DEFAULT_SOURCES)} unless another site option is given)")
    sites.add_argument("--site", "--url", dest="site", action="append", default=[], metavar="DOMAIN_OR_URL",
                       help="scrape any domain or careers/job page URL you supply, e.g. example.com or "
                            "https://example.com/careers; Workday/Greenhouse/Lever/LinkedIn/NinjaJobs URLs are "
                            "detected automatically (repeatable)")
    sites.add_argument("--sites-file", action="append", default=[], metavar="FILE",
                       help="file with one domain or URL per line ('#' comments allowed) (repeatable)")
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
                       help="maximum pages to fetch per --site, or result pages of 20 jobs per --workday site "
                            "(default: %(default)s)")

    out = parser.add_argument_group("output")
    out.add_argument("-o", "--output", default="jobs.csv",
                     help="output file, '-' for stdout (default: %(default)s)")
    out.add_argument("-f", "--format", choices=FORMATS,
                     help="output format (default: from the file extension, else csv)")
    out.add_argument("--append", action="store_true",
                     help="append results to the existing output file instead of replacing it")
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


def read_sites_file(path: str) -> List[str]:
    with open(path, encoding="utf-8") as handle:
        lines = (line.split("#", 1)[0].strip() for line in handle)
        return [line for line in lines if line]


def build_sources(args: argparse.Namespace) -> List[Source]:
    names: List[str] = []
    for name in args.source:
        names.extend(BUILTIN_SOURCES if name.lower() == "all" else [name])
    sources: List[Source] = [builtin_source(name) for name in names]
    sources += [Greenhouse(board) for board in args.greenhouse]
    sources += [Lever(company) for company in args.lever]
    sources += [Workday(url, max_pages=args.max_pages) for url in args.workday]
    sites = list(args.site)
    for path in args.sites_file:
        try:
            sites += read_sites_file(path)
        except OSError as exc:
            raise ValueError(f"Cannot read --sites-file {path!r}: {exc}") from exc
    sources += [s for s in (site_source(site, args.max_pages) for site in sites) if s is not None]
    if not sources:
        sources = [builtin_source(name) for name in DEFAULT_SOURCES]
    # The same board may be given twice (e.g. --source and --site); keep the first.
    unique = {}
    for source in sources:
        unique.setdefault(source.name, source)
    return list(unique.values())


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
            default = " (default)" if cls.name in DEFAULT_SOURCES else ""
            print(f"{cls.name:<10} {cls.domain:<16} {(cls.__doc__ or '').strip().splitlines()[0]}{default}")
        print(f"{'(custom)':<10} {'--greenhouse':<16} {(Greenhouse.__doc__ or '').strip()}")
        print(f"{'(custom)':<10} {'--lever':<16} {(Lever.__doc__ or '').strip()}")
        print(f"{'(custom)':<10} {'--workday':<16} {(Workday.__doc__ or '').strip()}")
        print(f"{'(custom)':<10} {'--site':<16} {(SchemaOrgSite.__doc__ or '').strip().splitlines()[0]}")
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
    if args.posted_within is not None and args.posted_within < 0:
        parser.error("--posted-within must be zero or more days")

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
        posted_within_days=args.posted_within,
        include_undated=args.include_undated,
    )
    query = SearchQuery(keywords=keywords, locations=args.location, remote_only=args.remote,
                        include_hybrid=args.include_hybrid, posted_within_days=args.posted_within)
    fetcher = Fetcher(user_agent=args.user_agent, timeout=args.timeout, delay=args.delay)
    jobs = scrape(sources, fetcher, job_filter, query, args.limit)

    try:
        fmt = write_jobs(jobs, args.output, args.format, args.include_description, args.append)
    except (OSError, ValueError) as exc:
        log.error("Could not write output: %s", exc)
        return 1
    if args.output != "-":
        print(f"Wrote {len(jobs)} job(s) to {args.output} ({fmt})", file=sys.stderr)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
