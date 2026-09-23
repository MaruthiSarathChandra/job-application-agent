import re
from typing import Optional
from .models import AnswerDecision
from .profile import CandidateProfile


def _clean(text: str) -> str:
    return " ".join(text.strip().lower().split())


class AnswerPolicy:
    """
    Deterministic answers have priority over the LLM.

    Critical principle:
    The model may interpret wording, but it may not alter locked facts.
    """

    def __init__(self, profile: CandidateProfile):
        self.profile = profile

    def answer_locked(self, question: str) -> Optional[AnswerDecision]:
        q = _clean(question)

        # CURRENT US WORK AUTHORIZATION
        if re.search(
            r"(authorized|legally authorized|eligible).*(work|employment).*(united states|u\.?s\.?)",
            q,
        ):
            value = self.profile.get_locked_value(
                "work_authorization.currently_authorized_us"
            )
            if isinstance(value, bool):
                return self._bool_decision(
                    question,
                    value,
                    "work_authorization_now",
                    "Locked candidate profile.",
                )

        # SPONSORSHIP NOW
        if (
            "sponsorship" in q
            and any(token in q for token in ["currently", "now", "at this time"])
            and "future" not in q
        ):
            value = self.profile.get_locked_value(
                "work_authorization.requires_sponsorship_now"
            )
            if isinstance(value, bool):
                return self._bool_decision(
                    question,
                    value,
                    "sponsorship_now",
                    "Locked candidate profile.",
                )

        # NOW OR IN THE FUTURE — keep separate from sponsorship-now.
        if "sponsorship" in q and "future" in q:
            value = self.profile.get_locked_value(
                "work_authorization.requires_sponsorship_future"
            )

            if isinstance(value, bool):
                return self._bool_decision(
                    question,
                    value,
                    "future_sponsorship",
                    "Locked candidate profile.",
                )

            return AnswerDecision(
                question=question,
                answer=None,
                source="POLICY",
                confidence=1.0,
                review_required=True,
                category="future_sponsorship",
                rationale=(
                    "Future-sponsorship questions are legally/immigration-sensitive "
                    "and the profile is configured as REVIEW."
                ),
            )

        # RELOCATION
        if "relocat" in q:
            value = self.profile.get("preferences.willing_to_relocate")
            if isinstance(value, bool):
                return self._bool_decision(
                    question,
                    value,
                    "relocation",
                    "Candidate preference from profile.",
                )

        # WORK MODALITY
        if "remote" in q and any(
            phrase in q for phrase in ["comfortable", "willing", "able", "open to"]
        ):
            value = self.profile.get("preferences.remote_ok")
            if isinstance(value, bool):
                return self._bool_decision(
                    question,
                    value,
                    "work_mode",
                    "Candidate preference from profile.",
                )

        if "onsite" in q or "on-site" in q:
            value = self.profile.get("preferences.onsite_ok")
            if isinstance(value, bool):
                return self._bool_decision(
                    question,
                    value,
                    "work_mode",
                    "Candidate preference from profile.",
                )

        if "hybrid" in q:
            value = self.profile.get("preferences.hybrid_ok")
            if isinstance(value, bool):
                return self._bool_decision(
                    question,
                    value,
                    "work_mode",
                    "Candidate preference from profile.",
                )

        # HIGH-RISK / PERSONAL / LEGAL CATEGORIES -> manual review.
        risky_patterns = {
            "security_clearance": [
                r"security clearance",
                r"secret clearance",
                r"top secret",
            ],
            "government_eligibility": [
                r"u\.?s\.? citizen",
                r"citizenship required",
                r"export control",
                r"itar",
            ],
            "criminal_disclosure": [
                r"convicted",
                r"criminal",
                r"felony",
            ],
            "disability": [r"disability", r"disabled"],
            "veteran_status": [r"veteran"],
            "race_ethnicity": [r"race", r"ethnicity", r"ethnic"],
            "gender": [r"gender", r"sex"],
            "salary_commitment": [
                r"desired salary",
                r"salary expectation",
                r"minimum salary",
                r"compensation expectation",
            ],
            "legal_attestation": [
                r"certify",
                r"attest",
                r"under penalty",
                r"signature",
                r"terms and conditions",
            ],
        }

        for category, patterns in risky_patterns.items():
            if any(re.search(pattern, q) for pattern in patterns):
                return AnswerDecision(
                    question=question,
                    answer=None,
                    source="POLICY",
                    confidence=1.0,
                    review_required=True,
                    category=category,
                    rationale=f"Configured as review-required category: {category}.",
                )

        return None

    @staticmethod
    def _bool_decision(question, value, category, rationale):
        return AnswerDecision(
            question=question,
            answer="Yes" if value else "No",
            source="LOCKED_PROFILE",
            confidence=1.0,
            review_required=False,
            category=category,
            rationale=rationale,
        )
