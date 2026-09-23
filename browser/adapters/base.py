from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from pipeline.models import JobLead


@dataclass
class ApplicationContext:
    job_id: str
    job: JobLead
    resume_path: str
    company: str = ""
    role: str = ""
    submission_mode: str = "manual"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AdapterResult:
    status: str
    review_required: bool = False
    submitted: bool = False
    message: str = ""
    blockers: List[Dict[str, Any]] = field(default_factory=list)
    decisions: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ATSAdapter:
    name = "base"

    def supports(self, job: JobLead) -> bool:
        raise NotImplementedError

    def run(self, page, profile, context: ApplicationContext) -> AdapterResult:
        raise NotImplementedError
