import tempfile
import unittest
from pathlib import Path

from pipeline.job_store import JobStore, canonicalize_url, dedupe_key
from pipeline.models import JobLead, JobMatch


class JobStoreTests(unittest.TestCase):
    def test_canonical_url_removes_tracking(self):
        url = "https://example.com/job/123/?utm_source=linkedin&ref=test&foo=bar#apply"
        self.assertEqual(
            canonicalize_url(url),
            "https://example.com/job/123?foo=bar",
        )

    def test_dedupe_prefers_external_id(self):
        a = JobLead(
            source="greenhouse",
            company="Acme",
            title="Backend Engineer",
            url="https://a.example/job/1",
            external_id="123",
        )
        b = JobLead(
            source="greenhouse",
            company="Acme",
            title="Different title",
            url="https://b.example/job/2",
            external_id="123",
        )
        self.assertEqual(dedupe_key(a), dedupe_key(b))

    def test_upsert_deduplicates_tracking_variants(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "jobs.db")
            store = JobStore(db)
            try:
                first = JobLead(
                    source="career_site",
                    company="Acme",
                    title="Software Engineer",
                    url="https://careers.acme.com/jobs/42?utm_source=linkedin",
                )
                second = JobLead(
                    source="career_site",
                    company="Acme",
                    title="Software Engineer",
                    url="https://careers.acme.com/jobs/42?utm_medium=social",
                )
                first_id = store.upsert(first)
                second_id = store.upsert(second)
                self.assertEqual(first_id, second_id)
                rows = store.list_rows(limit=10)
                self.assertEqual(len(rows), 1)
            finally:
                store.close()

    def test_reranking_preserves_resume_ready_pipeline_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "jobs.db")
            store = JobStore(db)
            try:
                job = JobLead(
                    source="brassring",
                    company="Acme",
                    title="Software Engineer",
                    url="https://sjobs.brassring.com/TGnewUI/Search/home/HomeWithPreLoad?jobId=42",
                )
                job_id = store.upsert(job)
                store.set_resume(job_id, str(Path(tmp) / "resume.docx"))
                store.set_application_status(job_id, "review")

                match = JobMatch(
                    job=job,
                    score=50.0,
                    title_score=30.0,
                    skills_score=20.0,
                    matched_skills=["Java"],
                    reasons=["title matched"],
                )
                store.save_match(job_id, match)

                row = store.get(job_id)
                self.assertEqual(row["pipeline_status"], "resume_ready")
                self.assertEqual(row["application_status"], "review")
                self.assertTrue(row["resume_path"])

                queued = store.list_application_queue(
                    minimum_score=0,
                    statuses=("review",),
                    limit=10,
                )
                self.assertEqual([item["job_id"] for item in queued], [job_id])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
