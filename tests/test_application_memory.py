import tempfile
import unittest
from pathlib import Path

from learning.application_memory import ApplicationMemory


class ApplicationMemoryTests(unittest.TestCase):
    def test_requires_repeated_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "memory.db")
            memory = ApplicationMemory(db)
            try:
                question = "Are you willing to relocate for this role?"
                self.assertTrue(memory.remember_confirmed(question, "Yes", ats="workday"))
                self.assertIsNone(memory.lookup(question, ats="workday", min_confirmations=2))
                self.assertTrue(memory.remember_confirmed(question, "Yes", ats="workday"))
                result = memory.lookup(question, ats="workday", min_confirmations=2)
                self.assertIsNotNone(result)
                self.assertEqual(result.answer, "Yes")
            finally:
                memory.close()

    def test_sensitive_questions_are_not_stored(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "memory.db")
            memory = ApplicationMemory(db)
            try:
                self.assertFalse(
                    memory.remember_confirmed(
                        "Will you now or in the future require sponsorship?",
                        "Yes",
                        ats="workday",
                    )
                )
                self.assertEqual(memory.stats()["stored"], 0)
            finally:
                memory.close()

    def test_conservative_fuzzy_reuse(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "memory.db")
            memory = ApplicationMemory(db)
            try:
                q1 = "Are you willing to relocate for this role?"
                q2 = "Are you willing to relocate for the role?"
                memory.remember_confirmed(q1, "Yes", company="Acme", ats="workday")
                memory.remember_confirmed(q1, "Yes", company="Acme", ats="workday")
                result = memory.lookup(q2, company="Acme", ats="workday")
                self.assertIsNotNone(result)
                self.assertEqual(result.answer, "Yes")
                self.assertGreaterEqual(result.similarity, 0.94)
            finally:
                memory.close()


if __name__ == "__main__":
    unittest.main()
