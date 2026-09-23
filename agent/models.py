from dataclasses import dataclass, asdict
from typing import Optional, Any, Dict


@dataclass
class AnswerDecision:
    question: str
    answer: Optional[str]
    source: str
    confidence: float
    review_required: bool
    category: str
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ResumeDecision:
    resume_key: Optional[str]
    resume_label: Optional[str]
    resume_path: Optional[str]
    confidence: float
    review_required: bool
    rationale: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
