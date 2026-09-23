from __future__ import annotations

from pathlib import Path
from typing import Iterable

from agent.submission_policy import SubmissionPolicy
from browser.submission_detector import detect_submission_confirmation
from learning.application_memory import ApplicationMemory
from pipeline.ats import ATS_LEVER, detect_ats

from .base import AdapterResult, ApplicationContext, ATSAdapter
from .generic_questions import fill_generic_form_questions


class LeverAdapter(ATSAdapter):
    name = ATS_LEVER

    def supports(self, job) -> bool:
        return detect_ats(job.url) == ATS_LEVER

    @staticmethod
    def _first_visible(page, selectors: Iterable[str]):
        for frame in page.frames:
            for selector in selectors:
                try:
                    items = frame.locator(selector)
                except Exception:
                    continue
                for index in range(items.count()):
                    item = items.nth(index)
                    try:
                        if item.is_visible():
                            return item
                    except Exception:
                        continue
        return None

    @staticmethod
    def _fill(page, selectors, value) -> bool:
        if value is None or str(value).strip() == "":
            return False
        element = LeverAdapter._first_visible(page, selectors)
        if element is None:
            return False
        try:
            current = element.input_value(timeout=500).strip()
        except Exception:
            current = ""
        if current:
            return True
        try:
            element.fill(str(value))
            return True
        except Exception:
            return False

    @staticmethod
    def _resume_present(page, resume_path: str) -> bool:
        name = Path(resume_path).name.lower()
        if not name:
            return False
        for frame in page.frames:
            try:
                body = frame.locator("body")
                if body.count() and body.first.is_visible():
                    if name in body.first.inner_text(timeout=700).lower():
                        return True
            except Exception:
                continue
        return False

    @staticmethod
    def _upload_resume(page, resume_path: str) -> bool:
        path = Path(resume_path)
        if not path.exists() or not path.is_file():
            return False

        if LeverAdapter._resume_present(page, resume_path):
            return True

        for frame in page.frames:
            try:
                inputs = frame.locator('input[type="file"]')
            except Exception:
                continue
            for index in range(inputs.count()):
                element = inputs.nth(index)
                try:
                    element.set_input_files(str(path.resolve()))
                    page.wait_for_timeout(900)
                    return True
                except Exception:
                    continue
        return False

    @staticmethod
    def _submit(page):
        for frame in page.frames:
            for name in ("Submit application", "Submit Application", "Submit"):
                try:
                    buttons = frame.get_by_role("button", name=name, exact=True)
                    for index in range(buttons.count()):
                        button = buttons.nth(index)
                        if button.is_visible() and button.is_enabled():
                            return button
                except Exception:
                    continue
            try:
                buttons = frame.locator('button[type="submit"], input[type="submit"]')
                for index in range(buttons.count()):
                    button = buttons.nth(index)
                    if button.is_visible() and button.is_enabled():
                        return button
            except Exception:
                continue
        return None

    def run(self, page, profile, context: ApplicationContext) -> AdapterResult:
        resume_current = bool(context.metadata.get("resume_current_page"))
        if not resume_current:
            page.goto(context.job.url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(900)
        else:
            page.wait_for_timeout(350)

        if detect_submission_confirmation(page):
            return AdapterResult(
                status="submitted",
                submitted=True,
                message="Lever submission confirmation detected.",
            )

        legal_name = profile.get("candidate.legal_name") or ""
        email = profile.get("candidate.email")
        phone = profile.get("application_defaults.phone_number") or profile.get("candidate.phone")
        linkedin = profile.get("candidate.linkedin")
        github = profile.get("candidate.github")

        standard = {
            "name": self._fill(
                page,
                ['input[name="name"]', 'input[autocomplete="name"]'],
                legal_name,
            ),
            "email": self._fill(
                page,
                ['input[name="email"]', 'input[type="email"]'],
                email,
            ),
            "phone": self._fill(
                page,
                ['input[name="phone"]', 'input[type="tel"]'],
                phone,
            ),
            "linkedin": self._fill(
                page,
                ['input[name*="linkedin" i]', 'input[placeholder*="LinkedIn" i]'],
                linkedin,
            ),
            "github": self._fill(
                page,
                ['input[name*="github" i]', 'input[placeholder*="GitHub" i]'],
                github,
            ),
        }

        if not self._upload_resume(page, context.resume_path):
            return AdapterResult(
                status="review",
                review_required=True,
                message="Lever resume upload failed or no upload control was found.",
                blockers=[{"category": "resume", "reason": "resume_upload_failed"}],
                metadata={"standard_fields": standard},
            )

        memory = ApplicationMemory()
        try:
            questions = fill_generic_form_questions(
                page,
                profile,
                company=context.company or context.job.company,
                ats=self.name,
                job_text=context.job.description,
                memory=memory,
            )
        finally:
            memory.close()

        blockers = list(questions.get("blockers") or [])
        submit = self._submit(page)
        if submit is None and not detect_submission_confirmation(page):
            blockers.append({
                "category": "submit_control",
                "reason": "Lever submit control was not found.",
            })

        decisions = questions.get("decisions") or []
        policy = SubmissionPolicy(context.submission_mode)
        submission = policy.decide(decisions, validation_errors=blockers)

        if blockers:
            return AdapterResult(
                status="review",
                review_required=True,
                message="Lever form requires review before submission.",
                blockers=blockers,
                decisions=decisions,
                metadata={"standard_fields": standard, "resume_uploaded": True},
            )

        if not submission.may_submit:
            return AdapterResult(
                status="ready_for_review",
                message=submission.reason,
                decisions=decisions,
                metadata={"standard_fields": standard, "resume_uploaded": True},
            )

        try:
            submit.click(timeout=5000)
            page.wait_for_timeout(1400)
            if detect_submission_confirmation(page):
                return AdapterResult(
                    status="submitted",
                    submitted=True,
                    message="Lever application submitted and confirmation detected.",
                    decisions=decisions,
                    metadata={"standard_fields": standard, "resume_uploaded": True},
                )
            return AdapterResult(
                status="review",
                review_required=True,
                message="Lever submit was clicked, but no submission confirmation was detected.",
                blockers=[{"category": "submit_confirmation", "reason": "confirmation_not_detected"}],
                decisions=decisions,
                metadata={"standard_fields": standard, "resume_uploaded": True},
            )
        except Exception as exc:
            return AdapterResult(
                status="review",
                review_required=True,
                message="Lever submit click failed.",
                blockers=[{"category": "submit", "reason": str(exc)}],
                decisions=decisions,
            )
