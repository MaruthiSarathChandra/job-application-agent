from pathlib import Path
from typing import Any, Dict
import yaml


class CandidateProfile:
    def __init__(self, path: str = "candidate_profile.yaml"):
        self.path = Path(path)
        if not self.path.exists():
            raise FileNotFoundError(
                f"Candidate profile not found: {self.path.resolve()}"
            )

        with self.path.open("r", encoding="utf-8") as f:
            self.data: Dict[str, Any] = yaml.safe_load(f) or {}

    def get(self, dotted_path: str, default=None):
        current = self.data
        for part in dotted_path.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    def get_locked_value(self, dotted_path: str):
        node = self.get(dotted_path)
        if not isinstance(node, dict):
            return None

        if node.get("locked") is not True:
            return None

        return node.get("value")

    @property
    def resumes(self):
        return self.data.get("resumes", {})

    @property
    def llm_min_confidence(self) -> float:
        return float(self.get("safety.llm_min_confidence", 0.97))
