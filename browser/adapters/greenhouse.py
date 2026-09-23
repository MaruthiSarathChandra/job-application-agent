from __future__ import annotations

from pathlib import Path
from typing import Iterable, Optional

from agent.submission_policy import SubmissionPolicy
from learning.application_memory import ApplicationMemory
from pipeline.ats import ATS_GREENHOUSE, detect_ats

from .base import AdapterResult, ApplicationContext, ATSAdapter
from .generic_questions import fill_generic_form_questions


class GreenhouseAdapter(ATSAdapter):
    name = ATS_GREENHOUSE

    def supports(self, job) -> bool:
        return detect_ats(job.url) == ATS_GREENHOUSE

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
    def _fill_if_empty(page, selectors, value) -> bool:
        if value is None or str(value).strip() == "":
            return False
        element = GreenhouseAdapter._first_visible(page, selectors)
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
    def _upload_resume(page, resume_path: str) -> bool:
        path = Path(resume_path)
        if not path.exists() or not path.is_file():
            return False

        selectors = [
            'input[type="file"][name*="resume"]',
            'input[type="file"][id*="resume"]',
            'input[type="file"]',
        ]
        element = GreenhouseAdapter._first_visible(page, selectors)
        if element is None:
            # File inputs can be intentionally hidden behind an Upload button.
            for frame in page.frames:
                try:
                    hidden = frame.locator('input[type="file"]')
                    if hidden.count():
                        element = hidden.first
                        break
                except Exception:
                    continue

        if element is None:
            return False

        try:
            element.set_input_files(str(path.resolve()))
            page.wait_for_timeout(700)
            return True
        except Exception:
            return False

    @staticmethod
    def _find_submit(page):
        names = ["Submit Application", "Submit application", "Submit"]
        for frame in page.frames:
            for name in names:
                try:
                    buttons = frame.get_by_role("button", name=name, exact=True)
                    for index in range(buttons.count()):
                        button = buttons.nth(index)
                        if button.is_visible() and button.is_enabled():
                            return button
                except Exception:
                    continue

            try:
                submits = frame.locator('input[type="submit"], button[type="submit"]')
                for index in range(submits.count()):
                    button = submits.nth(index)
                    if button.is_visible() and button.is_enabled():
                        return button
            except Exception:
                continue
        return None

    def run(self, page, profile, context: ApplicationContext) -> AdapterResult:
        page.goto(context.job.url, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(900)

        first_name = profile.get("application_defaults.first_name")
        last_name = profile.get("application_defaults.last_name")
        email = profile.get("candidate.email")
        phone = profile.get("application_defaults.phone_number") or profile.get("candidate.phone")
        linkedin = profile.get("candidate.linkedin")
        github = profile.get("candidate.github")

        standard = {
            "first_name": self._fill_if_empty(
                page,
                ['input[name="first_name"]', 'input[id*="first_name"]', 'input[autocomplete="given-name"]'],
                first_name,
            ),
            "last_name": self._fill_if_empty(
                page,
                ['input[name="last_name"]', 'input[id*="last_name"]', 'input[autocomplete="family-name"]'],
                last_name,
            ),
            "email": self._fill_if_empty(
                page,
                ['input[name="email"]', 'input[type="email"]', 'input[autocomplete="email"]'],
                email,
            ),
            "phone": self._fill_if_empty(
                page,
                ['input[name="phone"]', 'input[type="tel"]', 'input[autocomplete="tel"]'],
                phone,
            ),
            "linkedin": self._fill_if_empty(
                page,
                ['input[name*="linkedin" i]', 'input[id*="linkedin" i]'],
                linkedin,
            ),
            "github": self._fill_if_empty(
                page,
                ['input[name*="github" i]', 'input[id*="github" i]'],
                github,
            ),
        }

        resume_ok = self._upload_resume(page, context.resume_path)
        if not resume_ok:
            return AdapterResult(
                status="review",
                review_required=True,
                message="Greenhouse resume upload control was not found or the file could not be uploaded.",
                blockers=[{"category": "resume", "reason": "resume_upload_failed"}],
                metadata={"standard_fields": standard},
            )

        memory = ApplicationMemory()
        try:
            question_result = fill_generic_form_questions(
                page,
                profile,
                company=context.company or context.job.company,
                ats=self.name,
                job_text=context.job.description,
                memory=memory,
            )
        finally:
            memory.close()

        blockers = list(question_result.get("blockers") or [])
        submit = self._find_submit(page)
        if submit is None:
            blockers.append({
                "category": "submit_control",
                "reason": "Submit Application control was not found.",
            })

        decisions = question_result.get("decisions") or []
        policy = SubmissionPolicy(context.submission_mode)
        submission = policy.decide(decisions, validation_errors=blockers)

        if blockers:
            return AdapterResult(
                status="review",
                review_required=True,
                message="Greenhouse form requires review before submission.",
                blockers=blockers,
                decisions=decisions,
                metadata={"standard_fields": standard, "resume_uploaded": True},
            )

        if not submission.may_submit:
            return AdapterResult(
                status="ready_for_review",
                review_required=False,
                submitted=False,
                message=submission.reason,
                decisions=decisions,
                metadata={"standard_fields": standard, "resume_uploaded": True},
            )

        try:
            submit.click(timeout=5000)
            page.wait_for_timeout(1200)
            return AdapterResult(
                status="submitted",
                submitted=True,
                message="Greenhouse submit control was clicked after the safe-submit policy passed.",
                decisions=decisions,
                metadata={"standard_fields": standard, "resume_uploaded": True},
            )
        except Exception as exc:
            return AdapterResult(
                status="review",
                review_required=True,
                message="Greenhouse submit click failed.",
                blockers=[{"category": "submit", "reason": str(exc)}],
                decisions=decisions,
            )
