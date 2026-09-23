from __future__ import annotations

from typing import Dict, List

from agent.engine import ApplicationEngine
from browser.form_filler import (
    click_prompt_item,
    close_workday_prompt,
    collect_fields,
    get_visible_prompt_items,
    normalize_text,
)
from learning.application_memory import ApplicationMemory


GENERIC_LABELS = {
    "",
    "select one",
    "select one required",
    "search",
    "required",
}

NAV_LABELS = {
    "back",
    "save and continue",
    "next",
    "continue",
    "submit",
}


def _visible(element) -> bool:
    try:
        return element.is_visible()
    except Exception:
        return False


def _clean_question_text(text: str) -> str:
    if not text:
        return ""

    lines = [
        " ".join(line.strip().split())
        for line in str(text).splitlines()
        if line.strip()
    ]

    ignored = {
        "select one",
        "required",
        "yes",
        "no",
        "back",
        "save and continue",
        "next",
        "settings",
        "english",
    }

    kept = []
    for line in lines:
        normalized = normalize_text(line).replace("*", "").strip()
        if normalized in ignored:
            continue
        if normalized.startswith("selected:"):
            continue
        kept.append(line)

    if not kept:
        return ""

    # Prefer question-like text over option values. This prevents an open
    # Workday prompt from turning values such as company names into questions.
    for line in kept:
        if "?" in line and len(line) >= 8:
            return line[:1200]

    for line in kept:
        normalized = normalize_text(line)
        if any(
            phrase in normalized
            for phrase in (
                "are you ",
                "do you ",
                "have you ",
                "what is ",
                "please select",
                "please enter",
                "how many",
                "how did",
                "will you ",
            )
        ):
            return line[:1200]

    for line in kept:
        if len(line) >= 12:
            return line[:1200]

    return kept[0][:1200]


def _is_prompt_internal(field) -> bool:
    element = field.get("_element")
    if element is None:
        return False

    try:
        return bool(
            element.evaluate(
                """
                el => Boolean(
                    el.closest('[role="option"]') ||
                    el.closest('[data-automation-id="promptOption"]') ||
                    el.closest('[data-automation-id="menuItem"]')
                )
                """
            )
        )
    except Exception:
        return False


def question_for_field(field) -> str:
    label = str(field.get("label") or "").strip()
    normalized_label = normalize_text(label).replace("*", "").strip()

    # A normal full label is usually the safest source.
    if (
        normalized_label not in GENERIC_LABELS
        and normalized_label not in NAV_LABELS
        and len(normalized_label) >= 8
    ):
        return label

    element = field.get("_element")
    if element is None:
        return label

    try:
        text = element.evaluate(
            """
            el => {
                let node = el;
                for (let i = 0; i < 8 && node; i++, node = node.parentElement) {
                    const t = (node.innerText || '').trim();
                    if (t && t.length > 5 && t.length < 1800) return t;
                }
                return '';
            }
            """
        )
        cleaned = _clean_question_text(text)
        if cleaned:
            return cleaned
    except Exception:
        pass

    return label or "UNKNOWN QUESTION"


def _current_text(element) -> str:
    try:
        tag = element.evaluate("el => el.tagName.toLowerCase()")
    except Exception:
        tag = ""

    if tag in {"input", "textarea", "select"}:
        try:
            return str(element.input_value()).strip()
        except Exception:
            return ""

    try:
        return str(element.inner_text()).strip()
    except Exception:
        return ""


def _select_workday_option(page, field, desired: str) -> bool:
    element = field["_element"]
    frame = field["_frame"]
    desired_norm = normalize_text(desired)
    if not desired_norm:
        return False

    current = normalize_text(_current_text(element))
    if current == desired_norm or (
        desired_norm in current and "select one" not in current
    ):
        return True

    close_workday_prompt(page)

    try:
        element.click(timeout=3500)
    except Exception:
        try:
            element.click(force=True, timeout=3500)
        except Exception:
            return False

    page.wait_for_timeout(350)
    options = get_visible_prompt_items(frame)

    for text, option in options:
        if normalize_text(text) == desired_norm:
            return click_prompt_item(page, option)

    aliases = {
        "yes": {"yes", "y"},
        "no": {"no", "n"},
        "i prefer not to answer": {
            "i prefer not to answer",
            "i do not want to answer",
            "decline to self-identify",
        },
    }
    allowed = aliases.get(desired_norm, {desired_norm})

    for text, option in options:
        if normalize_text(text) in allowed:
            return click_prompt_item(page, option)

    close_workday_prompt(page)
    return False


