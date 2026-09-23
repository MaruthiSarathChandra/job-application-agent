import json
import os
from typing import Dict, Any

from dotenv import load_dotenv
from openai import OpenAI

from .models import AnswerDecision
from .profile import CandidateProfile

load_dotenv()


SYSTEM_RULES = """
You are one component inside a job-application assistant.

Your job is ONLY to draft an answer to a non-critical application question
using the supplied candidate facts and job description.

Hard rules:
1. Never invent employment, education, dates, skills, certifications,
   citizenship, visa status, salary history, security clearance, or years
   of experience.
2. Never upgrade a project into professional employment.
3. Never change or reinterpret locked candidate facts.
4. If the supplied facts are insufficient, return review_required=true.
5. Be concise and suitable for a job-application form.
6. Confidence must represent factual confidence, not writing quality.
7. Never infer that the candidate is currently a student merely because
   education information is provided. Use candidate.current_status exactly.
8. Technical experience may only be described using verified_facts.
   You may rephrase or summarize verified facts, but never add new facts.
   
Return JSON only with these fields:
{
  "answer": string | null,
  "confidence": number,
  "review_required": boolean,
  "category": string,
  "rationale": string
}
"""


class LLMAnswerer:
    def __init__(self, profile: CandidateProfile):
        self.profile = profile
        self.model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
        self.client = OpenAI()

    def _safe_candidate_context(self) -> Dict[str, Any]:
        """
        Expose only non-secret application facts to the model.
        Add verified experience/project facts here as you build the system.
        """
        return {
            "candidate": self.profile.get("candidate", {}),
            "education": self.profile.get("education", {}),
            "preferences": self.profile.get("preferences", {}),
            "verified_facts": self.profile.get("verified_facts", {}),
            # Work authorization is intentionally omitted from the LLM context.
            # Deterministic policy code handles it.
        }

    def answer(self, question: str, job_text: str = "") -> AnswerDecision:
        payload = {
            "candidate_facts": self._safe_candidate_context(),
            "job_description": job_text[:18000],
            "question": question,
        }

        response = self.client.responses.create(
            model=self.model,
            instructions=SYSTEM_RULES,
            input=json.dumps(payload, ensure_ascii=False),
        )

        raw = response.output_text.strip()

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return AnswerDecision(
                question=question,
                answer=None,
                source=f"LLM:{self.model}",
                confidence=0.0,
                review_required=True,
                category="llm_parse_error",
                rationale=f"Model did not return valid JSON. Raw output: {raw[:300]}",
            )

        confidence = float(data.get("confidence", 0.0))
        review_required = bool(data.get("review_required", True))

        if confidence < self.profile.llm_min_confidence:
            review_required = True

        return AnswerDecision(
            question=question,
            answer=data.get("answer"),
            source=f"LLM:{self.model}",
            confidence=confidence,
            review_required=review_required,
            category=str(data.get("category", "general")),
            rationale=str(data.get("rationale", "")),
        )
