import json

from jobscraper.models import HYBRID, REMOTE, UNKNOWN
from jobscraper.sources import (
    Arbeitnow,
    Greenhouse,
    Lever,
    RemoteOK,
    Remotive,
    SchemaOrgSite,
    SearchQuery,
    builtin_source,
    discover_job_links,
    iter_unique,
    parse_job_postings,
)
from jobscraper.models import Job

from conftest import FakeResponse


def test_remoteok_skips_legal_notice(make_fetcher):
    fetcher = make_fetcher({"https://remoteok.com/api": [
        {"legal": "API terms"},
        {"id": "1", "position": "Security Engineer", "company": "Acme", "location": "Worldwide",
         "url": "https://remoteok.com/remote-jobs/1", "date": "2026-10-01T00:00:00+00:00",
         "salary_min": 100000, "salary_max": 150000, "tags": ["security"], "description": "<p>Protect things.</p>"},
    ]})
    jobs = list(RemoteOK().fetch(fetcher, SearchQuery()))
    assert len(jobs) == 1
    job = jobs[0]
    assert (job.title, job.company, job.remote, job.posted_date) == ("Security Engineer", "Acme", REMOTE, "2026-10-01")
    assert job.salary == "USD 100,000-150,000"
    assert job.description == "Protect things."


def test_remotive_searches_each_keyword(make_fetcher):
    def route(params):
        return {"jobs": [{"title": f"{params['search']} job", "company_name": "Co",
                          "url": f"https://remotive.com/{params['search']}", "category": "Security",
                          "job_type": "full_time", "candidate_required_location": "USA"}]}

    fetcher = make_fetcher({"https://remotive.com/api/remote-jobs": route})
    jobs = list(Remotive().fetch(fetcher, SearchQuery(keywords=["soc", "pentest"])))
    assert [j.title for j in jobs] == ["soc job", "pentest job"]
    assert jobs[0].employment_type == "Full Time"
    assert jobs[0].tags == ["Security"]


def test_remotive_many_keywords_single_request(make_fetcher):
    fetcher = make_fetcher({"https://remotive.com/api/remote-jobs": {"jobs": []}})
    list(Remotive().fetch(fetcher, SearchQuery(keywords=["a", "b", "c", "d"])))
    assert fetcher.session.calls == [("https://remotive.com/api/remote-jobs", None)]


def test_arbeitnow_paginates(make_fetcher):
    def route(params):
        page = params["page"]
        return {"data": [{"title": f"Job {page}", "company_name": "Co", "url": f"https://www.arbeitnow.com/{page}",
                          "remote": page == 1, "created_at": 1790000000, "job_types": ["full time"]}],
                "links": {"next": "more" if page == 1 else None}}

    fetcher = make_fetcher({"https://www.arbeitnow.com/api/job-board-api": route})
    jobs = list(Arbeitnow().fetch(fetcher, SearchQuery()))
    assert [j.title for j in jobs] == ["Job 1", "Job 2"]
    assert [j.remote for j in jobs] == [REMOTE, UNKNOWN]
    assert jobs[0].posted_date == "2026-09-21"


def test_greenhouse_unescapes_content(make_fetcher):
    fetcher = make_fetcher({"https://boards-api.greenhouse.io/v1/boards/acme/jobs": {"jobs": [
        {"title": "AppSec Engineer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
         "location": {"name": "Remote, US"}, "updated_at": "2026-09-30T10:00:00-04:00",
         "departments": [{"name": "Security"}], "content": "&lt;p&gt;Secure our apps.&lt;/p&gt;"},
    ]}})
    job = list(Greenhouse("acme").fetch(fetcher, SearchQuery()))[0]
    assert job.description == "Secure our apps."
    assert (job.location, job.source, job.tags, job.posted_date) == (
        "Remote, US", "greenhouse:acme", ["Security"], "2026-09-30")
    assert fetcher.session.calls[0][1] == {"content": "true"}


def test_lever_builds_description_from_lists(make_fetcher):
    fetcher = make_fetcher({"https://api.lever.co/v0/postings/acme": [
        {"text": "Pen Tester", "hostedUrl": "https://jobs.lever.co/acme/1", "workplaceType": "hybrid",
         "categories": {"location": "Boston", "commitment": "Full-time", "team": "Security"},
         "createdAt": 1790000000000, "description": "<p>Break things.</p>",
         "lists": [{"text": "Requirements", "content": "<li>OSCP</li><li>2+ years of pentest experience</li>"}],
         "salaryRange": {"min": 90000, "max": 120000, "currency": "USD", "interval": "per-year-salary"}},
    ]})
    job = list(Lever("acme").fetch(fetcher, SearchQuery()))[0]
    assert job.remote == HYBRID
    assert job.description.splitlines() == ["Break things.", "Requirements", "OSCP", "2+ years of pentest experience"]
    assert job.salary == "USD 90,000-120,000 per year"
    assert job.employment_type == "Full-time"


