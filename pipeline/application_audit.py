from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from agent.submission_policy import REVIEW_CATEGORIES
from learning.application_memory import is_sensitive_question


SENSITIVE_KEYS = {
    "password",
    "passcode",
    "otp",
    "token",
    "secret",
    "security_code",
    "verification_code",
    "ssn",
    "social_security",
    "api_key",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_payload(value: Any):
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            key_norm = str(key).strip().lower()
            if any(secret in key_norm for secret in SENSITIVE_KEYS):
                result[str(key)] = "[REDACTED]"
            else:
                result[str(key)] = _safe_payload(item)
        return result
    if isinstance(value, (list, tuple)):
        return [_safe_payload(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


SCHEMA = """
CREATE TABLE IF NOT EXISTS application_runs (
    run_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    ats TEXT NOT NULL,
    company TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT '',
    job_url TEXT NOT NULL DEFAULT '',
    resume_path TEXT NOT NULL DEFAULT '',
    submission_mode TEXT NOT NULL DEFAULT 'manual',
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL DEFAULT 'started',
    submitted INTEGER NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS application_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    FOREIGN KEY(run_id) REFERENCES application_runs(run_id)
);

CREATE TABLE IF NOT EXISTS application_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    question TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0,
    review_required INTEGER NOT NULL DEFAULT 0,
    answer TEXT,
    answer_redacted INTEGER NOT NULL DEFAULT 0,
    rationale TEXT NOT NULL DEFAULT '',
    FOREIGN KEY(run_id) REFERENCES application_runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_application_runs_job
ON application_runs(job_id, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_application_events_run
ON application_events(run_id, created_at);
"""


class ApplicationAudit:
    """Privacy-aware local audit trail for browser application attempts."""

    def __init__(self, db_path: str = "data/application_audit.db"):
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self):
        self.conn.close()

    def begin_run(
        self,
        job_id: str,
        ats: str,
        company: str,
        role: str,
        job_url: str,
        resume_path: str,
        submission_mode: str,
    ) -> str:
        run_id = str(uuid.uuid4())
        self.conn.execute(
            """
            INSERT INTO application_runs (
                run_id, job_id, ats, company, role, job_url, resume_path,
                submission_mode, started_at, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'started')
            """,
            (
                run_id,
                job_id,
                ats or "",
                company or "",
                role or "",
                job_url or "",
                resume_path or "",
                submission_mode or "manual",
                _utc_now(),
            ),
        )
        self.conn.commit()
        return run_id

    def event(self, run_id: str, event_type: str, payload: Optional[Dict] = None):
        self.conn.execute(
            """
            INSERT INTO application_events (run_id, created_at, event_type, payload_json)
            VALUES (?, ?, ?, ?)
            """,
            (
                run_id,
                _utc_now(),
                event_type,
                json.dumps(_safe_payload(payload or {}), ensure_ascii=False),
            ),
        )
        self.conn.commit()

    def decisions(self, run_id: str, decisions: Iterable[Dict]):
        for decision in decisions or []:
            question = str(decision.get("question") or "")
            category = str(decision.get("category") or "")
            source = str(decision.get("source") or "")
            review_required = bool(decision.get("review_required"))
            answer = decision.get("answer")

            redact = (
                is_sensitive_question(question)
                or category in REVIEW_CATEGORIES
                or any(secret in source.lower() for secret in ("password", "otp", "credential"))
            )

            stored_answer = None if redact else (None if answer is None else str(answer))

            self.conn.execute(
                """
                INSERT INTO application_decisions (
                    run_id, created_at, question, category, source, confidence,
                    review_required, answer, answer_redacted, rationale
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    _utc_now(),
                    question,
                    category,
                    source,
                    float(decision.get("confidence") or 0),
                    int(review_required),
                    stored_answer,
                    int(redact),
                    str(decision.get("rationale") or ""),
                ),
            )
        self.conn.commit()

    def finish(
        self,
        run_id: str,
        status: str,
        submitted: bool,
        message: str = "",
        blockers=None,
        decisions=None,
        metadata=None,
    ):
        self.decisions(run_id, decisions or [])
        self.event(
            run_id,
            "result",
            {
                "status": status,
                "submitted": bool(submitted),
                "message": message or "",
                "blockers": blockers or [],
                "metadata": metadata or {},
            },
        )
        self.conn.execute(
            """
            UPDATE application_runs
            SET finished_at=?, status=?, submitted=?, message=?
            WHERE run_id=?
            """,
            (
                _utc_now(),
                status or "unknown",
                int(bool(submitted)),
                message or "",
                run_id,
            ),
        )
        self.conn.commit()
