import csv
from datetime import datetime, timedelta, timezone

import pytest

from jobscraper import cli
from jobscraper.sources import Arbeitnow, Greenhouse, RemoteOK, Remotive, SchemaOrgSite, Workday
from jobscraper.fetch import Fetcher

from conftest import FakeSession

ROUTES = {
    "https://remoteok.com/api": [
        {"legal": "terms"},
        {"position": "Senior Security Engineer", "company": "A", "url": "https://remoteok.com/1",
         "description": "<h3>Requirements</h3><ul><li>CISSP required</li><li>5+ years of security experience</li></ul>"},
        {"position": "Marketing Manager", "company": "B", "url": "https://remoteok.com/2", "description": "Sell."},
    ],
    "https://remotive.com/api/remote-jobs": {"jobs": [
        {"title": "SOC Analyst", "company_name": "C", "url": "https://remotive.com/3",
         "publication_date": (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
         "description": "<p>Monitor alerts. Bachelor's degree required.</p>"},
    ]},
    "https://www.arbeitnow.com/api/job-board-api": RuntimeError,  # broken source must not stop the run
}


@pytest.fixture
def fake_network(monkeypatch):
    def route(url):
        value = ROUTES.get(url)
        if value is RuntimeError:
            raise RuntimeError("boom")
        return value

    class Session(FakeSession):
        def get(self, url, params=None, timeout=None):
            route(url)
            return super().get(url, params, timeout)

    original = Fetcher.__init__

    def init(self, session=None, **kwargs):
        original(self, session=Session(ROUTES), **{**kwargs, "delay": 0})

    monkeypatch.setattr(Fetcher, "__init__", init)


def test_build_sources():
    parser = cli.build_parser()
    default = cli.build_sources(parser.parse_args([]))
    assert [type(s) for s in default] == [RemoteOK, Remotive, Arbeitnow]
    args = parser.parse_args(["--source", "remotive.com", "--greenhouse", "acme", "--url", "https://x.test/careers",
                              "--url", "https://acme.wd1.myworkdayjobs.com/Ext", "--workday",
                              "https://b.wd5.myworkdayjobs.com/Jobs"])
    assert [type(s) for s in cli.build_sources(args)] == [Remotive, Greenhouse, Workday, SchemaOrgSite, Workday]
    every = cli.build_sources(parser.parse_args(["--source", "all", "--site", "linkedin.com"]))
    assert [s.name for s in every] == ["remoteok", "remotive", "arbeitnow", "ninjajobs", "linkedin"]


def test_sites_file(tmp_path):
    sites = tmp_path / "sites.txt"
    sites.write_text("# my targets\nexample.com\n\nhttps://jobs.lever.co/acme  # lever board\nninjajobs.org\n")
    args = cli.build_parser().parse_args(["--sites-file", str(sites)])
    assert [s.name for s in cli.build_sources(args)] == ["example.com", "lever:acme", "ninjajobs"]
    with pytest.raises(SystemExit):
        cli.main(["--sites-file", str(tmp_path / "missing.txt")])


def test_cli_end_to_end(fake_network, tmp_path, capsys):
    out = tmp_path / "jobs.csv"
    assert cli.main(["--field", "cybersecurity", "--remote", "-o", str(out)]) == 0
    rows = list(csv.DictReader(out.open(encoding="utf-8-sig")))
    assert [r["title"] for r in rows] == ["Senior Security Engineer", "SOC Analyst"]
    assert rows[0]["certifications"] == "CISSP"
    assert rows[0]["experience"] == "5+ years"
    assert rows[0]["requirements"] == "CISSP required | 5+ years of security experience"
    assert rows[1]["education"] == "Bachelor's"
    assert "Wrote 2 job(s)" in capsys.readouterr().err


def test_cli_append(fake_network, tmp_path):
    out = tmp_path / "jobs.csv"
    args = ["--field", "cybersecurity", "-o", str(out)]
    assert cli.main(args) == 0
    assert cli.main(args + ["--append"]) == 0
    assert len(list(csv.DictReader(out.open(encoding="utf-8-sig")))) == 4


def test_cli_posted_within(fake_network, tmp_path):
    out = tmp_path / "jobs.csv"
    assert cli.main(["--field", "cybersecurity", "--posted-within", "5", "-o", str(out)]) == 0
    assert [r["title"] for r in csv.DictReader(out.open(encoding="utf-8-sig"))] == ["SOC Analyst"]
    assert cli.main(["--field", "cybersecurity", "--posted-within", "5", "--include-undated", "-o", str(out)]) == 0
    assert len(list(csv.DictReader(out.open(encoding="utf-8-sig")))) == 2


def test_cli_exclude_domain_and_limit(fake_network, tmp_path):
    out = tmp_path / "jobs.json"
    assert cli.main(["-k", "security", "-k", "soc", "--exclude", "senior", "--limit", "1", "-o", str(out)]) == 0
    assert '"SOC Analyst"' in out.read_text()
    assert cli.main(["--field", "cybersecurity", "--exclude-domain", "remoteok.com", "-o", str(out)]) == 0
    assert "remoteok.com" not in out.read_text()


def test_cli_rejects_unknown_source():
    with pytest.raises(SystemExit):
        cli.main(["--source", "nope"])
    with pytest.raises(SystemExit):
        cli.main(["--workday", "https://example.com/careers"])
