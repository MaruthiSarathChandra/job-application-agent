import unittest

from agent_v2 import _normalize_cli_url


class CliUrlNormalizationTests(unittest.TestCase):
    def test_raw_url_is_preserved(self):
        url = "https://example.wd3.myworkdayjobs.com/Careers/job/City/Role_R123"
        self.assertEqual(_normalize_cli_url(url), url)

    def test_markdown_link_is_unwrapped_to_target(self):
        raw = (
            "[https://example.wd3.myworkdayjobs.com/Careers/job/City/Role_R123]"
            "(https://example.wd3.myworkdayjobs.com/Careers/job/City/Role_R123)"
        )
        self.assertEqual(
            _normalize_cli_url(raw),
            "https://example.wd3.myworkdayjobs.com/Careers/job/City/Role_R123",
        )

    def test_angle_bracket_url_is_unwrapped(self):
        self.assertEqual(
            _normalize_cli_url("<https://example.com/jobs/123>"),
            "https://example.com/jobs/123",
        )

    def test_invalid_non_url_is_rejected(self):
        with self.assertRaises(ValueError):
            _normalize_cli_url("example.com/jobs/123")


if __name__ == "__main__":
    unittest.main()
