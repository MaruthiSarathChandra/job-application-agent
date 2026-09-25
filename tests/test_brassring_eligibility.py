import unittest

from browser.adapters.brassring import classify_brassring_requirements


class BrassRingEligibilityTests(unittest.TestCase):
    def test_detects_us_citizenship_required(self):
        text = """
        Experience Level\nEntry-Level (0-2 years)\n
        US Citizenship Required?\nYes\n
        Clearance Required?\nDesired\n
        Clearance Level\nSecret
        """
        result = classify_brassring_requirements(text)
        self.assertTrue(result["us_citizenship_required"])
        self.assertFalse(result["clearance_required"])
        self.assertEqual(result["clearance_level"], "Secret")

    def test_detects_required_clearance(self):
        result = classify_brassring_requirements(
            "Clearance Required? Yes\nClearance Level\nSecret"
        )
        self.assertTrue(result["clearance_required"])
        self.assertEqual(result["clearance_level"], "Secret")

    def test_desired_clearance_is_not_hard_requirement(self):
        result = classify_brassring_requirements(
            "Clearance Required? Desired\nClearance Level\nSecret"
        )
        self.assertFalse(result["clearance_required"])

    def test_plain_job_page_has_no_hard_requirement(self):
        result = classify_brassring_requirements("Software Developer\nApply to job")
        self.assertFalse(result["us_citizenship_required"])
        self.assertFalse(result["clearance_required"])


if __name__ == "__main__":
    unittest.main()
