import unittest

from pipeline.job_sources import infer_source, workday_board_parts


class JobSourceTests(unittest.TestCase):
    def test_workday_board_parts_without_locale(self):
        host, tenant, site, locale, remainder = workday_board_parts(
            "https://statestreet.wd1.myworkdayjobs.com/Global"
        )
        self.assertEqual(host, "statestreet.wd1.myworkdayjobs.com")
        self.assertEqual(tenant, "statestreet")
        self.assertEqual(site, "Global")
        self.assertEqual(locale, "en-US")
        self.assertEqual(remainder, [])

    def test_workday_job_parts_with_locale(self):
        host, tenant, site, locale, remainder = workday_board_parts(
            "https://nvidia.wd5.myworkdayjobs.com/en-US/NVIDIAExternalCareerSite/job/US-CA/Software-Engineer_R123"
        )
        self.assertEqual(tenant, "nvidia")
        self.assertEqual(site, "NVIDIAExternalCareerSite")
        self.assertEqual(locale, "en-US")
        self.assertEqual(remainder[0], "job")

    def test_infer_workday(self):
        self.assertEqual(
            infer_source("https://example.wd3.myworkdayjobs.com/Careers"),
            "workday",
        )

    def test_non_workday_rejected(self):
        with self.assertRaises(ValueError):
            workday_board_parts("https://example.com/jobs")


if __name__ == "__main__":
    unittest.main()
