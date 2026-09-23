from __future__ import annotations

import re
from typing import Dict, Tuple


KNOWN_STEPS = {
    "my information": "my_information",
    "my experience": "my_experience",
    "application questions 1 of 2": "application_questions_1",
    "application questions 2 of 2": "application_questions_2",
    "voluntary disclosures": "voluntary_disclosures",
    "self identify": "self_identify",
    "review": "review",
}


def normalize(value) -> str:
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


def _visible_text(locator, timeout=800) -> str:
    try:
        if not locator.is_visible():
            return ""
        return locator.inner_text(timeout=timeout).strip()
    except Exception:
        return ""


def _step_from_text(text: str) -> str | None:
    normalized = normalize(text)
    for label in sorted(KNOWN_STEPS, key=len, reverse=True):
        if label in normalized:
            return KNOWN_STEPS[label]
    return None


def _current_step_from_aria(page) -> Tuple[str | None, str]:
    selectors = [
        '[aria-current="step"]',
        '[aria-current="true"]',
    ]

    for frame in page.frames:
        for selector in selectors:
            try:
                items = frame.locator(selector)
            except Exception:
                continue

            for index in range(min(items.count(), 30)):
                item = items.nth(index)
                try:
                    if not item.is_visible():
                        continue
                except Exception:
                    continue

                texts = []
                own = _visible_text(item)
                if own:
                    texts.append(own)

                for attr in ("aria-label", "title"):
                    try:
                        value = item.get_attribute(attr)
                    except Exception:
                        value = None
                    if value:
                        texts.append(value)

                try:
                    ancestor_text = item.evaluate(
                        """
                        el => {
                            let node = el;
                            for (let i = 0; i < 6 && node; i++, node = node.parentElement) {
                                const t = (node.innerText || "").trim();
                                if (t && t.length < 700) return t;
                            }
                            return "";
                        }
                        """
                    )
                except Exception:
                    ancestor_text = ""

                if ancestor_text:
                    texts.append(ancestor_text)

                evidence = " | ".join(texts)
                step = _step_from_text(evidence)
                if step:
                    return step, f"aria-current: {evidence[:300]}"

    return None, ""


def _current_step_from_progress_text(page) -> Tuple[str | None, str]:
    """
    Extract only the label immediately after Workday's "current step X of Y"
    marker. Future step labels in the sidebar are never treated as active.
    """
    for frame in page.frames:
        try:
            body = frame.locator("body")
            if body.count() == 0:
                continue
            text = body.inner_text(timeout=1500)
        except Exception:
            continue

        if not text:
            continue

        lines = [line.strip() for line in text.splitlines() if line.strip()]

        for index, line in enumerate(lines):
            if not re.search(r"\bcurrent\s+step\s+\d+\s+of\s+\d+\b", line, re.I):
                continue

            for candidate in lines[index + 1:index + 6]:
                step = _step_from_text(candidate)
                if step:
                    return step, f"progress text: {line} -> {candidate}"

    return None, ""


def _main_regions(frame):
    selectors = [
        "main",
        '[role="main"]',
        '[data-automation-id="jobApplicationPage"]',
        '[data-automation-id="applicationPage"]',
        "form",
    ]

    for selector in selectors:
        try:
            loc = frame.locator(selector)
        except Exception:
            continue

        for index in range(min(loc.count(), 10)):
            region = loc.nth(index)
            try:
                if not region.is_visible():
                    continue
            except Exception:
                continue
            yield region


def _step_from_main_content(page) -> Tuple[str | None, str]:
    strong_markers = [
        (
            "application_questions_1",
            "Are you a relative of a current Public Official",
        ),
        (
            "my_information",
            "How Did You Hear About Us",
        ),
    ]

    for frame in page.frames:
        for region in _main_regions(frame):
            text = _visible_text(region, timeout=1200)
            if not text:
                continue

            normalized = normalize(text)

            for step, marker in strong_markers:
                if normalize(marker) in normalized:
                    return step, f"main marker: {marker}"

            if (
                "work experience" in normalized
                and (
                    "school or university" in normalized
                    or "education" in normalized
                    or "resume" in normalized
                )
            ):
                return "my_experience", "main marker: Work Experience + Education/Resume"

            for label in sorted(KNOWN_STEPS, key=len, reverse=True):
                if label in normalized:
                    return KNOWN_STEPS[label], f"main region label: {label}"

    return None, ""


def _step_from_controls(page) -> Tuple[str | None, str]:
    for frame in page.frames:
        try:
            previous = frame.locator('input[name="candidateIsPreviousWorker"]')
            for index in range(previous.count()):
                if previous.nth(index).is_visible():
                    return "my_information", "control marker: candidateIsPreviousWorker"
        except Exception:
            pass

        try:
            file_inputs = frame.locator('input[type="file"]')
            if file_inputs.count() > 0:
                text = normalize(_visible_text(frame.locator("body").first, timeout=1200))
                if "work experience" in text and "education" in text:
                    return "my_experience", "control marker: resume + experience"
        except Exception:
            pass

        try:
            submit = frame.get_by_role("button", name="Submit", exact=True)
            for index in range(submit.count()):
                if submit.nth(index).is_visible():
                    return "review", "control marker: visible Submit"
        except Exception:
            pass

    return None, ""


def detect_current_step(page) -> Dict[str, str]:
    detectors = (
        _current_step_from_aria,
        _current_step_from_progress_text,
        _step_from_main_content,
        _step_from_controls,
    )

    for detector in detectors:
        try:
            step, evidence = detector(page)
        except Exception as exc:
            step, evidence = None, f"{detector.__name__} failed: {exc}"

        if step:
            return {"step": step, "evidence": evidence}

    return {
        "step": "unknown",
        "evidence": "No active Workday step could be identified.",
    }


def wizard_controls_visible(page) -> bool:
    selectors = [
        '[data-automation-id="pageFooterNextButton"]',
        '[data-automation-id="pageFooterBackButton"]',
    ]

    for frame in page.frames:
        for selector in selectors:
            try:
                items = frame.locator(selector)
                for index in range(items.count()):
                    if items.nth(index).is_visible():
                        return True
            except Exception:
                continue

    for frame in page.frames:
        for name in ("Save and Continue", "Next", "Back"):
            try:
                items = frame.get_by_role("button", name=name, exact=True)
                for index in range(items.count()):
                    if items.nth(index).is_visible():
                        return True
            except Exception:
                continue

    return False


def wait_for_application_step(page, timeout_ms=30000) -> Dict[str, str]:
    interval = 500
    elapsed = 0
    previous = None
    stable = 0
    last = {"step": "unknown", "evidence": "Not checked yet."}

    while elapsed < timeout_ms:
        last = detect_current_step(page)
        step = last["step"]

        if step != "unknown" and (wizard_controls_visible(page) or step == "review"):
            if step == previous:
                stable += 1
            else:
                previous = step
                stable = 1

            if stable >= 2:
                return last
        else:
            previous = None
            stable = 0

        page.wait_for_timeout(interval)
        elapsed += interval

    return last


def wait_for_step_change(page, old_step: str, timeout_ms=20000) -> Dict[str, str]:
    interval = 500
    elapsed = 0
    candidate = None
    stable = 0
    last = {"step": old_step, "evidence": "Waiting for navigation."}

    while elapsed < timeout_ms:
        last = detect_current_step(page)
        step = last["step"]

        if step != "unknown" and step != old_step:
            if step == candidate:
                stable += 1
            else:
                candidate = step
                stable = 1

            if stable >= 2:
                return last
        else:
            candidate = None
            stable = 0

        page.wait_for_timeout(interval)
        elapsed += interval

    return last