JOB_PAGE = """<html><head><script type="application/ld+json">{json}</script></head><body>Job</body></html>"""
POSTING = {
    "@context": "https://schema.org", "@type": "JobPosting", "title": "Cyber Analyst",
    "hiringOrganization": {"@type": "Organization", "name": "Gov Co"},
    "jobLocation": {"@type": "Place", "address": {"addressLocality": "Reston", "addressRegion": "VA",
                                                  "addressCountry": {"name": "US"}}},
    "jobLocationType": "TELECOMMUTE", "datePosted": "2026-09-01", "employmentType": ["FULL_TIME"],
    "baseSalary": {"currency": "USD", "value": {"minValue": 80000, "maxValue": 95000, "unitText": "YEAR"}},
    "educationRequirements": {"@type": "EducationalOccupationalCredential", "credentialCategory": "bachelor degree"},
    "experienceRequirements": {"monthsOfExperience": 36},
    "description": "<p>Defend networks. TS/SCI required. CISSP preferred.</p>",
}


def test_parse_job_postings_jsonld():
    page = JOB_PAGE.format(json=json.dumps({"@graph": [{"@type": "WebPage"}, POSTING]}))
    jobs = parse_job_postings(page, "https://careers.gov.test/job/1")
    assert len(jobs) == 1
    job = jobs[0]
    assert (job.title, job.company, job.location, job.remote) == ("Cyber Analyst", "Gov Co", "Reston, VA, US", REMOTE)
    assert job.url == "https://careers.gov.test/job/1"
    assert job.salary == "USD 80,000-95,000 per year"
    assert job.education == "Bachelor's"
    assert job.experience == "3+ years"
    assert job.employment_type == "FULL_TIME"
    assert job.source == "careers.gov.test"
    assert parse_job_postings("<script type='application/ld+json'>{bad json</script>", "https://x.test") == []


def test_discover_job_links_same_site_only():
    page = """
      <a href="/jobs/123">One</a><a href="https://jobs.example.com/positions/9#apply">Two</a>
      <a href="https://other.test/jobs/1">Other</a><a href="/about">About</a><a href="mailto:x@example.com">M</a>
      <a href="/jobs/123">Dup</a>
    """
    assert discover_job_links(page, "https://www.example.com/careers") == [
        "https://www.example.com/jobs/123", "https://jobs.example.com/positions/9"]


def test_schema_org_site_follows_links_and_respects_robots(make_fetcher):
    posting_page = JOB_PAGE.format(json=json.dumps(POSTING))
    fetcher = make_fetcher({
        "https://example.com/robots.txt": FakeResponse("User-agent: *\nDisallow: /jobs/private"),
        "https://example.com/careers": '<a href="/jobs/1">1</a><a href="/jobs/private">2</a>',
        "https://example.com/jobs/1": posting_page,
        "https://example.com/jobs/private": posting_page,
    })
    jobs = list(SchemaOrgSite("https://example.com/careers").fetch(fetcher, SearchQuery()))
    assert [j.url for j in jobs] == ["https://example.com/jobs/1"]
    fetched = [url for url, _ in fetcher.session.calls]
    assert "https://example.com/jobs/private" not in fetched


def test_builtin_source_lookup():
    assert isinstance(builtin_source("remotive"), Remotive)
    assert isinstance(builtin_source("https://www.remoteok.com"), RemoteOK)
    assert isinstance(builtin_source("arbeitnow.com"), Arbeitnow)


def test_iter_unique():
    jobs = [
        Job(title="A", company="X", url="https://a.test/1", source="s1"),
        Job(title="A", company="X", url="https://a.test/1/", source="s1"),
        Job(title="A", company="X", url="https://a.test/2", source="s1"),
        Job(title="A", company="X", url="https://b.test/9", source="s2"),
    ]
    assert [j.url for j in iter_unique(jobs)] == ["https://a.test/1", "https://a.test/2"]
    no_company = [Job(title="Analyst", url="https://a.test/1", source="s1"),
                  Job(title="Analyst", url="https://b.test/2", source="s2")]
    assert len(list(iter_unique(no_company))) == 2
