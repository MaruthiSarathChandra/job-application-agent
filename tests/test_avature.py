import unittest

from browser.adapters.avature import classify_avature_page, normalize_avature_job_url


class AvatureTests(unittest.TestCase):
    def test_metlife_confirmation_link_normalizes_to_job_detail(self):
        url = (
            "https://www.metlifecareers.com/en_US/ml/ApplicationConfirmation?"
            "jobId=18437&recommendation=&source=LinkedIn&tags=&user=&formValues="
        )
        self.assertEqual(
            normalize_avature_job_url(url),
            "https://www.metlifecareers.com/en_US/ml/JobDetail?jobId=18437&source=LinkedIn",
        )

    def test_normal_job_detail_is_unchanged(self):
        url = "https://www.metlifecareers.com/en_US/ml/JobDetail/Software-Engineer-Developer/18437"
        self.assertEqual(normalize_avature_job_url(url), url)

    def test_closed_page_detection(self):
        self.assertEqual(
            classify_avature_page("This position is no longer available."),
            "closed",
        )

    def test_open_page_detection(self):
        self.assertEqual(
            classify_avature_page("Software Engineer Developer Apply Now"),
            "open",
        )


if __name__ == "__main__":
    unittest.main()
