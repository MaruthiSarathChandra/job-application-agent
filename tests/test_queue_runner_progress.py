import unittest
from types import SimpleNamespace

from browser.queue_runner import _blocker_fingerprint


class QueueRunnerProgressTests(unittest.TestCase):
    def test_same_blocker_has_same_fingerprint(self):
        first = SimpleNamespace(
            status="review",
            message="Resume upload failed",
            blockers=[{"category": "resume", "reason": "resume_upload_failed"}],
        )
        second = SimpleNamespace(
            status="review",
            message="Resume upload failed",
            blockers=[{"reason": "resume_upload_failed", "category": "resume"}],
        )
        self.assertEqual(_blocker_fingerprint(first), _blocker_fingerprint(second))

    def test_changed_blocker_changes_fingerprint(self):
        first = SimpleNamespace(
            status="review",
            message="Resume upload failed",
            blockers=[{"category": "resume", "reason": "resume_upload_failed"}],
        )
        second = SimpleNamespace(
            status="review",
            message="Application question requires review",
            blockers=[{"category": "question", "reason": "answer_required"}],
        )
        self.assertNotEqual(_blocker_fingerprint(first), _blocker_fingerprint(second))


if __name__ == "__main__":
    unittest.main()
