from jobscraper.extract import (
    detect_certifications,
    detect_clearance,
    detect_education,
    detect_experience,
    detect_remote,
    enrich,
    extract_requirements,
    html_to_text,
    summarize,
)
from jobscraper.models import HYBRID, ONSITE, REMOTE, UNKNOWN, Job

DESCRIPTION_HTML = """
<p>We are hiring a <b>Security Analyst</b> to protect our cloud platform. You will monitor alerts and respond to
incidents. This is a fully remote role.</p>
<h3>Responsibilities</h3>
<ul><li>Triage SIEM alerts</li><li>Run incident response</li></ul>
<h3>Requirements</h3>
<ul>
  <li>Bachelor's degree in Computer Science or equivalent experience</li>
  <li>3+ years of security operations experience</li>
  <li>CompTIA Security+ or CISSP certification</li>
  <li>Active Secret clearance</li>
</ul>
<h3>Benefits</h3>
<ul><li>Unlimited PTO</li></ul>
"""


def test_html_to_text_keeps_inline_text_together():
    text = html_to_text(DESCRIPTION_HTML)
    assert "We are hiring a Security Analyst to protect our cloud platform." in text
    assert "Triage SIEM alerts" in text.splitlines()


def test_summarize_respects_length():
    text = html_to_text(DESCRIPTION_HTML)
    summary = summarize(text, 120)
    assert summary.startswith("We are hiring a Security Analyst")
    assert len(summary) <= 120
    assert summarize("word " * 200, 50).endswith("…")
    assert summarize("") == ""


def test_extract_requirements_section():
    reqs = extract_requirements(html_to_text(DESCRIPTION_HTML))
    assert reqs == [
        "Bachelor's degree in Computer Science or equivalent experience",
        "3+ years of security operations experience",
        "CompTIA Security+ or CISSP certification",
        "Active Secret clearance",
    ]


def test_extract_requirements_fallback_sentences():
    text = "Join our team. A degree in IT is required. We have snacks. Must have 2 years of Python experience."
    assert extract_requirements(text) == ["A degree in IT is required.", "Must have 2 years of Python experience."]


def test_detect_education():
    assert detect_education("Bachelor's degree or equivalent experience") == "Bachelor's (or equivalent experience)"
    assert detect_education("BS in CS; Master's degree preferred") == "Master's"
    assert detect_education("B.S. in CS; Master's degree preferred") == "Master's, Bachelor's"
    assert detect_education("PhD in mathematics") == "Doctorate"
    assert detect_education("A college degree is a plus") == "Degree (level unspecified)"
    assert detect_education("Scrum Master experience") == ""
    assert detect_education("No degree needed") == ""


def test_detect_certifications():
    text = "CISSP, CEH or OSCP preferred. CompTIA Security+ (DoD 8570 IAT II). AWS Certified Security. AZ-500."
    assert detect_certifications(text) == [
        "CISSP", "CEH", "OSCP", "CompTIA Security+", "AWS Certification", "Azure Certification", "DoD 8570/8140",
    ]
    assert detect_certifications("We value security and networking.") == []
    assert detect_certifications("Grade A+ customer service") == ["CompTIA A+"]


def test_detect_experience():
    assert detect_experience("3+ years of experience in security") == "3+ years"
    assert detect_experience("2-4 years relevant work experience; 5 years of Python experience") == "2-4 years; 5 years"
    assert detect_experience("Founded 10 years ago") == ""


def test_detect_clearance():
    assert detect_clearance("Must hold TS/SCI with Full Scope Polygraph") == ["TS/SCI", "Polygraph"]
    assert detect_clearance("Active Secret clearance") == ["Secret"]
    assert detect_clearance("Top Secret clearance") == ["Top Secret"]
    assert detect_clearance("Ability to obtain a security clearance") == ["Security clearance"]
    assert detect_clearance("Keep secrets safe") == []


def test_detect_remote():
    assert detect_remote(title="Security Engineer (Remote)") == REMOTE
    assert detect_remote(location="Remote - US") == REMOTE
    assert detect_remote(location="Hybrid - Austin, TX") == HYBRID
    assert detect_remote(location="Austin, TX", description="This is a fully remote role.") == REMOTE
    # "remote access" in a security description is not a remote job.
    assert detect_remote(location="Austin, TX", description="Secure remote access VPN") == UNKNOWN
    assert detect_remote(location="On-site, Denver") == ONSITE
    assert detect_remote(location="Denver", description="This is not remote.") == ONSITE


def test_enrich_fills_fields():
    job = enrich(Job(title="Security Analyst", url="https://x.test/1", description=html_to_text(DESCRIPTION_HTML)))
    assert job.remote == REMOTE
    assert job.education == "Bachelor's (or equivalent experience)"
    assert job.certifications == ["CISSP", "CompTIA Security+"]
    assert job.experience == "3+ years"
    assert job.clearance == ["Secret"]
    assert len(job.requirements) == 4
    assert job.summary.startswith("We are hiring")
