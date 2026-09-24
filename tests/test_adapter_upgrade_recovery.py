import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from agent.profile import CandidateProfile
from agent_v2 import _prepare
from pipeline.job_store import JobStore
from pipeline.models import JobLead


class AdapterUpgradeRecoveryTests(unittest.TestCase):
    def _profile_and_args(self, root, db):
        profile_path = root / "candidate_profile.yaml"
        profile_path.write_text(
            """
candidate:
  legal_name: Example Candidate
  email: candidate@example.com
preferences:
  target_roles: [Software Engineer]
verified_facts:
  skills: [Python]
""".strip(),
            encoding="utf-8",
        )
        args = SimpleNamespace(
            db=db,
            scan_limit=10,
            minimum_score=0,
            output_dir=str(root / "resumes"),
            prepare_limit=0,
        )
        return CandidateProfile(str(profile_path)), args

    def test_adapter_missing_job_is_requeued_after_upgrade(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = str(root / "jobs.db")
            profile, args = self._profile_and_args(root, db)
            job = JobLead(
                source="career_site",
                company="Example",
                title="Software Engineer",
                url="https://careers.example.com/jobs/123",
            )

            store = JobStore(db)
            try:
                job_id = store.upsert(job)
                store.set_application_status(job_id, "adapter_missing")
            finally:
                store.close()

            _prepare(profile, [job], args)

            store = JobStore(db)
            try:
                row = store.get(job_id)
                self.assertEqual(row["application_status"], "not_started")
            finally:
                store.close()

    def test_interrupted_in_progress_job_is_requeued_for_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            db = str(root / "jobs.db")
            profile, args = self._profile_and_args(root, db)
            job = JobLead(
                source="workday",
                company="Example",
                title="Software Engineer",
                url="https://example.wd1.myworkdayjobs.com/External/job/Test/Software-Engineer_R1/apply",
            )

            store = JobStore(db)
            try:
                job_id = store.upsert(job)
                store.set_application_status(job_id, "in_progress")
            finally:
                store.close()

            _prepare(profile, [job], args)

            store = JobStore(db)
            try:
                row = store.get(job_id)
                self.assertEqual(row["application_status"], "review")
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
