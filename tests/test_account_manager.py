import unittest

from browser.account_manager import site_key


class AccountManagerTests(unittest.TestCase):
    def test_workday_site_key_ignores_locale(self):
        a = site_key("https://statestreet.wd1.myworkdayjobs.com/Global/apply")
        b = site_key("https://statestreet.wd1.myworkdayjobs.com/en-US/Global/apply")
        self.assertEqual(a, b)
        self.assertEqual(a, "statestreet.wd1.myworkdayjobs.com/global")

    def test_non_workday_uses_host(self):
        self.assertEqual(
            site_key("https://jobs.example.com/apply/123"),
            "jobs.example.com",
        )


if __name__ == "__main__":
    unittest.main()
