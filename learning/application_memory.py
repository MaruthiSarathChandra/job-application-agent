import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


SENSITIVE_PATTERNS = [
    r"password",
    r"passcode",
    r"one[- ]?time",
    r"otp",
    r"verification code",
    r"security code",
    r"social security",
    r"\bssn\b",
    r"bank account",
    r"routing number",
    r"credit card",
    r"disability",
    r"race",
    r"ethnicity",
    r"gender",
    r"veteran",
]


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def normalize_question(question: str) -> str:
    value = " ".join((question or "").strip().lower().split())
    value = re.sub(r"\brequired\b", "", value)
    value = value.replace("*", "")
    return " ".join(value.split())


def question_key(question: str) -> str:
    return hashlib.sha256(normalize_question(question).encode("utf-8")).hexdigest()


def is_sensitive_question(question: str) -> bool:
    q = normalize_question(question)
    return any(re.search(pattern, q) for pattern in SENSITIVE_PATTERNS)


SCHEMA = """
CREATE TABLE IF NOT EXISTS learned_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    question_key TEXT NOT NULL,
    normalized_question TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '',
    ats TEXT NOT NULL DEFAULT '',
    answer TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT 'general',
    confirmations INTEGER NOT NULL DEFAULT 1,
    first_seen_at TEXT NOT NULL,
    last_confirmed_at TEXT NOT NULL,
    UNIQUE(question_key, company, ats, answer)
);
CREATE INDEX IF NOT EXISTS idx_learned_answers_lookup
ON learned_answers(question_key, company, ats, confirmations);
"""


@dataclass
class LearnedAnswer:
    question: str
    answer: str
    company: str
    ats: str
    confirmations: int
    category: str


class ApplicationMemory:
    """
    Stores only answers the user has explicitly confirmed in a real form.

    Passwords, OTP/MFA codes, financial identifiers and sensitive demographic
    answers are intentionally excluded from this memory.
    """

    def __init__(self, db_path: str = "data/application_memory.db"):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def remember_confirmed(
        self,
        question: str,
        answer: str,
        company: str = "",
        ats: str = "",
        category: str = "general",
    ) -> bool:
        question = (question or "").strip()
        answer = (answer or "").strip()
        if not question or not answer or is_sensitive_question(question):
            return False

        key = question_key(question)
        normalized = normalize_question(question)
        now = _utc_now()

        row = self.conn.execute(
            """
            SELECT id, confirmations
            FROM learned_answers
            WHERE question_key=? AND company=? AND ats=? AND answer=?
            """,
            (key, company, ats, answer),
        ).fetchone()

        if row:
            self.conn.execute(
                """
                UPDATE learned_answers
                SET confirmations=?, last_confirmed_at=?, category=?
                WHERE id=?
                """,
                (int(row[1]) + 1, now, category, int(row[0])),
            )
        else:
            self.conn.execute(
                """
                INSERT INTO learned_answers (
                    question_key, normalized_question, company, ats, answer,
                    category, confirmations, first_seen_at, last_confirmed_at
                ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (key, normalized, company, ats, answer, category, now, now),
            )

        self.conn.commit()
        return True

    def lookup(
        self,
        question: str,
        company: str = "",
        ats: str = "",
        min_confirmations: int = 2,
    ) -> Optional[LearnedAnswer]:
        if is_sensitive_question(question):
            return None

        key = question_key(question)
        candidates = self.conn.execute(
            """
            SELECT answer, company, ats, confirmations, category
            FROM learned_answers
            WHERE question_key=?
              AND confirmations>=?
            ORDER BY
              CASE WHEN company=? AND ats=? THEN 0
                   WHEN company=? THEN 1
                   WHEN ats=? THEN 2
                   ELSE 3 END,
              confirmations DESC,
              last_confirmed_at DESC
            """,
            (key, min_confirmations, company, ats, company, ats),
        ).fetchall()

        if not candidates:
            return None

        answer, row_company, row_ats, confirmations, category = candidates[0]
        return LearnedAnswer(
            question=question,
            answer=answer,
            company=row_company,
            ats=row_ats,
            confirmations=int(confirmations),
            category=category,
        )

    def close(self):
        self.conn.close()
