import tempfile
import unittest
from pathlib import Path

from pipeline.models import JobLead
from resume_builder.docx_resume import build_tailored_resume


class FakeProfile:
    def __init__(self, data):
        self.data = data

    def get(self, dotted_path, default=None):
        value = self.data
        for part in dotted_path.split("."):
            if not isinstance(value, dict) or part not in value:
                return default
            value = value[part]
        return value


class LegacyResumeBuilderTests(unittest.TestCase):
    def test_builds_from_work_experience_without_resume_content(self):
        profile = FakeProfile(
            {
                "candidate": {
                    "legal_name": "Example Candidate",
                    "email": "candidate@example.com",
                },
                "verified_facts": {"skills": ["Java", "Spring Boot"]},
                "work_experience": [
                    {
                        "job_title": "Software Engineer",
                        "employer": "Example Employer",
                        "location": "Kansas City, MO",
                        "current_job": True,
                        "start_month": "February",
                        "start_year": "2026",
                        "description": "Develop backend services using Java and Spring Boot.",
                    }
                ],
                "education": {
                    "highest_degree": "MS Computer Science",
                    "university": "Example University",
                    "graduation_date": "2025-12-19",
                },
            }
        )
        job = JobLead(
            source="brassring",
            company="Example",
            title="Software Engineer",
            url="https://sjobs.brassring.com/example",
            description="Java Spring Boot REST APIs",
        )

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "resume.docx"
            result = build_tailored_resume(profile, job, str(output))
            self.assertEqual(Path(result), output)
            self.assertTrue(output.exists())
            self.assertGreater(output.stat().st_size, 0)


if __name__ == "__main__":
    unittest.main()
