import re
from pathlib import Path
from .models import ResumeDecision
from .profile import CandidateProfile


YEAR_PATTERN = re.compile(
    r"\b(?P<years>\d{1,2})\s*\+?\s*(?:years?|yrs?)\b",
    re.IGNORECASE,
)


class ResumeRouter:
    def __init__(self, profile: CandidateProfile):
        self.profile = profile

    @staticmethod
    def _extract_required_years(job_text: str):
        values = [int(m.group("years")) for m in YEAR_PATTERN.finditer(job_text)]
        if not values:
            return None
        # Conservative: treat the highest explicit requirement as the requirement.
        return max(values)

    @staticmethod
    def _keyword_score(text: str, keywords):
        text = text.lower()
        hits = sum(1 for kw in keywords if str(kw).lower() in text)
        return hits

    def choose(self, job_text: str) -> ResumeDecision:
        resumes = self.profile.resumes
        eligible = {
            key: cfg
            for key, cfg in resumes.items()
            if cfg.get("eligible_for_auto_use") is True
        }

        if not eligible:
            return ResumeDecision(
                resume_key=None,
                resume_label=None,
                resume_path=None,
                confidence=0.0,
                review_required=True,
                rationale="No resume is approved for automatic use.",
            )

        required_years = self._extract_required_years(job_text)

        scored = []
        for key, cfg in eligible.items():
            score = self._keyword_score(
                job_text,
                cfg.get("target_keywords", []),
            )

            # Do not auto-select a resume merely because a job asks for more
            # years. Experience claims must come from the approved resume itself.
            scored.append((score, key, cfg))

        scored.sort(reverse=True, key=lambda row: row[0])
        top_score, key, cfg = scored[0]

        path = cfg.get("path")
        if not path:
            return ResumeDecision(
                resume_key=key,
                resume_label=cfg.get("label"),
                resume_path=None,
                confidence=0.0,
                review_required=True,
                rationale="Selected resume has no configured path.",
            )

        if not Path(path).exists():
            return ResumeDecision(
                resume_key=key,
                resume_label=cfg.get("label"),
                resume_path=path,
                confidence=0.50,
                review_required=True,
                rationale=f"Resume path is configured but file is missing: {path}",
            )

        confidence = 0.90 if top_score > 0 else 0.75
        rationale = (
            f"Selected from approved resumes using keyword alignment. "
            f"Keyword hits={top_score}. "
        )

        if required_years is not None:
            rationale += f"Job text mentions up to {required_years} years of experience. "

        # Resume selection itself is safe only if the user has approved that resume.
        return ResumeDecision(
            resume_key=key,
            resume_label=cfg.get("label"),
            resume_path=path,
            confidence=confidence,
            review_required=False,
            rationale=rationale.strip(),
        )
