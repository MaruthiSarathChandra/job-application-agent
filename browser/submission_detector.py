from __future__ import annotations

from typing import Iterable


SUCCESS_MARKERS = (
    "application submitted",
    "application has been submitted",
    "your application has been submitted",
    "thank you for applying",
    "thanks for applying",
    "thank you for your application",
    "we have received your application",
    "we received your application",
    "application received",
    "application successfully submitted",
)

NEGATIVE_MARKERS = (
    "submit application",
    "review your application",
    "application not submitted",
    "submission failed",
)


def normalize_text(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def confirmation_from_text(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return False

    if any(marker in normalized for marker in NEGATIVE_MARKERS):
        # A real success sentence may coexist with a footer containing
        # "Submit application". In that case prefer an explicit success marker.
        explicit = (
            "your application has been submitted",
            "application successfully submitted",
            "thank you for applying",
            "thanks for applying",
            "thank you for your application",
            "we have received your application",
            "we received your application",
        )
        return any(marker in normalized for marker in explicit)

    return any(marker in normalized for marker in SUCCESS_MARKERS)


def detect_submission_confirmation(page) -> bool:
    """Return True only when a visible page contains a strong submission-success marker."""
    texts = []
    for frame in page.frames:
        try:
            body = frame.locator("body")
            if body.count() and body.first.is_visible():
                texts.append(body.first.inner_text(timeout=1200))
        except Exception:
            continue

    return confirmation_from_text("\n".join(texts))
