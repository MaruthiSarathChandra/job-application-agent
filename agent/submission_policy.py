from dataclasses import dataclass
from typing import Iterable


REVIEW_CATEGORIES = {
    "legal_attestation",
    "future_sponsorship",
    "criminal_disclosure",
    "security_clearance",
    "government_eligibility",
    "salary_commitment",
    "disability",
    "veteran_status",
    "race_ethnicity",
    "gender",
}


@dataclass
class SubmissionDecision:
    may_submit: bool
    reason: str


class SubmissionPolicy:
    """
    A final submit click is allowed only in explicit auto mode and only when no
    unresolved legal/sensitive/review-required decision remains.

    Default mode remains manual. CAPTCHA, MFA/OTP and legal attestations are not
    automated by this policy.
    """

    def __init__(self, mode: str = "manual"):
        self.mode = (mode or "manual").strip().lower()

    def decide(self, decisions: Iterable[dict], validation_errors=None):
        if self.mode != "auto_if_safe":
            return SubmissionDecision(False, "Submission mode is manual.")

        if validation_errors:
            return SubmissionDecision(False, "Validation errors remain.")

        for decision in decisions or []:
            if decision.get("review_required"):
                return SubmissionDecision(False, "A review-required answer remains.")
            if decision.get("category") in REVIEW_CATEGORIES:
                return SubmissionDecision(
                    False,
                    f"Manual confirmation required for {decision.get('category')}.",
                )

        return SubmissionDecision(True, "All recorded answers passed the safe-submit gate.")
