import unittest
from unittest.mock import patch

from browser.adapters.avature import AvatureAdapter, classify_avature_page, normalize_avature_job_url


class _Control:
    def __init__(self, tag="button", control_type="submit", text="Continue", value=""):
        self.tag = tag
        self.control_type = control_type
        self.text = text
        self.value = value

    def evaluate(self, script):
        return self.tag

    def get_attribute(self, name):
        if name == "type":
            return self.control_type
        if name == "value":
            return self.value
        if name == "aria-label":
            return None
        return None

    def inner_text(self, timeout=300):
        return self.text


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

    def test_submit_typed_continue_on_acknowledgment_page_is_guarded(self):
        control = _Control(control_type="submit", text="Continue")
        with patch.object(AvatureAdapter, "_page_text", return_value="I Acknowledge *"):
            self.assertTrue(AvatureAdapter._navigation_may_submit(object(), control))

    def test_plain_next_navigation_is_not_treated_as_submit(self):
        control = _Control(control_type="button", text="Next")
        with patch.object(AvatureAdapter, "_page_text", return_value="Application Questions"):
            self.assertFalse(AvatureAdapter._navigation_may_submit(object(), control))


if __name__ == "__main__":
    unittest.main()
