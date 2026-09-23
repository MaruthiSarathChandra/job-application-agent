import unittest

from agent.submission_policy import SubmissionPolicy


class SubmissionPolicyTests(unittest.TestCase):
    def test_manual_mode_never_submits(self):
        result = SubmissionPolicy("manual").decide([])
        self.assertFalse(result.may_submit)

    def test_auto_if_safe_allows_clean_decisions(self):
        decisions = [
            {
                "question": "Are you willing to relocate?",
                "answer": "Yes",
                "source": "CONFIRMED_MEMORY",
                "confidence": 0.99,
                "review_required": False,
                "category": "relocation",
            }
        ]
        result = SubmissionPolicy("auto_if_safe").decide(decisions)
        self.assertTrue(result.may_submit)

    def test_auto_if_safe_blocks_validation_error(self):
        result = SubmissionPolicy("auto_if_safe").decide(
            [],
            validation_errors=["Required field missing"],
        )
        self.assertFalse(result.may_submit)

    def test_conflict_of_interest_never_auto_submits(self):
        decisions = [
            {
                "question": "Conflict question",
                "answer": "No",
                "source": "LOCKED_PROFILE",
                "confidence": 1.0,
                "review_required": False,
                "category": "conflict_of_interest",
            }
        ]
        result = SubmissionPolicy("auto_if_safe").decide(decisions)
        self.assertFalse(result.may_submit)


if __name__ == "__main__":
    unittest.main()
