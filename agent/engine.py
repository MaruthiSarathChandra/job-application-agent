from .answer_policy import AnswerPolicy
from .models import AnswerDecision
from .profile import CandidateProfile


class ApplicationEngine:
    def __init__(
        self,
        profile: CandidateProfile,
        use_llm: bool = True,
        memory=None,
        company: str = "",
        ats: str = "",
        memory_min_confirmations: int = 2,
    ):
        self.profile = profile
        self.policy = AnswerPolicy(profile)
        self.use_llm = use_llm
        self.memory = memory
        self.company = company or ""
        self.ats = (ats or "").strip().lower()
        self.memory_min_confirmations = int(memory_min_confirmations)
        self._llm = None

    @property
    def llm(self):
        if self._llm is None:
            from .llm import LLMAnswerer
            self._llm = LLMAnswerer(self.profile)
        return self._llm

    def answer_question(
        self,
        question: str,
        job_text: str = "",
    ) -> AnswerDecision:
        # Locked profile facts always outrank learned answers.
        deterministic = self.policy.answer_locked(question)
        if deterministic is not None:
            return deterministic

        # Reuse only user-confirmed, non-sensitive memory. The memory layer
        # independently blocks immigration, legal, demographic, salary,
        # credential and authentication categories.
        if self.memory is not None:
            learned = self.memory.lookup(
                question,
                company=self.company,
                ats=self.ats,
                min_confirmations=self.memory_min_confirmations,
            )
            if learned is not None:
                confidence = min(
                    0.999,
                    0.94 + min(learned.confirmations, 5) * 0.01,
                )
                confidence *= max(0.94, float(learned.similarity))
                return AnswerDecision(
                    question=question,
                    answer=learned.answer,
                    source="CONFIRMED_MEMORY",
                    confidence=round(confidence, 4),
                    review_required=False,
                    category=learned.category or "learned",
                    rationale=(
                        f"Reused a non-sensitive answer confirmed "
                        f"{learned.confirmations} time(s); "
                        f"question similarity={learned.similarity:.3f}."
                    ),
                )

        if not self.use_llm:
            return AnswerDecision(
                question=question,
                answer=None,
                source="NO_LLM",
                confidence=0.0,
                review_required=True,
                category="unknown",
                rationale="No deterministic or confirmed-memory rule matched and LLM is disabled.",
            )

        return self.llm.answer(question, job_text)