def _click_radio(field, desired: str) -> bool:
    element = field["_element"]
    frame = field["_frame"]
    desired_norm = normalize_text(desired)

    try:
        field_value = normalize_text(element.get_attribute("value") or "")
        aria = normalize_text(element.get_attribute("aria-label") or "")
        label = normalize_text(field.get("label") or "")
    except Exception:
        field_value = aria = label = ""

    if desired_norm in {"yes", "no"}:
        truthy = desired_norm == "yes"
        expected = {"true", "yes", "1"} if truthy else {"false", "no", "0"}
        matches = field_value in expected or aria == desired_norm or label == desired_norm
    else:
        matches = desired_norm in {field_value, aria, label}
        if not matches:
            matches = desired_norm and (
                desired_norm in aria or desired_norm in label
            )

    if not matches:
        return False

    try:
        if element.is_checked():
            return True
    except Exception:
        pass

    element_id = None
    try:
        element_id = element.get_attribute("id")
    except Exception:
        pass

    if element_id:
        try:
            label_el = frame.locator(f'label[for="{element_id}"]')
            if label_el.count() and label_el.first.is_visible():
                label_el.first.click(timeout=2500)
                return True
        except Exception:
            pass

    try:
        element.click(timeout=2500)
        return True
    except Exception:
        try:
            element.evaluate("el => el.click()")
            return True
        except Exception:
            return False


def _fill_text(field, value: str) -> bool:
    element = field["_element"]
    current = _current_text(element)
    if current:
        return True

    try:
        element.fill(str(value))
        return True
    except Exception:
        return False


def _is_navigation_or_search(field) -> bool:
    label = normalize_text(field.get("label") or "")
    field_id = normalize_text(field.get("id") or "")
    placeholder = ""
    try:
        placeholder = normalize_text(field["_element"].get_attribute("placeholder") or "")
    except Exception:
        pass

    if label in NAV_LABELS:
        return True
    if field_id.startswith("pagefooter") or "backtojobposting" in field_id:
        return True
    if placeholder == "search" and not field.get("required"):
        return True
    if _is_prompt_internal(field):
        return True
    return False


def fill_generic_questions(
    page,
    profile,
    job_text: str = "",
    company: str = "",
    ats: str = "workday",
    memory=None,
) -> Dict:
    """
    Fill only answers backed by locked profile facts, repeatedly confirmed
    non-sensitive memory, or a high-confidence LLM decision.

    Sensitive/legal/immigration/salary/demographic questions remain REVIEW.
    """

    # Close any leftover prompt from the previous wizard section before field
    # discovery. This was the cause of option values being interpreted as
    # standalone questions in earlier State Street runs.
    close_workday_prompt(page)
    page.wait_for_timeout(150)

    owns_memory = memory is None
    if owns_memory:
        memory = ApplicationMemory()

    engine = ApplicationEngine(
        profile,
        use_llm=True,
        memory=memory,
        company=company,
        ats=ats,
    )
    fields = collect_fields(page)

    handled = 0
    blockers: List[Dict] = []
    decisions: List[Dict] = []
    seen_questions = set()

    try:
        for field in fields:
            if _is_navigation_or_search(field):
                continue
            if not _visible(field["_element"]):
                continue

            question = question_for_field(field)
            question_norm = normalize_text(question)

            if not question_norm or question_norm in GENERIC_LABELS:
                if field.get("required"):
                    blockers.append({
                        "question": question or "UNKNOWN QUESTION",
                        "reason": "Could not identify the question text safely.",
                        "category": "unknown_required_field",
                    })
                continue

            decision = engine.answer_question(question, job_text=job_text)

            if question_norm not in seen_questions:
                decisions.append(decision.to_dict())
                seen_questions.add(question_norm)

            if decision.review_required or decision.answer is None:
                if field.get("required") and not any(
                    normalize_text(item.get("question")) == question_norm
                    for item in blockers
                ):
                    blockers.append({
                        "question": question,
                        "reason": decision.rationale,
                        "category": decision.category,
                    })
                continue

            answer = str(decision.answer).strip()
            tag = normalize_text(field.get("tag") or "")
            role = normalize_text(field.get("role") or "")
            field_type = normalize_text(field.get("type") or "")
            popup = normalize_text(field.get("aria_haspopup") or "")

            success = False
            if field_type in {"radio", "checkbox"} or role in {"radio", "checkbox"}:
                success = _click_radio(field, answer)
            elif tag == "button" or role == "combobox" or popup == "listbox":
                success = _select_workday_option(page, field, answer)
            elif tag in {"input", "textarea"} or role == "textbox":
                success = _fill_text(field, answer)

            if success:
                handled += 1
                print(
                    f"ANSWERED               {decision.category:24} "
                    f"{question[:100]} -> {answer}"
                )
            elif field.get("required"):
                blockers.append({
                    "question": question,
                    "reason": f"Safe answer '{answer}' was available but the control could not be filled.",
                    "category": decision.category,
                })
    finally:
        if owns_memory:
            memory.close()

    unique = []
    seen = set()
    for blocker in blockers:
        key = (
            normalize_text(blocker.get("question")),
            normalize_text(blocker.get("category")),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(blocker)

    return {
        "handled_count": handled,
        "blockers": unique,
        "decisions": decisions,
        "ready": not unique,
    }
