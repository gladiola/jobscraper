import pytest

from jobscraper.filters import JobFilter, domain_matches, expand_fields, keyword_pattern
from jobscraper.models import HYBRID, ONSITE, REMOTE, Job


def make_job(**kwargs):
    defaults = dict(title="Cyber Security Analyst", url="https://jobs.example.com/1", location="Remote, US",
                    remote=REMOTE, description="Full-time role.", tags=["security"])
    defaults.update(kwargs)
    return Job(**defaults)


def test_keyword_pattern_flexible_spacing():
    pattern = keyword_pattern("cyber security")
    assert pattern.search("Cybersecurity Engineer")
    assert pattern.search("cyber-security")
    assert not keyword_pattern("SOC").search("social media")


def test_expand_fields():
    terms = expand_fields(["cybersecurity"])
    assert "information security" in terms
    with pytest.raises(KeyError):
        expand_fields(["basket weaving"])


def test_domain_matches():
    assert domain_matches("https://jobs.example.com/1", "example.com")
    assert domain_matches("https://example.com/1", "https://www.example.com")
    assert not domain_matches("https://badexample.com/1", "example.com")


def test_job_filter():
    job = make_job()
    assert JobFilter(keywords=expand_fields(["cybersecurity"]), remote_only=True).matches(job)
    assert not JobFilter(keywords=["nurse"]).matches(job)
    assert JobFilter(require=["full time", "security"]).matches(job)
    assert not JobFilter(require=["part-time"]).matches(job)
    assert not JobFilter(exclude=["analyst"]).matches(job)
    assert not JobFilter(keywords=["full-time"], title_only=True).matches(job)
    assert JobFilter(domains=["example.com"]).matches(job)
    assert not JobFilter(exclude_domains=["example.com"]).matches(job)
    assert JobFilter(locations=["us"]).matches(job)
    assert not JobFilter(locations=["berlin"]).matches(job)
    assert not JobFilter(remote_only=True).matches(make_job(remote=ONSITE))
    assert not JobFilter(remote_only=True).matches(make_job(remote=HYBRID))
    assert JobFilter(remote_only=True, include_hybrid=True).matches(make_job(remote=HYBRID))


def test_posted_within_filter():
    from datetime import date
    today = date(2026, 10, 8)
    recent = JobFilter(posted_within_days=5, today=today)
    assert recent.matches(make_job(posted_date="2026-10-03"))
    assert recent.matches(make_job(posted_date="Posted 2 Days Ago"))
    assert not recent.matches(make_job(posted_date="2026-10-02"))
    assert not recent.matches(make_job(posted_date=""))
    assert JobFilter(posted_within_days=5, include_undated=True, today=today).matches(make_job(posted_date=""))
