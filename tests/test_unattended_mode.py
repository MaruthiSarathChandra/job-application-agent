import tempfile
import unittest
from pathlib import Path

from agent_v2 import _runtime_profile, build_parser


class UnattendedModeTests(unittest.TestCase):
    def test_cli_accepts_unattended_and_job_source(self):
        args = build_parser().parse_args([
            "--unattended",
            "--job-source",
            "LinkedIn Job Post",
        ])
        self.assertTrue(args.unattended)
        self.assertEqual(args.job_source, "LinkedIn Job Post")

    def test_runtime_profile_forces_auto_if_safe_without_mutating_original(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = Path(tmp) / "candidate_profile.yaml"
            original.write_text(
                """
candidate:
  legal_name: Example Candidate
  email: candidate@example.com
submission:
  mode: manual
application_defaults:
  job_source: Indeed
""".strip(),
                encoding="utf-8",
            )

            runtime_path, runtime_profile, cleanup = _runtime_profile(
                original,
                unattended=True,
                job_source="LinkedIn Job Post",
            )
            try:
                self.assertNotEqual(runtime_path, original)
                self.assertEqual(runtime_profile.get("submission.mode"), "auto_if_safe")
                self.assertEqual(
                    runtime_profile.get("application_defaults.job_source"),
                    "LinkedIn Job Post",
                )
                original_text = original.read_text(encoding="utf-8")
                self.assertIn("mode: manual", original_text)
                self.assertIn("job_source: Indeed", original_text)
            finally:
                if cleanup is not None:
                    cleanup.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
