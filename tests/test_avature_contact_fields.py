import unittest

from agent.answer_policy import AnswerPolicy
from browser.adapters.generic_questions import _answers_equivalent
from learning.application_memory import is_sensitive_question


class FakeProfile:
    def __init__(self):
        self.data = {
            "application_defaults": {
                "country_phone_code": "+1",
                "address_line1": "123 Example St",
                "city": "Kansas City",
                "state": "Missouri",
                "postal_code": "64100",
                "country": "United States of America",
            }
        }

    def get(self, dotted_path, default=None):
        current = self.data
        for part in dotted_path.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    def get_locked_value(self, dotted_path):
        return None


class AvatureContactFieldTests(unittest.TestCase):
    def test_phone_code_decorated_select_is_equivalent(self):
        self.assertTrue(
            _answers_equivalent("United States of America (+1)", "+1")
        )
        self.assertFalse(
            _answers_equivalent("Bahamas (+1242)", "+1")
        )

    def test_contact_fields_use_profile_not_llm(self):
        policy = AnswerPolicy(FakeProfile())

        phone = policy.answer_locked("Country Phone Code * United States of America (+1)")
        self.assertIsNotNone(phone)
        self.assertEqual(phone.answer, "+1")
        self.assertEqual(phone.source, "PROFILE")

        street = policy.answer_locked("Street Name and Number *")
        self.assertIsNotNone(street)
        self.assertEqual(street.answer, "123 Example St")
        self.assertEqual(street.category, "address")

    def test_acknowledgment_is_review_required(self):
        policy = AnswerPolicy(FakeProfile())
        decision = policy.answer_locked("I Acknowledge *")
        self.assertIsNotNone(decision)
        self.assertTrue(decision.review_required)
        self.assertEqual(decision.category, "legal_attestation")
        self.assertIsNone(decision.answer)

    def test_personal_address_and_acknowledgment_are_not_learned(self):
        self.assertTrue(is_sensitive_question("Street Name and Number *"))
        self.assertTrue(is_sensitive_question("Country Phone Code *"))
        self.assertTrue(is_sensitive_question("I Acknowledge *"))


if __name__ == "__main__":
    unittest.main()
