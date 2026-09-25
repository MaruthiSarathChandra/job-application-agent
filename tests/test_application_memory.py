import sqlite3
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
                sensitive_questions = [
                    "Will you now or in the future require sponsorship?",
                    "Are you currently authorized to work in the Country to which you are applying to work?",
                    "Do you have a conflict of interest?",
                    "Do you have an outside business activity or financial interest?",
                    "Are you or any member of your family an official of a State, Local, or Federal government?",
                ]
                for question in sensitive_questions:
                    self.assertFalse(
                        memory.remember_confirmed(question, "Yes", ats="avature")
                    )
                self.assertEqual(memory.stats()["stored"], 0)
            finally:
                memory.close()

    def test_placeholder_answers_are_not_stored(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "memory.db")
            memory = ApplicationMemory(db)
            try:
                self.assertFalse(
                    memory.remember_confirmed(
                        "Are you a commutable distance to the city listed on the role?",
                        "Select an option",
                        ats="avature",
                    )
                )
                self.assertEqual(memory.stats()["stored"], 0)
            finally:
                memory.close()

    def test_legacy_placeholder_rows_are_purged_on_open(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "memory.db")
            memory = ApplicationMemory(db)
            memory.close()

            conn = sqlite3.connect(db)
            try:
                conn.execute(
                    """
                    INSERT INTO learned_answers (
                        question_key, normalized_question, company, ats, answer,
                        category, confirmations, first_seen_at, last_confirmed_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "legacy-key",
                        "are you a commutable distance",
                        "",
                        "avature",
                        "Select an option",
                        "user_confirmed",
                        1,
                        "2026-01-01T00:00:00+00:00",
                        "2026-01-01T00:00:00+00:00",
                    ),
                )
                conn.commit()
            finally:
                conn.close()

            reopened = ApplicationMemory(db)
            try:
                self.assertEqual(reopened.stats()["stored"], 0)
            finally:
                reopened.close()

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
