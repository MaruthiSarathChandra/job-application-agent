from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Sequence
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from .ats import detect_ats
from .models import JobLead, JobMatch


TRACKING_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "source",
    "src",
    "trk",
    "trackingid",
    "ref",
    "refid",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonicalize_url(url: str) -> str:
    value = (url or "").strip()
    if not value:
        return ""

    parsed = urlparse(value)
    query = []
    for key, item in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() in TRACKING_KEYS or key.lower().startswith("utm_"):
            continue
        query.append((key, item))

    normalized_path = parsed.path.rstrip("/") or "/"
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        path=normalized_path,
        query=urlencode(query, doseq=True),
        fragment="",
    )
    return urlunparse(normalized)


def dedupe_key(job: JobLead) -> str:
    source = (job.source or detect_ats(job.url) or "career_site").strip().lower()
    external = (job.external_id or "").strip()
    company = " ".join((job.company or "").lower().split())
    title = " ".join((job.title or "").lower().split())
    location = " ".join((job.location or "").lower().split())
    url = canonicalize_url(job.url)

    if external:
        material = f"external|{source}|{company}|{external}"
    elif url:
        material = f"url|{url}"
    else:
        material = f"fallback|{source}|{company}|{title}|{location}"

    return hashlib.sha256(material.encode("utf-8")).hexdigest()


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    job_id TEXT PRIMARY KEY,
    dedupe_key TEXT NOT NULL UNIQUE,
    source TEXT NOT NULL,
    ats TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    canonical_url TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    external_id TEXT NOT NULL DEFAULT '',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    match_score REAL,
    title_score REAL,
    skills_score REAL,
    matched_skills TEXT NOT NULL DEFAULT '',
    reasons TEXT NOT NULL DEFAULT '',
    pipeline_status TEXT NOT NULL DEFAULT 'discovered',
    resume_path TEXT NOT NULL DEFAULT '',
    application_status TEXT NOT NULL DEFAULT 'not_started',
    last_error TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_jobs_pipeline_status
ON jobs(pipeline_status, match_score DESC);

