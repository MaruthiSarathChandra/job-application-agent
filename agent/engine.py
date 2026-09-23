from .answer_policy import AnswerPolicy
from .models import AnswerDecision
from .profile import CandidateProfile


class ApplicationEngine:
    def __init__(self, profile: CandidateProfile, use_llm: bool = True):
        self.profile = profile
        self.policy = AnswerPolicy(profile)
        self.use_llm = use_llm
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
        deterministic = self.policy.answer_locked(question)
        if deterministic is not None:
            return deterministic

        if not self.use_llm:
            return AnswerDecision(
                question=question,
                answer=None,
                source="NO_LLM",
                confidence=0.0,
                review_required=True,
                category="unknown",
                rationale="No deterministic rule matched and LLM is disabled.",
            )

        return self.llm.answer(question, job_text)
