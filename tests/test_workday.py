import pytest

from jobscraper.models import HYBRID, REMOTE
from jobscraper.sources import SearchQuery, Workday, is_workday_url

API = "https://acme.wd5.myworkdayjobs.com/wday/cxs/acme/External"


def test_workday_url_parsing():
    source = Workday("https://acme.wd5.myworkdayjobs.com/en-US/External/job/Remote/Analyst_R1")
    assert (source.tenant, source.site, source.api_base) == ("acme", "External", API)
    assert source.name == "workday:acme/External"
    assert is_workday_url("acme.wd1.myworkdayjobs.com/Careers")
    assert not is_workday_url("https://example.com/careers")
    with pytest.raises(ValueError):
        Workday("https://example.com/careers")
    with pytest.raises(ValueError):
        Workday("https://acme.wd5.myworkdayjobs.com/")


def _listing(payload):
    offset = payload["offset"]
    postings = [
        {"title": f"Job {i}", "externalPath": f"/job/Remote/Job-{i}_R{i}", "locationsText": "Remote",
         "postedOn": "Posted Today", "bulletFields": [f"R{i}"]}
        for i in range(offset, min(offset + payload["limit"], 25))
    ]
    # Like the real API, "total" is only populated on the first page.
    return {"total": 25 if offset == 0 else 0, "jobPostings": postings}


def _detail(i):
    return {
        "jobPostingInfo": {
            "title": f"Security Analyst {i}", "location": "Remote - USA", "additionalLocations": ["Austin, TX"],
            "remoteType": "Hybrid" if i == 1 else "Fully Remote", "timeType": "Full time",
            "startDate": "2026-10-01", "externalUrl": f"https://acme.wd5.myworkdayjobs.com/External/job/{i}",
            "jobDescription": "<p>Protect us.</p><h3>Qualifications</h3><ul><li>CISSP</li></ul>",
        },
        "hiringOrganization": {"name": "Acme Corp"},
    }


def test_workday_fetch_paginates_and_reads_details(make_fetcher):
    routes = {"POST " + API + "/jobs": _listing}
    routes.update({f"{API}/job/Remote/Job-{i}_R{i}": _detail(i) for i in range(25)})
    fetcher = make_fetcher(routes)
    jobs = list(Workday("https://acme.wd5.myworkdayjobs.com/External", max_pages=5).fetch(
        fetcher, SearchQuery(keywords=["security"])))
    assert len(jobs) == 25
    posts = [body for url, body in fetcher.session.calls if url.startswith("POST")]
    assert [p["offset"] for p in posts] == [0, 20]
    assert posts[0]["searchText"] == "security"
    job = jobs[1]
    assert (job.title, job.company, job.remote, job.employment_type, job.posted_date) == (
        "Security Analyst 1", "Acme Corp", HYBRID, "Full time", "2026-10-01")
    assert job.location == "Remote - USA; Austin, TX"
    assert job.url == "https://acme.wd5.myworkdayjobs.com/External/job/1"
    assert job.description.splitlines() == ["Protect us.", "Qualifications", "CISSP"]
    assert jobs[0].remote == REMOTE


def test_workday_detail_failure_falls_back_to_listing(make_fetcher):
    fetcher = make_fetcher({"POST " + API + "/jobs": {"total": 1, "jobPostings": [
        {"title": "SOC Analyst", "externalPath": "/job/X/SOC_R9", "locationsText": "Denver, CO"}]}})
    job = list(Workday("https://acme.wd5.myworkdayjobs.com/External").fetch(fetcher, SearchQuery()))[0]
    assert (job.title, job.location, job.company) == ("SOC Analyst", "Denver, CO", "acme")
    assert job.url == "https://acme.wd5.myworkdayjobs.com/External/job/X/SOC_R9"
