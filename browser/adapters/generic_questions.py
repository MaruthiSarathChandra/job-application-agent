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

GENERIC_LABEL_TEXT = PLACEHOLDER_VALUES | {
    "search",
    "required",
    "optional",
    "dropdown",
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

    if len(answer_norm) >= 4 and answer_norm in existing_norm:
        return True
    if len(existing_norm) >= 4 and existing_norm in answer_norm:
        return True
    return False


def _meaningful_label(value: str) -> bool:
    normalized = _norm(value).replace("*", "").strip()
    return bool(normalized and normalized not in GENERIC_LABEL_TEXT and len(normalized) >= 3)


def _label_for(frame, element) -> str:
    # Strong semantic labels first. Generic placeholders such as "Select" are
    # deliberately ignored because Rippling and other React ATS controls often
    # use them inside an otherwise well-labelled question container.
    for attr in ("aria-label", "data-qa"):
        try:
            value = element.get_attribute(attr)
        except Exception:
            value = None
        if value and _meaningful_label(str(value)):
            return str(value).strip()

    try:
        labelledby = element.get_attribute("aria-labelledby")
    except Exception:
        labelledby = None
    if labelledby:
        pieces = []
        for item_id in str(labelledby).split():
            try:
                target = frame.locator(f"#{item_id}")
                if target.count():
                    text = target.first.inner_text(timeout=400).strip()
                    if text:
                        pieces.append(text)
            except Exception:
                continue
        combined = " ".join(pieces).strip()
        if _meaningful_label(combined):
            return combined

    try:
        element_id = element.get_attribute("id")
    except Exception:
        element_id = None

    if element_id:
        try:
            label = frame.locator(f'label[for="{element_id}"]')
            if label.count() and label.first.is_visible():
                text = label.first.inner_text(timeout=500).strip()
                if _meaningful_label(text):
                    return text
        except Exception:
            pass

    # Prefer nearby explicit label/legend/question text before falling back to
    # a whole container's text. This is important for custom comboboxes where
    # the input itself only says "Select".
    try:
        text = element.evaluate(
            """
            el => {
                const clean = s => (s || '').replace(/\s+/g, ' ').trim();
                const generic = new Set(['select','select one','please select','choose','choose one','search','required','optional']);
                const good = s => {
                    const t = clean(s);
                    return t.length >= 3 && !generic.has(t.toLowerCase());
                };

                const fieldset = el.closest('fieldset');
                if (fieldset) {
                    const legend = fieldset.querySelector('legend');
                    if (legend && good(legend.innerText)) return clean(legend.innerText);
                }

                let node = el;
                for (let i = 0; i < 7 && node; i++, node = node.parentElement) {
                    const labels = node.querySelectorAll('label, legend, [data-testid*="label"], [class*="label" i]');
                    for (const candidate of labels) {
                        const t = clean(candidate.innerText || candidate.textContent);
                        if (good(t) && t.length < 500) return t;
                    }

                    const children = Array.from(node.children || []);
                    const index = children.indexOf(el);
                    if (index > 0) {
                        for (let j = index - 1; j >= 0; j--) {
                            const t = clean(children[j].innerText || children[j].textContent);
                            if (good(t) && t.length < 500) return t;
                        }
                    }

                    const t = clean(node.innerText || node.textContent);
                    if (good(t) && t.length >= 5 && t.length < 1000) return t;
                }
                return '';
            }
            """
        )
        if text and _meaningful_label(text):
            return " ".join(str(text).split())[:1200]
    except Exception:
        pass

    # Placeholder is only useful when it is actually descriptive.
    try:
        placeholder = element.get_attribute("placeholder")
    except Exception:
        placeholder = None
    if placeholder and _meaningful_label(str(placeholder)):
        return str(placeholder).strip()

    try:
        name = element.get_attribute("name") or ""
    except Exception:
        name = ""
    return name if _meaningful_label(name) else ""


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
        for index in range(options.count()):
            option = options.nth(index)
            text_raw = option.inner_text(timeout=300)
            value_raw = option.get_attribute("value") or ""
            if desired in {_norm(text_raw), _norm(value_raw)}:
                element.select_option(value=value_raw)
                return True

        if desired_codes:
            for index in range(options.count()):
                option = options.nth(index)
                text_raw = option.inner_text(timeout=300)
                value_raw = option.get_attribute("value") or ""
                if desired_codes.intersection(_phone_codes(text_raw)) or desired_codes.intersection(_phone_codes(value_raw)):
                    element.select_option(value=value_raw)
                    return True

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


def _visible_options(frame):
    results = []
    seen = set()
    selectors = (
        '[role="option"]',
        '[data-radix-collection-item]',
        '[data-headlessui-state]',
        'li[role="option"]',
    )
    for selector in selectors:
        try:
            options = frame.locator(selector)
        except Exception:
            continue
        for index in range(min(options.count(), 100)):
            option = options.nth(index)
            if not _visible(option):
                continue
            try:
                text = " ".join(option.inner_text(timeout=300).split())
            except Exception:
                text = ""
            key = _norm(text)
            if not key or key in seen:
                continue
            seen.add(key)
            results.append((text, option))
    return results


def _combobox_answer(frame, element, answer: str) -> bool:
    desired = _norm(answer)
    if not desired:
        return False

    try:
        element.click(timeout=2000)
    except Exception:
        try:
            element.click(force=True, timeout=2000)
        except Exception:
            return False

    try:
        tag = _norm(element.evaluate("el => el.tagName.toLowerCase()"))
    except Exception:
        tag = ""
    if tag in {"input", "textarea"}:
        try:
            element.fill(str(answer))
        except Exception:
            pass

    try:
        frame.page.wait_for_timeout(350)
    except Exception:
        pass

    options = _visible_options(frame)
    for text, option in options:
        if _norm(text) == desired or _answers_equivalent(text, answer):
            try:
                option.click(timeout=2000)
                return True
            except Exception:
                try:
                    option.click(force=True, timeout=2000)
                    return True
                except Exception:
                    continue
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
                    'input:not([type="hidden"]):not([type="file"]), textarea, select, [role="combobox"]'
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
                    role = _norm(element.get_attribute("role"))
                    popup = _norm(element.get_attribute("aria-haspopup"))
                except Exception:
                    name = field_type = tag = role = popup = ""

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

                if existing and _answers_equivalent(existing, answer):
                    success = True
                elif field_type == "radio":
                    success = _radio_answer(frame, element, answer)
                elif tag == "select":
                    success = _select_option(element, answer)
                elif role == "combobox" or popup == "listbox":
                    success = _combobox_answer(frame, element, answer)
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
