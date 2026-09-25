import unittest

from browser.adapters.generic_career import GenericCareerSiteAdapter
from browser.adapters.registry import get_adapter
from pipeline.models import JobLead


class GenericAdapterRegistryTests(unittest.TestCase):
    def test_unknown_career_site_uses_generic_adapter(self):
        job = JobLead(
            source="career_site",
            company="Example",
            title="Software Engineer",
            url="https://careers.example.com/jobs/123",
        )
        adapter = get_adapter(job)
        self.assertIsInstance(adapter, GenericCareerSiteAdapter)


if __name__ == "__main__":
    unittest.main()
