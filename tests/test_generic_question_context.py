import unittest

from browser.adapters.generic_questions import _answers_equivalent, _meaningful_label


class GenericQuestionContextTests(unittest.TestCase):
    def test_generic_select_placeholder_is_not_a_question(self):
        self.assertFalse(_meaningful_label("Select"))
        self.assertFalse(_meaningful_label("Select One"))
        self.assertFalse(_meaningful_label("Search"))

    def test_real_question_remains_meaningful(self):
        self.assertTrue(_meaningful_label("Why AndHealth?"))
        self.assertTrue(_meaningful_label("Are you authorized to work in the United States?"))

    def test_decorated_answer_equivalence(self):
        self.assertTrue(_answers_equivalent("United States of America (+1)", "+1"))
        self.assertTrue(_answers_equivalent("Yes", "true"))
        self.assertFalse(_answers_equivalent("No", "Yes"))


if __name__ == "__main__":
    unittest.main()
