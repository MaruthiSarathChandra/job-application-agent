from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional

from learning.application_memory import (
    ApplicationMemory,
    is_placeholder_answer,
    is_sensitive_question,
)


SKIP_LABELS = {
    "",
    "first name",
    "last name",
    "full name",
    "name",
    "email",
    "email address",
    "phone",
    "phone number",
    "address",
    "address line 1",
    "address line 2",
    "city",
    "state",
    "postal code",
    "zip code",
    "country",
    "linkedin",
    "linkedin url",
    "github",
    "website",
    "resume",
    "resume/cv",
    "search",
}


def _norm(value) -> str:
    return " ".join(str(value or "").strip().lower().replace("*", "").split())


def _visible(element) -> bool:
    try:
        return element.is_visible()
    except Exception:
        return False


def _question_for(frame, element) -> str:
    try:
        aria = element.get_attribute("aria-label")
    except Exception:
        aria = None
    if aria and len(str(aria).strip()) >= 6:
        return " ".join(str(aria).split())[:1200]

    try:
        element_id = element.get_attribute("id")
    except Exception:
        element_id = None

    if element_id:
        try:
            label = frame.locator(f'label[for="{element_id}"]')
            if label.count() and label.first.is_visible():
                text = label.first.inner_text(timeout=400).strip()
                if text:
                    return " ".join(text.split())[:1200]
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
                for (let i = 0; i < 7 && node; i++, node = node.parentElement) {
                    const t = (node.innerText || '').trim();
                    if (!t || t.length > 1600) continue;
                    const lines = t.split(/\n+/).map(x => x.trim()).filter(Boolean);
                    for (const line of lines) {
                        if (line.includes('?') && line.length >= 6) return line;
                    }
                    if (lines.length && lines[0].length >= 6) return lines[0];
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


def _selected_option_text(element) -> str:
    try:
        return element.locator("option:checked").first.inner_text(timeout=300).strip()
    except Exception:
        try:
            return element.input_value(timeout=300).strip()
        except Exception:
            return ""


def _radio_group_value(frame, element) -> str:
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
            return (radio.get_attribute("value") or "").strip()
        except Exception:
            return ""

    return ""


@dataclass
class CapturedAnswer:
    key: str
    question: str
    answer: str
    control_type: str


class ReviewCapture:
    """
    Captures only user-visible, non-secret form answers around a manual review.

    The intended workflow is:
      before = capture(page)
      user completes only review-required fields
      after = capture(page)
      remember_changes(before, after, ...)

    Only values changed by the user during that window are considered for
    learning. Checkboxes are intentionally excluded because they frequently
    represent legal terms/attestations.
    """

    def capture(self, page) -> Dict[str, CapturedAnswer]:
        result: Dict[str, CapturedAnswer] = {}

        for frame_index, frame in enumerate(page.frames):
            try:
                controls = frame.locator(
                    'input:not([type="hidden"]):not([type="file"]):not([type="checkbox"]), '
                    'textarea, select'
                )
            except Exception:
                continue

            seen_radio_names = set()

            for index in range(controls.count()):
                element = controls.nth(index)
                if not _visible(element):
                    continue

                try:
                    tag = str(element.evaluate("el => el.tagName.toLowerCase()"))
                    control_type = str(element.get_attribute("type") or tag).lower()
                    name = str(element.get_attribute("name") or "")
                    element_id = str(element.get_attribute("id") or "")
                except Exception:
                    continue

                question = _question_for(frame, element)
                question_norm = _norm(question)
                if not question_norm or question_norm in SKIP_LABELS:
                    continue

                if control_type == "password":
                    continue

                if control_type == "radio":
                    if name and name in seen_radio_names:
                        continue
                    if name:
                        seen_radio_names.add(name)
                    answer = _radio_group_value(frame, element)
                elif tag == "select":
                    answer = _selected_option_text(element)
                else:
                    try:
                        answer = element.input_value(timeout=300).strip()
                    except Exception:
                        answer = ""

                key_material = name or element_id or f"{frame_index}:{index}"
                key = f"{frame_index}|{key_material}|{question_norm}"
                result[key] = CapturedAnswer(
                    key=key,
                    question=question,
                    answer=answer,
                    control_type=control_type,
                )

        return result

    def changed_answers(
        self,
        before: Dict[str, CapturedAnswer],
        after: Dict[str, CapturedAnswer],
    ) -> List[CapturedAnswer]:
        changed = []

        for key, current in after.items():
            previous = before.get(key)
            previous_answer = previous.answer.strip() if previous else ""
            current_answer = current.answer.strip()

            if not current_answer:
                continue
            if is_placeholder_answer(current_answer):
                continue
            if previous_answer == current_answer:
                continue
            if is_sensitive_question(current.question):
                continue

            changed.append(current)

        return changed

    def remember_changes(
        self,
        before: Dict[str, CapturedAnswer],
        after: Dict[str, CapturedAnswer],
        memory: ApplicationMemory,
        company: str = "",
        ats: str = "",
    ) -> List[dict]:
        stored = []
        for item in self.changed_answers(before, after):
            ok = memory.remember_confirmed(
                question=item.question,
                answer=item.answer,
                company=company,
                ats=ats,
                category="user_confirmed",
            )
            if ok:
                stored.append({
                    "question": item.question,
                    "answer": item.answer,
                    "control_type": item.control_type,
                })
        return stored
