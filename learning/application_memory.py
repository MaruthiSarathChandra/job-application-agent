import hashlib
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
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
    r"criminal",
    r"felony",
    r"security clearance",
    r"citizen",
    r"citizenship",
    r"sponsorship",
    r"work authorization",
    r"salary",
    r"compensation",
    r"public official",
    r"attest",
    r"certify",
]


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def normalize_question(question: str) -> str:
    value = " ".join((question or "").strip().lower().split())
    value = re.sub(r"\brequired\b", "", value)
    value = value.replace("*", "")
    value = re.sub(r"[^a-z0-9+#. ]+", " ", value)
    return " ".join(value.split())


def question_key(question: str) -> str:
    return hashlib.sha256(normalize_question(question).encode("utf-8")).hexdigest()


def is_sensitive_question(question: str) -> bool:
    q = normalize_question(question)
    return any(re.search(pattern, q) for pattern in SENSITIVE_PATTERNS)


def question_similarity(a: str, b: str) -> float:
    a_norm = normalize_question(a)
    b_norm = normalize_question(b)
    if not a_norm or not b_norm:
        return 0.0
    if a_norm == b_norm:
        return 1.0

    seq = SequenceMatcher(None, a_norm, b_norm).ratio()
    a_tokens = set(a_norm.split())
    b_tokens = set(b_norm.split())
    union = a_tokens | b_tokens
    jaccard = len(a_tokens & b_tokens) / len(union) if union else 0.0
    return round((seq * 0.65) + (jaccard * 0.35), 4)


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
CREATE INDEX IF NOT EXISTS idx_learned_answers_context
ON learned_answers(company, ats, confirmations);
"""


@dataclass
class LearnedAnswer:
    question: str
    answer: str
    company: str
    ats: str
    confirmations: int
    category: str
    similarity: float = 1.0


class ApplicationMemory:
    """
    Stores only answers the user explicitly confirms in a real form.

    High-risk answers are intentionally excluded. Exact matches are preferred.
    Fuzzy reuse is conservative and only activates after repeated confirmation.
    """

    def __init__(self, db_path: str = "data/application_memory.db"):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
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
        company = (company or "").strip()
        ats = (ats or "").strip().lower()

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
                (int(row["confirmations"]) + 1, now, category, int(row["id"])),
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

    def _to_answer(self, question: str, row, similarity: float) -> LearnedAnswer:
        return LearnedAnswer(
            question=question,
            answer=row["answer"],
            company=row["company"],
            ats=row["ats"],
            confirmations=int(row["confirmations"]),
            category=row["category"],
            similarity=similarity,
        )

    def lookup(
        self,
        question: str,
        company: str = "",
        ats: str = "",
        min_confirmations: int = 2,
        fuzzy_threshold: float = 0.94,
    ) -> Optional[LearnedAnswer]:
        if is_sensitive_question(question):
            return None

        key = question_key(question)
        company = (company or "").strip()
        ats = (ats or "").strip().lower()

        exact = self.conn.execute(
            """
            SELECT answer, company, ats, confirmations, category,
                   normalized_question, last_confirmed_at
            FROM learned_answers
            WHERE question_key=? AND confirmations>=?
            ORDER BY
              CASE WHEN company=? AND ats=? THEN 0
                   WHEN company=? THEN 1
                   WHEN ats=? THEN 2
                   ELSE 3 END,
              confirmations DESC,
              last_confirmed_at DESC
            LIMIT 1
            """,
            (key, min_confirmations, company, ats, company, ats),
        ).fetchone()

        if exact:
            return self._to_answer(question, exact, 1.0)

        rows = self.conn.execute(
            """
            SELECT answer, company, ats, confirmations, category,
                   normalized_question, last_confirmed_at
            FROM learned_answers
            WHERE confirmations>=?
            ORDER BY confirmations DESC, last_confirmed_at DESC
            LIMIT 500
            """,
            (min_confirmations,),
        ).fetchall()

        scored = []
        for row in rows:
            similarity = question_similarity(question, row["normalized_question"])
            if similarity < fuzzy_threshold:
                continue

            context_rank = (
                0 if row["company"] == company and row["ats"] == ats and (company or ats)
                else 1 if company and row["company"] == company
                else 2 if ats and row["ats"] == ats
                else 3
            )
            scored.append((context_rank, -int(row["confirmations"]), -similarity, row))

        if not scored:
            return None

        scored.sort(key=lambda item: (item[0], item[1], item[2]))
        best = scored[0]
        best_row = best[3]
        best_similarity = -best[2]

        # If similarly strong memories disagree, require review instead of reuse.
        conflicting = {
            row[3]["answer"]
            for row in scored
            if row[0] == best[0] and (-row[2]) >= best_similarity - 0.015
        }
        if len(conflicting) > 1:
            return None

        return self._to_answer(question, best_row, best_similarity)

    def stats(self):
        total = self.conn.execute("SELECT COUNT(*) AS n FROM learned_answers").fetchone()["n"]
        reusable = self.conn.execute(
            "SELECT COUNT(*) AS n FROM learned_answers WHERE confirmations>=2"
        ).fetchone()["n"]
        return {"stored": int(total), "reusable": int(reusable)}

    def close(self):
        self.conn.close()
