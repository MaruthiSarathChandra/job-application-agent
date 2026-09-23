import unittest

from browser.adapters.brassring import classify_brassring_page


class BrassRingPreflightTests(unittest.TestCase):
    def test_expired_job_is_closed(self):
        status, reason = classify_brassring_page(
            "The job posting you are looking for has expired or the position has already been filled."
        )
        self.assertEqual(status, "closed")
        self.assertIn("expired", reason.lower())

    def test_already_applied(self):
        status, reason = classify_brassring_page(
            "You have already applied for this job. Check your applications."
        )
        self.assertEqual(status, "already_applied")

    def test_normal_page_is_open(self):
        status, reason = classify_brassring_page(
            "Software Developer Job Summary Quick Apply"
        )
        self.assertEqual(status, "open")
        self.assertEqual(reason, "")


if __name__ == "__main__":
    unittest.main()
