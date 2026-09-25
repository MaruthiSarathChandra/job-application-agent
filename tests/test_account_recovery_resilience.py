import unittest
from types import SimpleNamespace

from browser.account_recovery_resilience import (
    RESET_SUBMIT_NAMES,
    _blocker_contains,
)


class AccountRecoveryResilienceTests(unittest.TestCase):
    def test_avature_password_activation_label_is_supported(self):
        self.assertIn("Activate", RESET_SUBMIT_NAMES)
        self.assertIn("Activate Password", RESET_SUBMIT_NAMES)

    def test_reset_submit_missing_blocker_is_detected(self):
        result = SimpleNamespace(
            blockers=[
                {
                    "category": "credential_recovery",
                    "reason": "Password reset submit control was not found.",
                }
            ]
        )
        self.assertTrue(
            _blocker_contains(
                result,
                "credential_recovery",
                "submit control was not found",
            )
        )

    def test_other_blockers_do_not_match(self):
        result = SimpleNamespace(
            blockers=[{"category": "verification", "reason": "Email verification required"}]
        )
        self.assertFalse(
            _blocker_contains(
                result,
                "credential_recovery",
                "submit control was not found",
            )
        )


if __name__ == "__main__":
    unittest.main()
