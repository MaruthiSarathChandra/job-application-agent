import re
from pathlib import Path
from typing import Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import requests
from pypdf import PdfReader

from .models import JobLead


URL_RE = re.compile(r"https?://[^\s<>\]\)\}\"']+")
LOCALE_RE = re.compile(r"^[a-z]{2}-[A-Z]{2}$")
USER_AGENT = "job-application-agent/2.0"


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
    """Extract clickable annotation links and visible text URLs from a PDF."""
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
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if "greenhouse.io" in host:
        return "greenhouse"
    if "linkedin.com" in host:
        return "linkedin"
    if "myworkdayjobs.com" in host or "workdayjobs.com" in host:
        return "workday"
    if "lever.co" in host:
        return "lever"
    if "brassring.com" in host:
        return "brassring"
    if "avature.net" in host or host.endswith("metlifecareers.com"):
        return "avature"
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
    value = value.strip().rstrip("/")
    if "/" not in value:
        return value

    parsed = urlparse(value)
    path = [part for part in parsed.path.split("/") if part]
    if not path:
        raise ValueError(f"Could not determine Greenhouse board token from {value}")
    return path[0]


def fetch_greenhouse_jobs(board: str, company: str = "", timeout: int = 20) -> List[JobLead]:
    token = greenhouse_board_token(board)
    endpoint = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs"
    response = requests.get(
        endpoint,
        params={"content": "true"},
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
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
    value = value.strip().rstrip("/")
    if "/" not in value:
        return value

    parsed = urlparse(value)
    path = [part for part in parsed.path.split("/") if part]
    if not path:
        raise ValueError(f"Could not determine Lever site token from {value}")
    return path[0]


def fetch_lever_jobs(site: str, company: str = "", timeout: int = 20) -> List[JobLead]:
    token = lever_site_token(site)
    endpoint = f"https://api.lever.co/v0/postings/{token}"
    response = requests.get(
        endpoint,
        params={"mode": "json"},
        timeout=timeout,
        headers={"User-Agent": USER_AGENT},
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


def workday_board_parts(value: str):
    """
    Parse a public myworkdayjobs career URL into host, tenant, site and locale.

    Examples accepted:
      https://statestreet.wd1.myworkdayjobs.com/Global
      https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite
      https://.../Global/job/City/Role_REQ123
    """
    parsed = urlparse((value or "").strip())
    host = parsed.netloc.lower()
    if not host or not (
        "myworkdayjobs.com" in host or "workdayjobs.com" in host
    ):
        raise ValueError(f"Not a Workday career URL: {value}")

    tenant = host.split(".")[0]
    parts = [part for part in parsed.path.split("/") if part]
    locale = "en-US"
    if parts and LOCALE_RE.match(parts[0]):
        locale = parts.pop(0)
    if not parts:
        raise ValueError(f"Could not determine Workday career site from {value}")

    site = parts[0]
    remainder = parts[1:]
    return host, tenant, site, locale, remainder


def _workday_public_url(host: str, site: str, locale: str, external_path: str) -> str:
    external = "/" + str(external_path or "").lstrip("/")
    return f"https://{host}/{locale}/{site}{external}"


def _workday_detail(
    session: requests.Session,
    host: str,
    tenant: str,
    site: str,
    external_path: str,
    timeout: int,
):
    external = "/" + str(external_path or "").lstrip("/")
    endpoint = f"https://{host}/wday/cxs/{tenant}/{site}{external}"
    response = session.get(endpoint, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    info = payload.get("jobPostingInfo") or {}
    return info if isinstance(info, dict) else {}


def fetch_workday_job(url: str, company: str = "", timeout: int = 20) -> JobLead:
    host, tenant, site, locale, remainder = workday_board_parts(url)
    if not remainder or remainder[0].lower() != "job":
        raise ValueError(f"Workday URL is not a direct job posting: {url}")

    external_path = "/" + "/".join(remainder)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    info = _workday_detail(
        session,
        host,
        tenant,
        site,
        external_path,
        timeout,
    )

    return JobLead(
        source="workday",
        company=company or tenant,
        title=str(info.get("title") or ""),
        url=url,
        location=str(info.get("location") or info.get("locationsText") or ""),
        description=str(info.get("jobDescription") or ""),
        external_id=str(info.get("jobReqId") or external_path),
    )


def fetch_workday_jobs(
    board: str,
    company: str = "",
    timeout: int = 20,
    search_text: str = "",
    max_jobs: int = 200,
    include_descriptions: bool = True,
) -> List[JobLead]:
    """
    Fetch public jobs from Workday's candidate-experience JSON endpoint.

    The endpoint is unauthenticated but undocumented, so failures are surfaced to
    the caller and never treated as an empty board. Pagination stays conservative
    at Workday's normal 20-item page size.
    """
    host, tenant, site, locale, remainder = workday_board_parts(board)

    # A direct posting gets one precise detail request instead of a board scan.
    if remainder and remainder[0].lower() == "job":
        return [fetch_workday_job(board, company=company, timeout=timeout)]

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
    )

    endpoint = f"https://{host}/wday/cxs/{tenant}/{site}/jobs"
    page_size = 20
    offset = 0
    total: Optional[int] = None
    postings = []
    cap = max(1, int(max_jobs))

    while offset < cap:
        response = session.post(
            endpoint,
            json={
                "appliedFacets": {},
                "limit": page_size,
                "offset": offset,
                "searchText": search_text or "",
            },
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()

        if total is None:
            try:
                total = int(payload.get("total"))
            except Exception:
                total = None

        batch = payload.get("jobPostings") or []
        if not isinstance(batch, list) or not batch:
            break

        postings.extend(batch)
        offset += len(batch)

        if total is not None and offset >= total:
            break
        if len(batch) < page_size:
            break

    leads = []
    for item in postings[:cap]:
        external_path = str(item.get("externalPath") or "").strip()
        if not external_path:
            continue

        title = str(item.get("title") or "")
        location = str(item.get("locationsText") or item.get("location") or "")
        description = ""
        external_id = external_path

        if include_descriptions:
            try:
                info = _workday_detail(
                    session,
                    host,
                    tenant,
                    site,
                    external_path,
                    timeout,
                )
                title = str(info.get("title") or title)
                location = str(info.get("location") or info.get("locationsText") or location)
                description = str(info.get("jobDescription") or "")
                external_id = str(info.get("jobReqId") or external_path)
            except Exception:
                pass

        leads.append(
            JobLead(
                source="workday",
                company=company or tenant,
                title=title,
                url=_workday_public_url(host, site, locale, external_path),
                location=location,
                description=description,
                external_id=external_id,
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


def _looks_like_workday_board(url: str) -> bool:
    try:
        _host, _tenant, _site, _locale, remainder = workday_board_parts(url)
        return not remainder or remainder[0].lower() != "job"
    except Exception:
        return False


def expand_career_urls(
    urls: Iterable[str],
    company: str = "",
    timeout: int = 20,
    workday_search_terms: Optional[Iterable[str]] = None,
    workday_max_jobs_per_term: int = 100,
) -> Tuple[List[JobLead], List[dict]]:
    """
    Expand public Greenhouse, Lever and Workday career boards into jobs.

    Other supported direct ATS links (including BrassRing and Avature) remain
    direct source leads and are handled by their browser adapters.
    """
    jobs: List[JobLead] = []
    errors = []

    terms = _dedupe(workday_search_terms or [])[:3]
    if not terms:
        terms = [""]

    for url in _dedupe(urls):
        source = infer_source(url)

        try:
            if source == "greenhouse" and _looks_like_greenhouse_board(url):
                jobs.extend(fetch_greenhouse_jobs(url, company=company, timeout=timeout))
                continue

            if source == "lever" and _looks_like_lever_board(url):
                jobs.extend(fetch_lever_jobs(url, company=company, timeout=timeout))
                continue

            if source == "workday":
                if _looks_like_workday_board(url):
                    for term in terms:
                        jobs.extend(
                            fetch_workday_jobs(
                                url,
                                company=company,
                                timeout=timeout,
                                search_text=term,
                                max_jobs=workday_max_jobs_per_term,
                                include_descriptions=True,
                            )
                        )
                    continue

                jobs.extend(fetch_workday_jobs(url, company=company, timeout=timeout))
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

    seen = set()
    unique = []
    for job in jobs:
        key = (job.source, job.external_id, job.url)
        if key in seen:
            continue
        seen.add(key)
        unique.append(job)

    return unique, errors


def expand_pdf_sources(
    pdf_path: str,
    company: str = "",
    timeout: int = 20,
    workday_search_terms: Optional[Iterable[str]] = None,
    workday_max_jobs_per_term: int = 100,
):
    return expand_career_urls(
        extract_urls_from_pdf(pdf_path),
        company=company,
        timeout=timeout,
        workday_search_terms=workday_search_terms,
        workday_max_jobs_per_term=workday_max_jobs_per_term,
    )
