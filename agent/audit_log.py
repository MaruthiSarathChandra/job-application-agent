import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .models import AnswerDecision, ResumeDecision


SCHEMA = """
CREATE TABLE IF NOT EXISTS applications (
    application_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    company TEXT,
    role TEXT,
    job_url TEXT,
    job_text_sha256 TEXT,
    resume_key TEXT,
    resume_label TEXT,
    resume_path TEXT,
    resume_sha256 TEXT,
    status TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    question TEXT NOT NULL,
    answer TEXT,
    source TEXT NOT NULL,
    confidence REAL NOT NULL,
    review_required INTEGER NOT NULL,
    category TEXT NOT NULL,
    rationale TEXT,
    FOREIGN KEY(application_id) REFERENCES applications(application_id)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    application_id TEXT,
    created_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
"""


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: str) -> Optional[str]:
    file_path = Path(path)
    if not file_path.exists() or not file_path.is_file():
        return None

    h = hashlib.sha256()
    with file_path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


class AuditLog:
    def __init__(self, db_path: str = "data/applications.db"):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def begin_application(
        self,
        job_text: str,
        resume: ResumeDecision,
        company: str = "",
        role: str = "",
        job_url: str = "",
    ) -> str:
        application_id = str(uuid.uuid4())

        self.conn.execute(
            """
            INSERT INTO applications (
                application_id, created_at, company, role, job_url,
                job_text_sha256, resume_key, resume_label, resume_path,
                resume_sha256, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                application_id,
                _utc_now(),
                company,
                role,
                job_url,
                sha256_text(job_text),
                resume.resume_key,
                resume.resume_label,
                resume.resume_path,
                sha256_file(resume.resume_path) if resume.resume_path else None,
                "DRY_RUN",
            ),
        )
        self.conn.commit()
        return application_id

    def log_decision(self, application_id: str, decision: AnswerDecision):
        self.conn.execute(
            """
            INSERT INTO decisions (
                application_id, created_at, question, answer, source,
                confidence, review_required, category, rationale
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                application_id,
                _utc_now(),
                decision.question,
                decision.answer,
                decision.source,
                decision.confidence,
                int(decision.review_required),
                decision.category,
                decision.rationale,
            ),
        )
        self.conn.commit()

    def log_event(self, application_id: Optional[str], event_type: str, payload):
        self.conn.execute(
            """
            INSERT INTO events (
                application_id, created_at, event_type, payload_json
            ) VALUES (?, ?, ?, ?)
            """,
            (
                application_id,
                _utc_now(),
                event_type,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        self.conn.commit()

    def set_status(self, application_id: str, status: str):
        self.conn.execute(
            "UPDATE applications SET status=? WHERE application_id=?",
            (status, application_id),
        )
        self.conn.commit()

    def close(self):
        self.conn.close()
