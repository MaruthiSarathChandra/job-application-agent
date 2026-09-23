import unittest

from pipeline.ats import (
    ATS_BRASSRING,
    ATS_CAREER_SITE,
    ATS_GREENHOUSE,
    ATS_LEVER,
    ATS_LINKEDIN,
    ATS_WORKDAY,
    detect_ats,
)


class AtsDetectionTests(unittest.TestCase):
    def test_greenhouse(self):
        self.assertEqual(
            detect_ats("https://job-boards.greenhouse.io/example/jobs/123"),
            ATS_GREENHOUSE,
        )

    def test_workday(self):
        self.assertEqual(
            detect_ats("https://example.wd1.myworkdayjobs.com/en-US/jobs/job/Test_R-1"),
            ATS_WORKDAY,
        )

    def test_lever(self):
        self.assertEqual(
            detect_ats("https://jobs.lever.co/example/abc"),
            ATS_LEVER,
        )

    def test_brassring(self):
        self.assertEqual(
            detect_ats(
                "https://sjobs.brassring.com/TGnewUI/Search/home/HomeWithPreLoad?"
                "PageType=JobDetails&partnerid=25539&siteid=5313&jobId=5235658"
            ),
            ATS_BRASSRING,
        )

    def test_linkedin(self):
        self.assertEqual(
            detect_ats("https://www.linkedin.com/jobs/view/123"),
            ATS_LINKEDIN,
        )

    def test_unknown_is_career_site(self):
        self.assertEqual(
            detect_ats("https://careers.example.com/jobs/123"),
            ATS_CAREER_SITE,
        )


if __name__ == "__main__":
    unittest.main()
