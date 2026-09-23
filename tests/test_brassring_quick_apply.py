import unittest

from browser.adapters.brassring import classify_brassring_page


class BrassRingQuickApplyTests(unittest.TestCase):
    def test_quick_apply_page_is_not_closed(self):
        status, _ = classify_brassring_page("Software Developer Quick Apply Job Summary")
        self.assertEqual(status, "open")


if __name__ == "__main__":
    unittest.main()
