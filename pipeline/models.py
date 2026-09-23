from dataclasses import dataclass, asdict
from typing import Optional, Dict, Any, List


@dataclass
class JobLead:
    source: str
    company: str
    title: str
    url: str
    location: str = ""
    description: str = ""
    external_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class JobMatch:
    job: JobLead
    score: float
    title_score: float
    skills_score: float
    matched_skills: List[str]
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["job"] = self.job.to_dict()
        return data
