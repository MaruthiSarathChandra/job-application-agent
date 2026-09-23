from __future__ import annotations

from urllib.parse import urlparse


ATS_GREENHOUSE = "greenhouse"
ATS_WORKDAY = "workday"
ATS_LEVER = "lever"
ATS_LINKEDIN = "linkedin"
ATS_BRASSRING = "brassring"
ATS_CAREER_SITE = "career_site"


def detect_ats(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ATS_CAREER_SITE

    parsed = urlparse(value)
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    if "greenhouse.io" in host:
        return ATS_GREENHOUSE

    if "myworkdayjobs.com" in host or "workdayjobs.com" in host:
        return ATS_WORKDAY

    if "lever.co" in host or "jobs.lever.co" in host:
        return ATS_LEVER

    if "brassring.com" in host or "sjobs.brassring.com" in host:
        return ATS_BRASSRING

    if "linkedin.com" in host:
        return ATS_LINKEDIN

    # Some employers proxy an ATS through a branded hostname. These path
    # signatures are intentionally conservative and only used for routing.
    if "/greenhouse/" in path or "/boards/" in path and "greenhouse" in value.lower():
        return ATS_GREENHOUSE

    if "/job/" in path and "workday" in value.lower():
        return ATS_WORKDAY

    if "tgnewui" in path and "jobdetails" in value.lower():
        return ATS_BRASSRING

    return ATS_CAREER_SITE


def is_direct_application_target(url: str) -> bool:
    return detect_ats(url) in {
        ATS_GREENHOUSE,
        ATS_WORKDAY,
        ATS_LEVER,
        ATS_BRASSRING,
    }
