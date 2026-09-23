from __future__ import annotations

import re
from typing import Dict, List, Optional

from agent.engine import ApplicationEngine
from learning.application_memory import ApplicationMemory


STANDARD_NAMES = {
    "first_name",
    "firstname",
    "last_name",
    "lastname",
    "email",
    "phone",
    "phone_number",
    "location",
    "resume",
    "resume_text",
    "linkedin",
    "linkedin_url",
    "github",
    "website",
}

PLACEHOLDER_VALUES = {
    "",
    "select",
    "select one",
    "please select",
    "choose",
    "choose one",
    "--",
}

PHONE_CODE_RE = re.compile(r"(?<!\d)\+\d{1,4}(?!\d)")


def _norm(value) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _visible(element) -> bool:
    try:
        return element.is_visible()
    except Exception:
        return False


def _phone_codes(value: str):
    return set(PHONE_CODE_RE.findall(str(value or "")))


def _answers_equivalent(existing: str, answer: str) -> bool:
    """Conservative semantic equality for controls that display decorated values."""
    existing_norm = _norm(existing)
    answer_norm = _norm(answer)
    if not existing_norm or not answer_norm:
        return False
    if existing_norm == answer_norm:
        return True

    truthy = {"yes", "true", "1", "y"}
    falsy = {"no", "false", "0", "n"}
    if existing_norm in truthy and answer_norm in truthy:
        return True
    if existing_norm in falsy and answer_norm in falsy:
        return True

    existing_codes = _phone_codes(existing)
    answer_codes = _phone_codes(answer)
    if existing_codes and answer_codes and existing_codes.intersection(answer_codes):
        return True

    # Long text values are often decorated by the ATS (for example a country
    # label followed by a code). Avoid substring matching for tiny answers.
    if len(answer_norm) >= 4 and answer_norm in existing_norm:
        return True
    if len(existing_norm) >= 4 and existing_norm in answer_norm:
        return True
    return False


def _label_for(frame, element) -> str:
    for attr in ("aria-label", "data-qa", "placeholder"):
        try:
            value = element.get_attribute(attr)
        except Exception:
            value = None
        if value and len(str(value).strip()) >= 4:
            return str(value).strip()

    try:
        element_id = element.get_attribute("id")
    except Exception:
        element_id = None

    if element_id:
        try:
            label = frame.locator(f'label[for="{element_id}"]')
            if label.count() and label.first.is_visible():
                text = label.first.inner_text(timeout=500).strip()
                if text:
                    return text
        except Exception:
            pass

    try:
        text = element.evaluate(
            """
            el => {
                const fieldset = el.closest('fieldset');
                if (fieldset) {
                    const legend = fieldset.querySelector('legend');
                    if (legend && legend.innerText.trim()) return legend.innerText.trim();
                }
                let node = el.parentElement;
                for (let i = 0; i < 5 && node; i++, node = node.parentElement) {
                    const t = (node.innerText || '').trim();
                    if (t && t.length >= 5 && t.length < 1000) return t;
                }
                return '';
            }
            """
        )
        if text:
            return " ".join(str(text).split())[:1200]
    except Exception:
        pass

    try:
        return element.get_attribute("name") or ""
    except Exception:
        return ""


def _required(element, label: str) -> bool:
    try:
        if element.get_attribute("required") is not None:
            return True
        if _norm(element.get_attribute("aria-required")) == "true":
            return True
    except Exception:
        pass
    return "*" in (label or "") or "required" in _norm(label)


def _select_option(element, answer: str) -> bool:
    desired = _norm(answer)
    desired_codes = _phone_codes(answer)
    try:
        options = element.locator("option")
        # Exact match first.
        for index in range(options.count()):
            option = options.nth(index)
            text_raw = option.inner_text(timeout=300)
            value_raw = option.get_attribute("value") or ""
            text = _norm(text_raw)
            value = _norm(value_raw)
            if desired in {text, value}:
                element.select_option(value=value_raw)
                return True

        # ATS country-code selects commonly render an answer such as +1 as
        # "United States of America (+1)". Match the exact dial-code token,
        # never a loose substring that could confuse +1 with +1242.
        if desired_codes:
            for index in range(options.count()):
                option = options.nth(index)
                text_raw = option.inner_text(timeout=300)
                value_raw = option.get_attribute("value") or ""
                if desired_codes.intersection(_phone_codes(text_raw)) or desired_codes.intersection(_phone_codes(value_raw)):
                    element.select_option(value=value_raw)
                    return True

        # Conservative decorated-label fallback for longer answers.
        if len(desired) >= 4:
            for index in range(options.count()):
                option = options.nth(index)
                text_raw = option.inner_text(timeout=300)
                value_raw = option.get_attribute("value") or ""
                if _answers_equivalent(text_raw, answer) or _answers_equivalent(value_raw, answer):
                    element.select_option(value=value_raw)
                    return True
    except Exception:
        return False
    return False


def _radio_group_answer(frame, element) -> str:
    try:
        name = element.get_attribute("name")
    except Exception:
        name = None

    if not name:
        return ""

    try:
        radios = frame.locator(f'input[type="radio"][name="{name}"]')
    except Exception:
        return ""

    for index in range(radios.count()):
        radio = radios.nth(index)
        try:
            if not radio.is_checked():
                continue
        except Exception:
            continue

        try:
            radio_id = radio.get_attribute("id")
        except Exception:
            radio_id = None

        if radio_id:
            try:
                label = frame.locator(f'label[for="{radio_id}"]')
                if label.count():
                    text = label.first.inner_text(timeout=300).strip()
                    if text:
                        return " ".join(text.split())
            except Exception:
                pass

        try:
            return str(radio.get_attribute("value") or "").strip()
        except Exception:
            return ""

    return ""


