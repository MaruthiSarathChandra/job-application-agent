import unittest

from browser.workday_source import job_source_categories, normalize_job_source


class WorkdaySourceTests(unittest.TestCase):
    def test_linkedin_normalizes_to_workday_leaf(self):
        self.assertEqual(normalize_job_source("LinkedIn"), "LinkedIn Job Post")

    def test_indeed_prefers_third_party_job_boards(self):
        categories = job_source_categories("Indeed")
        self.assertEqual(categories[0], "Third Party Job Boards")

    def test_linkedin_prefers_third_party_job_boards(self):
        categories = job_source_categories("LinkedIn Job Post")
        self.assertEqual(categories[0], "Third Party Job Boards")

    def test_unknown_source_is_preserved_without_invention(self):
        self.assertEqual(normalize_job_source("University Portal"), "University Portal")


if __name__ == "__main__":
    unittest.main()
