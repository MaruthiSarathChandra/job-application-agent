from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


# Workday commonly places an application-method chooser in front of the actual
# wizard. These controls only start/resume an application; they are not final
# submission or legal-consent controls.
MANUAL_ENTRY_NAMES = (
    "Apply Manually",
    "Apply manually",
    "Start Application",
    "Start application",
    "Start Your Application",
    "Start your application",
)

RESUME_ENTRY_NAMES = (
    "Autofill with Resume",
    "Autofill with resume",
    "Apply with Resume",
    "Apply with resume",
    "Apply Using Resume",
    "Apply using resume",
)

GENERIC_ENTRY_NAMES = (
    "Apply",
    "Apply Now",
    "Apply now",
)

# Explicitly avoid controls that can import stale answers or have a different
# semantic meaning than starting this application.
UNSAFE_ENTRY_MARKERS = (
    "submit",
    "use my last application",
    "last application",
    "employee referral",
    "refer a candidate",
)


@dataclass
class WorkdayEntryResult:
    clicked: bool = False
    action: str = ""
    resume_uploaded: bool = False
    visible_actions: List[str] | None = None


def _norm(value) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _visible(locator) -> bool:
    try:
        return locator.is_visible() and locator.is_enabled()
    except Exception:
        return False


def _click(locator) -> bool:
    try:
        locator.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass
    try:
        locator.click(timeout=5000)
        return True
    except Exception:
        try:
            locator.click(force=True, timeout=3500)
            return True
        except Exception:
            return False


def _named_action(page, names):
    for frame in page.frames:
        for name in names:
            for role in ("button", "link"):
                try:
                    controls = frame.get_by_role(role, name=name, exact=True)
                except Exception:
                    continue
                for index in range(controls.count()):
                    control = controls.nth(index)
                    if _visible(control):
                        return control, name
    return None, ""


def _automation_action(page):
    selectors = (
        '[data-automation-id="applyManually"]',
        '[data-automation-id="applyManuallyButton"]',
        '[data-automation-id="applyButton"]',
        '[data-automation-id="applyNowButton"]',
        '[data-automation-id="startApplicationButton"]',
    )
    for frame in page.frames:
        for selector in selectors:
            try:
                controls = frame.locator(selector)
            except Exception:
                continue
            for index in range(controls.count()):
                control = controls.nth(index)
                if not _visible(control):
                    continue
                try:
                    text = control.inner_text(timeout=400).strip()
                except Exception:
                    text = selector
                normalized = _norm(text)
                if any(marker in normalized for marker in UNSAFE_ENTRY_MARKERS):
                    continue
                return control, text or selector
    return None, ""


def visible_entry_actions(page, limit: int = 20) -> List[str]:
    result = []
    seen = set()
    for frame in page.frames:
        try:
            controls = frame.locator("button, a[role='button'], a")
        except Exception:
            continue
        for index in range(min(controls.count(), 120)):
            control = controls.nth(index)
            if not _visible(control):
                continue
            try:
                text = " ".join(control.inner_text(timeout=300).strip().split())
            except Exception:
                text = ""
            if not text:
                try:
                    text = str(control.get_attribute("aria-label") or "").strip()
                except Exception:
                    text = ""
            key = _norm(text)
            if not key or key in seen:
                continue
            seen.add(key)
            result.append(text)
            if len(result) >= limit:
                return result
    return result


def _upload_entry_resume(page, resume_path: str) -> bool:
    value = str(resume_path or "").strip()
    if not value:
        return False
    path = Path(value)
    if not path.is_absolute():
        path = path.resolve()
    if not path.exists() or not path.is_file():
        return False

    for frame in page.frames:
        try:
            inputs = frame.locator('input[type="file"]')
        except Exception:
            continue
        for index in range(inputs.count()):
            element = inputs.nth(index)
            try:
                element.set_input_files(str(path))
                page.wait_for_timeout(900)
                return True
            except Exception:
                continue
    return False


def advance_workday_entry(page, resume_path: str = "") -> WorkdayEntryResult:
    """
    Advance one safe pre-wizard Workday entry transition.

    Preference order is Apply Manually -> resume-based entry -> generic Apply.
    Apply Manually is preferred because the main Workday adapter already owns
    resume upload and profile filling, making tenant behavior more consistent.
    """
    visible = visible_entry_actions(page)

    control, action = _named_action(page, MANUAL_ENTRY_NAMES)
    mode = "manual"
    if control is None:
        control, action = _named_action(page, RESUME_ENTRY_NAMES)
        mode = "resume"
    if control is None:
        control, action = _automation_action(page)
        mode = "generic"
    if control is None:
        control, action = _named_action(page, GENERIC_ENTRY_NAMES)
        mode = "generic"

    if control is None:
        return WorkdayEntryResult(
            clicked=False,
            visible_actions=visible,
        )

    normalized = _norm(action)
    if any(marker in normalized for marker in UNSAFE_ENTRY_MARKERS):
        return WorkdayEntryResult(
            clicked=False,
            visible_actions=visible,
        )

    if not _click(control):
        return WorkdayEntryResult(
            clicked=False,
            action=action,
            visible_actions=visible,
        )

    try:
        page.wait_for_timeout(900)
    except Exception:
        pass

    uploaded = False
    if mode == "resume":
        uploaded = _upload_entry_resume(page, resume_path)

    return WorkdayEntryResult(
        clicked=True,
        action=action,
        resume_uploaded=uploaded,
        visible_actions=visible,
    )
