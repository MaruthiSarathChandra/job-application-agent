import tempfile
import unittest
from pathlib import Path

from pipeline.job_store import JobStore, canonicalize_url, dedupe_key
from pipeline.models import JobLead


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


if __name__ == "__main__":
    unittest.main()
