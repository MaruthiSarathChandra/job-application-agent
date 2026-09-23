import unittest

from browser.adapters.brassring import classify_brassring_requirements


class BrassRingRequirementTests(unittest.TestCase):
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

    def test_required_clearance_is_detected(self):
        text = "Clearance Required? Yes\nClearance Level\nSecret"
        result = classify_brassring_requirements(text)
        self.assertTrue(result["clearance_required"])
        self.assertEqual(result["clearance_level"], "Secret")

    def test_no_requirement_is_safe_to_continue(self):
        result = classify_brassring_requirements("Software Developer\nApply to job")
        self.assertFalse(result["us_citizenship_required"])
        self.assertFalse(result["clearance_required"])


if __name__ == "__main__":
    unittest.main()
