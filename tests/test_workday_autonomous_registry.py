import unittest

from browser.adapters import get_adapter
from browser.adapters.workday_autonomous import AutonomousWorkdayAdapter
from pipeline.models import JobLead


class WorkdayAutonomousRegistryTests(unittest.TestCase):
    def test_workday_jobs_use_autonomous_adapter(self):
        job = JobLead(
            source="workday",
            company="Example",
            title="Software Engineer",
            url=(
                "https://example.wd3.myworkdayjobs.com/External/job/City/"
                "Software-Engineer_R123"
            ),
        )
        adapter = get_adapter(job)
        self.assertIsInstance(adapter, AutonomousWorkdayAdapter)


if __name__ == "__main__":
    unittest.main()