def _existing_answer(frame, element, field_type: str, tag: str) -> str:
    if field_type == "radio":
        return _radio_group_answer(frame, element)

    if field_type == "checkbox":
        try:
            return "Yes" if element.is_checked() else ""
        except Exception:
            return ""

    if tag == "select":
        try:
            selected = element.locator("option:checked")
            if selected.count():
                text = selected.first.inner_text(timeout=300).strip()
                if _norm(text) not in PLACEHOLDER_VALUES:
                    return text
        except Exception:
            pass
        try:
            value = element.input_value(timeout=300).strip()
            return value if _norm(value) not in PLACEHOLDER_VALUES else ""
        except Exception:
            return ""

    try:
        value = element.input_value(timeout=300).strip()
        return value if _norm(value) not in PLACEHOLDER_VALUES else ""
    except Exception:
        return ""


def _radio_answer(frame, element, answer: str) -> bool:
    desired = _norm(answer)
    try:
        name = element.get_attribute("name")
    except Exception:
        name = None

    candidates = frame.locator(f'input[type="radio"][name="{name}"]') if name else frame.locator('input[type="radio"]')
    for index in range(candidates.count()):
        radio = candidates.nth(index)
        if not _visible(radio):
            continue
        label = _norm(_label_for(frame, radio))
        try:
            value = _norm(radio.get_attribute("value"))
        except Exception:
            value = ""

        aliases = {desired}
        if desired == "yes":
            aliases.update({"true", "1", "y"})
        elif desired == "no":
            aliases.update({"false", "0", "n"})

        if value not in aliases and desired not in label:
            continue

        try:
            radio.check(timeout=2000)
            return True
        except Exception:
            try:
                radio.click(force=True, timeout=2000)
                return True
            except Exception:
                continue

    return False


def _user_provided_decision(decision, answer: str) -> Dict:
    item = decision.to_dict()
    item.update(
        {
            "answer": answer,
            "source": "USER_PROVIDED",
            "confidence": 1.0,
            "review_required": False,
            "rationale": "The field already contains a user-provided value after manual review.",
        }
    )
    return item


def fill_generic_form_questions(
    page,
    profile,
    company: str,
    ats: str,
    job_text: str = "",
    memory: Optional[ApplicationMemory] = None,
) -> Dict:
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

    decisions: List[Dict] = []
    blockers: List[Dict] = []
    handled = 0
    seen_groups = set()

    try:
        for frame in page.frames:
            try:
                fields = frame.locator(
                    'input:not([type="hidden"]):not([type="file"]), textarea, select'
                )
            except Exception:
                continue

            for index in range(fields.count()):
                element = fields.nth(index)
                if not _visible(element):
                    continue

                try:
                    name = _norm(element.get_attribute("name"))
                    field_type = _norm(element.get_attribute("type"))
                    tag = _norm(element.evaluate("el => el.tagName.toLowerCase()"))
                except Exception:
                    name = field_type = tag = ""

                if name in STANDARD_NAMES:
                    continue

                label = _label_for(frame, element)
                question = " ".join((label or "").split())
                if not question or len(question) < 4:
                    continue

                required = _required(element, question)

                group_key = (name, _norm(question)) if field_type == "radio" else (index, _norm(question))
                if group_key in seen_groups:
                    continue
                seen_groups.add(group_key)

                decision = engine.answer_question(question, job_text=job_text)
                existing = _existing_answer(frame, element, field_type, tag)

                # Manual review may already have supplied a required sensitive or
                # otherwise review-only value. Accept the presence of that value
                # for navigation, while preserving the category so safe-submit
                # policy can still require final manual confirmation where needed.
                if (decision.review_required or decision.answer is None) and existing:
                    decisions.append(_user_provided_decision(decision, existing))
                    handled += 1
                    continue

                decisions.append(decision.to_dict())

                if decision.review_required or decision.answer is None:
                    if required:
                        blockers.append({
                            "question": question,
                            "category": decision.category,
                            "reason": decision.rationale,
                        })
                    continue

                answer = str(decision.answer).strip()
                success = False

                # Do not fight an ATS control that already displays the same
                # semantic value. This is important for decorated select labels
                # such as "United States of America (+1)" versus profile "+1".
                if existing and _answers_equivalent(existing, answer):
                    success = True
                elif field_type == "radio":
                    success = _radio_answer(frame, element, answer)
                elif tag == "select":
                    success = _select_option(element, answer)
                elif field_type == "checkbox":
                    desired = _norm(answer)
                    if desired in {"yes", "true", "1"}:
                        try:
                            element.check(timeout=2000)
                            success = True
                        except Exception:
                            success = False
                    elif desired in {"no", "false", "0"}:
                        try:
                            element.uncheck(timeout=2000)
                            success = True
                        except Exception:
                            success = False
                else:
                    if existing:
                        success = True
                    else:
                        try:
                            element.fill(answer)
                            success = True
                        except Exception:
                            success = False

                if success:
                    handled += 1
                elif required:
                    blockers.append({
                        "question": question,
                        "category": decision.category,
                        "reason": f"Safe answer '{answer}' could not be written to the control.",
                    })
    finally:
        if owns_memory:
            memory.close()

    unique = []
    seen = set()
    for blocker in blockers:
        key = (_norm(blocker.get("question")), _norm(blocker.get("category")))
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
