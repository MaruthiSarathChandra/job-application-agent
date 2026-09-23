import re
from pathlib import Path
from typing import Iterable, List, Tuple
from urllib.parse import urlparse

import requests
from pypdf import PdfReader

from .models import JobLead


URL_RE = re.compile(r"https?://[^\s<>\]\)\}\"']+")


def _dedupe(values: Iterable[str]) -> List[str]:
    seen = set()
    result = []
    for value in values:
        value = str(value).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def extract_urls_from_pdf(pdf_path: str) -> List[str]:
    """
    Extract both clickable annotation links and visible text URLs from a
    company-career PDF. This does not execute any link.
    """
    path = Path(pdf_path)
    if not path.exists():
        raise FileNotFoundError(path)

    reader = PdfReader(str(path))
    urls = []

    for page in reader.pages:
        annotations = page.get("/Annots") or []
        for annotation_ref in annotations:
            try:
                annotation = annotation_ref.get_object()
                action = annotation.get("/A")
                if action and action.get("/URI"):
                    urls.append(str(action.get("/URI")))
            except Exception:
                continue

        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        urls.extend(URL_RE.findall(text))

    return _dedupe(urls)


def infer_source(url: str) -> str:
    host = urlparse(url).netloc.lower()
    if "greenhouse.io" in host:
        return "greenhouse"
    if "linkedin.com" in host:
        return "linkedin"
    if "myworkdayjobs.com" in host or "workdayjobs.com" in host:
        return "workday"
    if "lever.co" in host:
        return "lever"
    return "career_site"


def leads_from_pdf(pdf_path: str, company: str = "") -> List[JobLead]:
    return [
        JobLead(
            source=infer_source(url),
            company=company,
            title="",
            url=url,
        )
        for url in extract_urls_from_pdf(pdf_path)
    ]


def greenhouse_board_token(value: str) -> str:
    """Accept a board token or a Greenhouse board URL and return the token."""
    value = value.strip().rstrip("/")
    if "/" not in value:
        return value

    parsed = urlparse(value)
    path = [part for part in parsed.path.split("/") if part]
    if not path:
        raise ValueError(f"Could not determine Greenhouse board token from {value}")

    return path[0]


def fetch_greenhouse_jobs(board: str, company: str = "", timeout: int = 20) -> List[JobLead]:
    """
    Fetch jobs from Greenhouse's public job-board endpoint. No authenticated
    scraping is used.
    """
    token = greenhouse_board_token(board)
    endpoint = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    response = requests.get(
        endpoint,
        params={"content": "true"},
        timeout=timeout,
        headers={"User-Agent": "job-application-agent/2.0"},
    )
    response.raise_for_status()
    payload = response.json()

    leads = []
    for item in payload.get("jobs", []):
        location = ""
        if isinstance(item.get("location"), dict):
            location = item["location"].get("name", "") or ""

        leads.append(
            JobLead(
                source="greenhouse",
                company=company or token,
                title=item.get("title", "") or "",
                url=item.get("absolute_url", "") or "",
                location=location,
                description=item.get("content", "") or "",
                external_id=str(item.get("id", "") or ""),
            )
        )

    return leads


def lever_site_token(value: str) -> str:
    """Accept a Lever site token or jobs.lever.co URL and return the token."""
    value = value.strip().rstrip("/")
    if "/" not in value:
        return value

    parsed = urlparse(value)
    path = [part for part in parsed.path.split("/") if part]
    if not path:
        raise ValueError(f"Could not determine Lever site token from {value}")
    return path[0]


def fetch_lever_jobs(site: str, company: str = "", timeout: int = 20) -> List[JobLead]:
    """Fetch jobs from Lever's public postings JSON endpoint."""
    token = lever_site_token(site)
    endpoint = f"https://api.lever.co/v0/postings/{token}"
    response = requests.get(
        endpoint,
        params={"mode": "json"},
        timeout=timeout,
        headers={"User-Agent": "job-application-agent/2.0"},
    )
    response.raise_for_status()
    payload = response.json()

    leads = []
    for item in payload if isinstance(payload, list) else []:
        categories = item.get("categories") or {}
        location = categories.get("location", "") if isinstance(categories, dict) else ""
        description = (
            item.get("descriptionPlain")
            or item.get("description")
            or item.get("additionalPlain")
            or ""
        )
        leads.append(
            JobLead(
                source="lever",
                company=company or token,
                title=item.get("text", "") or "",
                url=item.get("hostedUrl", "") or item.get("applyUrl", "") or "",
                location=location or "",
                description=description,
                external_id=str(item.get("id", "") or ""),
            )
        )
    return leads


def _looks_like_greenhouse_board(url: str) -> bool:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    return "greenhouse.io" in parsed.netloc.lower() and len(parts) == 1


def _looks_like_lever_board(url: str) -> bool:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    return "lever.co" in parsed.netloc.lower() and len(parts) == 1


def expand_career_urls(
    urls: Iterable[str],
    company: str = "",
    timeout: int = 20,
) -> Tuple[List[JobLead], List[dict]]:
    """
    Expand public Greenhouse/Lever board links into individual jobs. Other
    links remain queued as direct discovery leads for later browser adapters.

    Returns (jobs, errors). A failed board expansion never drops the source URL.
    """
    jobs: List[JobLead] = []
    errors = []

    for url in _dedupe(urls):
        source = infer_source(url)

        try:
            if source == "greenhouse" and _looks_like_greenhouse_board(url):
                jobs.extend(fetch_greenhouse_jobs(url, company=company, timeout=timeout))
                continue

            if source == "lever" and _looks_like_lever_board(url):
                jobs.extend(fetch_lever_jobs(url, company=company, timeout=timeout))
                continue
        except Exception as exc:
            errors.append({"url": url, "source": source, "error": str(exc)})

        jobs.append(
            JobLead(
                source=source,
                company=company,
                title="",
                url=url,
            )
        )

    # URL/external-ID dedupe is handled persistently by JobStore. This local
    # pass only removes exact URL duplicates from a single discovery operation.
    seen = set()
    unique = []
    for job in jobs:
        key = (job.source, job.external_id, job.url)
        if key in seen:
            continue
        seen.add(key)
        unique.append(job)

    return unique, errors


def expand_pdf_sources(pdf_path: str, company: str = "", timeout: int = 20):
    return expand_career_urls(
        extract_urls_from_pdf(pdf_path),
        company=company,
        timeout=timeout,
    )