CREATE INDEX IF NOT EXISTS idx_jobs_application_status
ON jobs(application_status, last_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_jobs_company_title
ON jobs(company, title);
"""


DEFAULT_RESUMABLE_STATUSES = (
    "not_started",
    "review",
    "verification_required",
    "account_review",
    "error",
)


class JobStore:
    def __init__(self, db_path: str = "data/jobs.db"):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    def upsert(self, job: JobLead) -> str:
        key = dedupe_key(job)
        now = _utc_now()
        existing = self.conn.execute(
            "SELECT job_id FROM jobs WHERE dedupe_key=?",
            (key,),
        ).fetchone()

        ats = detect_ats(job.url)
        source = (job.source or ats or "career_site").strip().lower()
        canonical_url = canonicalize_url(job.url)

        if existing:
            job_id = str(existing["job_id"])
            self.conn.execute(
                """
                UPDATE jobs
                SET source=?, ats=?, company=?, title=?, url=?, canonical_url=?,
                    location=?, description=?, external_id=?, last_seen_at=?
                WHERE job_id=?
                """,
                (
                    source,
                    ats,
                    job.company or "",
                    job.title or "",
                    job.url or "",
                    canonical_url,
                    job.location or "",
                    job.description or "",
                    job.external_id or "",
                    now,
                    job_id,
                ),
            )
        else:
            job_id = key[:24]
            self.conn.execute(
                """
                INSERT INTO jobs (
                    job_id, dedupe_key, source, ats, company, title, url,
                    canonical_url, location, description, external_id,
                    first_seen_at, last_seen_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    key,
                    source,
                    ats,
                    job.company or "",
                    job.title or "",
                    job.url or "",
                    canonical_url,
                    job.location or "",
                    job.description or "",
                    job.external_id or "",
                    now,
                    now,
                ),
            )

        self.conn.commit()
        return job_id

    def upsert_many(self, jobs: Iterable[JobLead]) -> List[str]:
        return [self.upsert(job) for job in jobs]

    def save_match(self, job_id: str, match: JobMatch):
        """
        Save the latest score without destroying downstream pipeline progress.

        Re-running discovery/ranking is common. If a resume was already generated,
        the job must remain `resume_ready`; otherwise the application queue loses
        the job even though `resume_path` still points at a valid DOCX.
        """
        self.conn.execute(
            """
            UPDATE jobs
            SET match_score=?, title_score=?, skills_score=?, matched_skills=?,
                reasons=?,
                pipeline_status=CASE
                    WHEN TRIM(COALESCE(resume_path, '')) <> '' THEN 'resume_ready'
                    ELSE ?
                END
            WHERE job_id=?
            """,
            (
                float(match.score),
                float(match.title_score),
                float(match.skills_score),
                "\n".join(match.matched_skills),
                "\n".join(match.reasons),
                "qualified" if match.score > 0 else "ranked",
                job_id,
            ),
        )
        self.conn.commit()

    def set_resume(self, job_id: str, resume_path: str):
        self.conn.execute(
            """
            UPDATE jobs
            SET resume_path=?, pipeline_status='resume_ready', last_error=''
            WHERE job_id=?
            """,
            (resume_path, job_id),
        )
        self.conn.commit()

    def set_error(self, job_id: str, error: str, status: str = "error"):
        self.conn.execute(
            "UPDATE jobs SET pipeline_status=?, last_error=? WHERE job_id=?",
            (status, str(error)[:4000], job_id),
        )
        self.conn.commit()

    def set_application_status(self, job_id: str, status: str):
        self.conn.execute(
            "UPDATE jobs SET application_status=? WHERE job_id=?",
            (status, job_id),
        )
        self.conn.commit()

    def get(self, job_id: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM jobs WHERE job_id=?",
            (job_id,),
        ).fetchone()

    def list_rows(
        self,
        minimum_score: Optional[float] = None,
        pipeline_status: Optional[str] = None,
        application_status: Optional[str] = None,
        limit: int = 100,
    ):
        clauses = []
        params = []

        if minimum_score is not None:
            clauses.append("COALESCE(match_score, -1) >= ?")
            params.append(float(minimum_score))
        if pipeline_status:
            clauses.append("pipeline_status = ?")
            params.append(pipeline_status)
        if application_status:
            clauses.append("application_status = ?")
            params.append(application_status)

        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        sql = (
            "SELECT * FROM jobs"
            + where
            + " ORDER BY COALESCE(match_score, -1) DESC, last_seen_at DESC LIMIT ?"
        )
        params.append(int(limit))
        return self.conn.execute(sql, params).fetchall()

    def list_application_queue(
        self,
        minimum_score: float = 40.0,
        statuses: Sequence[str] = DEFAULT_RESUMABLE_STATUSES,
        limit: int = 100,
    ):
        clean_statuses = [str(value).strip() for value in statuses if str(value).strip()]
        if not clean_statuses:
            return []

        placeholders = ",".join("?" for _ in clean_statuses)
        sql = f"""
            SELECT * FROM jobs
            WHERE pipeline_status='resume_ready'
              AND COALESCE(match_score, -1) >= ?
              AND application_status IN ({placeholders})
            ORDER BY
              CASE application_status
                WHEN 'not_started' THEN 0
                WHEN 'verification_required' THEN 1
                WHEN 'account_review' THEN 2
                WHEN 'review' THEN 3
                WHEN 'error' THEN 4
                ELSE 5
              END,
              match_score DESC,
              last_seen_at DESC
            LIMIT ?
        """
        params = [float(minimum_score), *clean_statuses, int(limit)]
        return self.conn.execute(sql, params).fetchall()

    @staticmethod
    def row_to_job(row) -> JobLead:
        return JobLead(
            source=row["source"],
            company=row["company"],
            title=row["title"],
            url=row["url"],
            location=row["location"],
            description=row["description"],
            external_id=row["external_id"],
        )
