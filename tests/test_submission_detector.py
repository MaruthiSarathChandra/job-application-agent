import unittest

from browser.submission_detector import confirmation_from_text


class SubmissionDetectorTests(unittest.TestCase):
    def test_greenhouse_success(self):
        self.assertTrue(confirmation_from_text("Thank you for applying!"))

    def test_lever_success(self):
        self.assertTrue(confirmation_from_text("Thanks for applying. We received your application."))

    def test_workday_success(self):
        self.assertTrue(confirmation_from_text("Your application has been submitted."))

    def test_review_page_is_not_success(self):
        self.assertFalse(
            confirmation_from_text(
                "Review your application below. Submit Application when you are ready."
            )
        )

    def test_failure_is_not_success(self):
        self.assertFalse(confirmation_from_text("Submission failed. Please correct required fields."))


if __name__ == "__main__":
    unittest.main()
