"""LinkedIn, NinjaJobs, operator-supplied domains and the plain-HTML fallback."""

from jobscraper.models import REMOTE
from jobscraper.sources import (
    Greenhouse,
    Lever,
    LinkedIn,
    NinjaJobs,
    RemoteOK,
    SchemaOrgSite,
    SearchQuery,
    Workday,
    discover_ats_links,
    parse_html_job,
    site_source,
)

from conftest import FakeResponse

LINKEDIN_SEARCH = "https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
LINKEDIN_CARDS = """
<li><div class="base-card job-search-card" data-entity-urn="urn:li:jobPosting:4012345678">
  <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/soc-analyst-at-acme-4012345678?trk=x"></a>
  <h3 class="base-search-card__title"> SOC Analyst </h3>
  <h4 class="base-search-card__subtitle"><a>Acme</a></h4>
  <span class="job-search-card__location">United States (Remote)</span>
  <time class="job-search-card__listdate" datetime="2026-10-06">2 days ago</time>
</div></li>
"""
LINKEDIN_DETAIL = """
<div class="show-more-less-html__markup"><p>Watch the SIEM.</p><strong>Requirements</strong>
<ul><li>Security+ certification</li></ul></div>
<ul><li class="description__job-criteria-item"><h3 class="description__job-criteria-subheader">Seniority level</h3>
<span class="description__job-criteria-text">Entry level</span></li>
<li class="description__job-criteria-item"><h3 class="description__job-criteria-subheader">Employment type</h3>
<span class="description__job-criteria-text">Full-time</span></li></ul>
"""


def test_linkedin_search_and_details(make_fetcher):
    def search(params):
        return FakeResponse(LINKEDIN_CARDS if params["start"] == 0 else "")

    fetcher = make_fetcher({LINKEDIN_SEARCH: search,
                            "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/4012345678": LINKEDIN_DETAIL})
    query = SearchQuery(keywords=["cybersecurity", "SOC analyst"], locations=["United States"], remote_only=True,
                        posted_within_days=5)
    jobs = list(LinkedIn().fetch(fetcher, query))
    assert len(jobs) == 1
    job = jobs[0]
    assert (job.title, job.company, job.location, job.posted_date, job.remote) == (
        "SOC Analyst", "Acme", "United States (Remote)", "2026-10-06", REMOTE)
    assert job.url == "https://www.linkedin.com/jobs/view/4012345678/"
    assert job.employment_type == "Full-time" and job.tags == ["Entry level"]
    assert "Security+ certification" in job.description
    params = fetcher.session.calls[0][1]
    assert params == {"keywords": '"cybersecurity" OR "SOC analyst"', "location": "United States", "f_WT": "2",
                      "f_TPR": "r432000", "start": 0}


def test_linkedin_rate_limit_stops_cleanly(make_fetcher):
    fetcher = make_fetcher({LINKEDIN_SEARCH: FakeResponse("slow down", status=429)})
    assert list(LinkedIn().fetch(fetcher, SearchQuery())) == []


NINJA_LISTING = "".join(f'<a href="/job/abc{i}">Job {i}</a>' for i in range(3))
NINJA_JOB = """<html><head><title>Senior Security Engineer : Axios - NinjaJobs</title></head><body>
<nav>Home Jobs Post a job</nav><h1>Senior Security Engineer</h1>
<div class="job-description"><p>Posted Oct 5, 2026</p><p>Axios is looking for a security engineer to defend our cloud.
You will build detections and lead incident response for a fast moving newsroom.</p>
<h3>Requirements</h3><ul><li>5+ years of security experience</li><li>OSCP or GPEN</li></ul></div></body></html>"""


def test_ninjajobs_crawls_job_pages(make_fetcher):
    routes = {"https://ninjajobs.org/robots.txt": FakeResponse("", status=404),
              "https://ninjajobs.org/jobs": NINJA_LISTING}
    routes.update({f"https://ninjajobs.org/job/abc{i}": NINJA_JOB for i in range(3)})
    jobs = list(NinjaJobs().fetch(make_fetcher(routes), SearchQuery()))
    assert len(jobs) == 3
    job = jobs[0]
    assert (job.title, job.company, job.source) == ("Senior Security Engineer", "Axios", "ninjajobs")
    assert job.url == "https://ninjajobs.org/job/abc0"
    assert "Posted Oct 5, 2026" in job.posted_date
    assert "Home Jobs" not in job.description


def test_parse_html_job_rejects_thin_pages():
    assert parse_html_job("<h1>Careers</h1><p>Join us!</p>", "https://x.test/careers") is None


def test_site_source_routing():
    assert isinstance(site_source("acme.wd5.myworkdayjobs.com/External"), Workday)
    assert isinstance(site_source("https://boards.greenhouse.io/acme"), Greenhouse)
    assert site_source("https://boards.greenhouse.io/embed/job_board/js?for=acme").board == "acme"
    assert isinstance(site_source("https://jobs.lever.co/acme/123"), Lever)
    assert isinstance(site_source("https://www.linkedin.com/jobs"), LinkedIn)
    assert isinstance(site_source("ninjajobs.org"), NinjaJobs)
    assert isinstance(site_source("remoteok.com"), RemoteOK)
    bare = site_source("example.com")
    assert isinstance(bare, SchemaOrgSite)
    assert bare.start_urls == ["https://example.com/", "https://example.com/careers", "https://example.com/jobs"]
    assert site_source("https://example.com/careers/openings").start_urls == ["https://example.com/careers/openings"]
    assert site_source("  ") is None


def test_discover_ats_links():
    page = """<a href="https://boards.greenhouse.io/acme">Jobs</a><a href="https://boards.greenhouse.io/acme/jobs/1">x</a>
              <iframe src="https://acme.wd1.myworkdayjobs.com/en-US/Careers"></iframe><a href="https://lever.co">no</a>"""
    assert discover_ats_links(page, "https://acme.test/careers") == [
        "https://boards.greenhouse.io/acme", "https://acme.wd1.myworkdayjobs.com/en-US/Careers"]


def test_operator_domain_delegates_to_ats(make_fetcher):
    fetcher = make_fetcher({
        "https://acme.test/": '<a href="https://boards.greenhouse.io/acme">Open roles</a>',
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs": {"jobs": [
            {"title": "Red Teamer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/7", "content": ""}]},
    })
    jobs = list(site_source("acme.test").fetch(fetcher, SearchQuery()))
    assert [j.title for j in jobs] == ["Red Teamer"]
    fetched = [url for url, _ in fetcher.session.calls]
    assert "https://acme.test/careers" in fetched  # other candidate pages still tried
