from __future__ import annotations

from pathlib import Path
from typing import Iterable

from agent.submission_policy import SubmissionPolicy
from browser.account_manager import handle_account_page
from browser.submission_detector import detect_submission_confirmation
from learning.application_memory import ApplicationMemory
from pipeline.ats import ATS_BRASSRING, detect_ats

from .base import AdapterResult, ApplicationContext, ATSAdapter
from .generic_questions import fill_generic_form_questions


class BrassRingAdapter(ATSAdapter):
    name = ATS_BRASSRING

    def supports(self, job) -> bool:
        return detect_ats(job.url) == ATS_BRASSRING

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
    def _button_or_link(page, names):
        for frame in page.frames:
            for name in names:
                for role in ("button", "link"):
                    try:
                        items = frame.get_by_role(role, name=name, exact=False)
                    except Exception:
                        continue
                    for index in range(items.count()):
                        item = items.nth(index)
                        try:
                            if item.is_visible() and item.is_enabled():
                                return item
                        except Exception:
                            continue
        return None

    @staticmethod
    def _fill_if_empty(page, selectors, value) -> bool:
        if value is None or str(value).strip() == "":
            return False
        element = BrassRingAdapter._first_visible(page, selectors)
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
        for frame in page.frames:
            try:
                body = frame.locator("body")
                if body.count() and body.first.is_visible():
                    if name and name in body.first.inner_text(timeout=700).lower():
                        return True
            except Exception:
                continue
        return False

    @staticmethod
    def _upload_resume(page, resume_path: str) -> bool:
        path = Path(resume_path)
        if not path.exists() or not path.is_file():
            return False
        if BrassRingAdapter._resume_present(page, resume_path):
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
    def _find_submit(page):
        names = (
            "Submit Application",
            "Submit application",
            "Submit",
            "Complete Application",
            "Finish",
        )
        button = BrassRingAdapter._button_or_link(page, names)
        if button is not None:
            return button

        for frame in page.frames:
            try:
                items = frame.locator('button[type="submit"], input[type="submit"]')
            except Exception:
                continue
            for index in range(items.count()):
                item = items.nth(index)
                try:
                    if item.is_visible() and item.is_enabled():
                        return item
                except Exception:
                    continue
        return None

    def _open_application(self, page):
        apply = self._button_or_link(
            page,
            (
                "Apply",
                "Apply Now",
                "Apply now",
                "Apply for this job",
                "Apply to this job",
            ),
        )
        if apply is None:
            return False
        try:
            apply.click(timeout=5000)
            page.wait_for_timeout(1200)
            return True
        except Exception:
            return False

    def run(self, page, profile, context: ApplicationContext) -> AdapterResult:
        resume_current = bool(context.metadata.get("resume_current_page"))
        if not resume_current:
            page.goto(context.job.url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(1200)
            self._open_application(page)
        else:
            page.wait_for_timeout(350)

        if detect_submission_confirmation(page):
            return AdapterResult(
                status="submitted",
                submitted=True,
                message="BrassRing submission confirmation detected.",
            )

        account = handle_account_page(page, profile)
        if account.verification_required:
            return AdapterResult(
                status="verification_required",
                review_required=True,
                message=account.message,
                blockers=[{
                    "category": "verification",
                    "reason": "Complete CAPTCHA/MFA/email verification in the browser.",
                }],
                metadata={"account_state": account.state},
            )
        if account.blockers:
            return AdapterResult(
                status="account_review",
                review_required=True,
                message=account.message,
                blockers=account.blockers,
                metadata={"account_state": account.state},
            )

        first_name = profile.get("application_defaults.first_name")
        last_name = profile.get("application_defaults.last_name")
        full_name = profile.get("candidate.legal_name")
        email = profile.get("candidate.email")
        phone = profile.get("application_defaults.phone_number") or profile.get("candidate.phone")
        linkedin = profile.get("candidate.linkedin")
        github = profile.get("candidate.github")

        standard = {
            "first_name": self._fill_if_empty(
                page,
                ['input[name*="first" i]', 'input[id*="first" i]', 'input[autocomplete="given-name"]'],
                first_name,
            ),
            "last_name": self._fill_if_empty(
                page,
                ['input[name*="last" i]', 'input[id*="last" i]', 'input[autocomplete="family-name"]'],
                last_name,
            ),
            "full_name": self._fill_if_empty(
                page,
                ['input[name="name"]', 'input[autocomplete="name"]'],
                full_name,
            ),
            "email": self._fill_if_empty(
                page,
                ['input[type="email"]', 'input[name*="email" i]', 'input[id*="email" i]'],
                email,
            ),
            "phone": self._fill_if_empty(
                page,
                ['input[type="tel"]', 'input[name*="phone" i]', 'input[id*="phone" i]'],
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
                message="BrassRing resume upload control was not found or could not be filled.",
                blockers=[{"category": "resume", "reason": "resume_upload_failed"}],
                metadata={"standard_fields": standard, "account_state": account.state},
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
        decisions = questions.get("decisions") or []
        submit = self._find_submit(page)

        if submit is None and not detect_submission_confirmation(page):
            blockers.append({
                "category": "submit_control",
                "reason": "BrassRing submit/continue control was not identified on this page.",
            })

        policy = SubmissionPolicy(context.submission_mode)
        submission = policy.decide(decisions, validation_errors=blockers)

        if blockers:
            return AdapterResult(
                status="review",
                review_required=True,
                message="BrassRing application requires review before submission.",
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
            page.wait_for_timeout(1500)
        except Exception as exc:
            return AdapterResult(
                status="review",
                review_required=True,
                message="BrassRing submit click failed.",
                blockers=[{"category": "submit", "reason": str(exc)}],
                decisions=decisions,
            )

        if detect_submission_confirmation(page):
            return AdapterResult(
                status="submitted",
                submitted=True,
                message="BrassRing application submitted and confirmation detected.",
                decisions=decisions,
            )

        return AdapterResult(
            status="review",
            review_required=True,
            message="BrassRing submit was clicked, but no submission confirmation was detected.",
            blockers=[{"category": "submit_confirmation", "reason": "confirmation_not_detected"}],
            decisions=decisions,
        )
