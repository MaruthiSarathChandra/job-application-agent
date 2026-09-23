from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List

from .job_matcher import rank_job
from .job_store import JobStore
from .models import JobLead, JobMatch
from resume_builder.docx_resume import build_tailored_resume


SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]+")


def safe_filename(value: str, fallback: str = "job") -> str:
    value = SAFE_FILENAME_RE.sub("_", (value or "").strip()).strip("._")
    return value[:100] or fallback


class PipelineOrchestrator:
    def __init__(self, profile, store: JobStore):
        self.profile = profile
        self.store = store

    def ingest(self, jobs: Iterable[JobLead]) -> List[str]:
        return self.store.upsert_many(jobs)

    def rank_all(self, limit: int = 500) -> List[JobMatch]:
        results = []
        rows = self.store.list_rows(limit=limit)

        for row in rows:
            job = self.store.row_to_job(row)
            match = rank_job(job, self.profile)
            self.store.save_match(str(row["job_id"]), match)
            results.append(match)

        results.sort(key=lambda item: item.score, reverse=True)
        return results

    def prepare_resumes(
        self,
        minimum_score: float = 40.0,
        output_dir: str = "data/generated_resumes",
        limit: int = 25,
    ):
        output_root = Path(output_dir)
        output_root.mkdir(parents=True, exist_ok=True)

        rows = self.store.list_rows(
            minimum_score=minimum_score,
            application_status="not_started",
            limit=limit,
        )

        prepared = []

        for row in rows:
            job_id = str(row["job_id"])
            job = self.store.row_to_job(row)
            company = safe_filename(job.company, "company")
            title = safe_filename(job.title, "role")
            filename = f"{company}__{title}__{job_id}.docx"
            path = output_root / filename

            try:
                result = build_tailored_resume(self.profile, job, str(path))
                self.store.set_resume(job_id, result)
                prepared.append(
                    {
                        "job_id": job_id,
                        "company": job.company,
                        "title": job.title,
                        "score": row["match_score"],
                        "resume_path": result,
                    }
                )
            except Exception as exc:
                self.store.set_error(job_id, str(exc), status="resume_error")
                prepared.append(
                    {
                        "job_id": job_id,
                        "company": job.company,
                        "title": job.title,
                        "score": row["match_score"],
                        "error": str(exc),
                    }
                )

        return prepared

    def ready_for_application(self, minimum_score: float = 40.0, limit: int = 100):
        rows = self.store.list_rows(
            minimum_score=minimum_score,
            pipeline_status="resume_ready",
            application_status="not_started",
            limit=limit,
        )
        return [dict(row) for row in rows]
