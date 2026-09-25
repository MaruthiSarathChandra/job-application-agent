from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from agent.submission_policy import SubmissionPolicy
from browser.account_manager import handle_account_page
from browser.submission_detector import detect_submission_confirmation
from learning.application_memory import ApplicationMemory
from pipeline.ats import ATS_BRASSRING, detect_ats

from .base import AdapterResult, ApplicationContext, ATSAdapter
from .generic_questions import fill_generic_form_questions


CLOSED_MARKERS = (
    "job posting you are looking for has expired",
    "position has already been filled",
    "this link is no longer valid",
    "job is no longer available",
    "job is no longer active",
)

ALREADY_APPLIED_MARKERS = (
    "you have already applied for this job",
    "we only allow one application for this job and you have already applied",
)


def _norm(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def classify_brassring_page(text: str):
    normalized = _norm(text)
    for marker in ALREADY_APPLIED_MARKERS:
        if marker in normalized:
            return "already_applied", marker
    for marker in CLOSED_MARKERS:
        if marker in normalized:
            return "closed", marker
    return "open", ""


def classify_brassring_requirements(text: str):
    """Extract explicit hard-eligibility requirements from visible job text."""
    normalized = _norm(text)

    citizenship_required = bool(
        re.search(r"(?:u\.s\.|us) citizenship required\??\s*yes\b", normalized)
    )
    clearance_required = bool(
        re.search(r"(?:security )?clearance required\??\s*yes\b", normalized)
    )

    clearance_level = ""
    match = re.search(
        r"clearance level\s*(ts\/sci|top secret|secret|confidential)\b",
        normalized,
    )
    if match:
        raw = match.group(1)
        clearance_level = raw.upper() if raw == "ts/sci" else raw.title()

    return {
        "us_citizenship_required": citizenship_required,
        "clearance_required": clearance_required,
        "clearance_level": clearance_level,
    }


def _first_locked(profile, paths):
    for path in paths:
        try:
            value = profile.get_locked_value(path)
        except Exception:
            value = None
        if value is not None:
            return value
    return None


class BrassRingAdapter(ATSAdapter):
    name = ATS_BRASSRING

    def supports(self, job) -> bool:
        return detect_ats(job.url) == ATS_BRASSRING

    @staticmethod
    def _page_text(page) -> str:
        parts = []
        for frame in page.frames:
            try:
                body = frame.locator("body")
                if body.count() and body.first.is_visible():
                    parts.append(body.first.inner_text(timeout=900))
            except Exception:
                continue
        return "\n".join(parts)

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
    def _find_apply(page):
        button = BrassRingAdapter._button_or_link(
            page,
            (
                "Apply to job",
                "Apply To Job",
                "Quick Apply",
                "Apply Now",
                "Apply now",
                "Apply for this job",
                "Apply to this job",
                "Apply",
            ),
        )
        if button is not None:
            return button

        pattern = re.compile(r"^\s*(apply to job|quick apply|apply now|apply)\s*$", re.I)
        for frame in page.frames:
            for selector in ("button", "a", '[role="button"]'):
                try:
                    items = frame.locator(selector).filter(has_text=pattern)
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

        selectors = (
            'input[type="file"][name*="resume" i]',
            'input[type="file"][id*="resume" i]',
            'input[type="file"][aria-label*="resume" i]',
            'input[type="file"][accept*="pdf" i]',
            'input[type="file"]',
        )
        for frame in page.frames:
            for selector in selectors:
                try:
                    inputs = frame.locator(selector)
                except Exception:
                    continue
                for index in range(inputs.count()):
                    element = inputs.nth(index)
                    try:
                        element.set_input_files(str(path.resolve()))
                        page.wait_for_timeout(1000)
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

    def _application_surface_present(self, page) -> bool:
        selectors = (
            'input[type="file"]',
            'input[type="email"]',
            'input[name*="first" i]',
            'input[name*="last" i]',
            'textarea',
        )
        return self._first_visible(page, selectors) is not None or self._find_submit(page) is not None

    def _open_application(self, page):
        """Click Apply and return the browser page that owns the application flow."""
        apply = self._find_apply(page)
        if apply is None:
            return page, False

        context = page.context
        before_pages = list(context.pages)
        try:
            apply.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            pass

        try:
            apply.click(timeout=7000)
        except Exception:
            try:
                apply.click(timeout=3000, force=True)
            except Exception:
                return page, False

        page.wait_for_timeout(1800)
        new_pages = [item for item in context.pages if item not in before_pages]
        if new_pages:
            target = new_pages[-1]
            try:
                target.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            try:
                target.bring_to_front()
            except Exception:
                pass
            target.wait_for_timeout(700)
            return target, True

        return page, True

    def _resume_page(self, page):
        """Recover a popup/new-tab candidate page on a resumed manual cycle."""
        candidates = []
        try:
            candidates = list(page.context.pages)
        except Exception:
            return page

        for candidate in reversed(candidates):
            try:
                if candidate.is_closed():
                    continue
            except Exception:
                continue
            if self._application_surface_present(candidate):
                return candidate
        return candidates[-1] if candidates else page

    def _preflight_result(self, page, profile):
        text = self._page_text(page)
        status, reason = classify_brassring_page(text)
        if status == "closed":
            return AdapterResult(
                status="closed",
                review_required=False,
                submitted=False,
                message="BrassRing job is closed/expired; application was skipped.",
                blockers=[{"category": "job_availability", "reason": reason}],
            )
        if status == "already_applied":
            return AdapterResult(
                status="already_applied",
                review_required=False,
                submitted=False,
                message="BrassRing reports that this job was already applied to; skipped duplicate application.",
                blockers=[],
            )

        requirements = classify_brassring_requirements(text)
        if requirements["us_citizenship_required"]:
            citizen = _first_locked(
                profile,
                (
                    "eligibility.us_citizen",
                    "citizenship.us_citizen",
                    "application_questions.us_citizen",
                ),
            )
            if citizen is False:
                return AdapterResult(
                    status="ineligible",
                    review_required=False,
                    submitted=False,
                    message="Job explicitly requires U.S. citizenship and the locked profile says the requirement is not met.",
                    blockers=[{"category": "eligibility", "reason": "us_citizenship_required"}],
                )
            if citizen is not True:
                return AdapterResult(
                    status="eligibility_review",
                    review_required=False,
                    submitted=False,
                    message="Job explicitly requires U.S. citizenship. Add a truthful locked eligibility.us_citizen value before the agent can continue.",
                    blockers=[{"category": "eligibility", "reason": "us_citizenship_required_profile_missing"}],
                )

        if requirements["clearance_required"]:
            clearance = _first_locked(
                profile,
                (
                    "eligibility.has_required_security_clearance",
                    "security_clearance.has_required_clearance",
                ),
            )
            if clearance is False:
                return AdapterResult(
                    status="ineligible",
                    review_required=False,
                    submitted=False,
                    message="Job explicitly requires a security clearance and the locked profile says the requirement is not met.",
                    blockers=[{"category": "eligibility", "reason": "security_clearance_required"}],
                )
            if clearance is not True:
                level = requirements.get("clearance_level") or "the required level"
                return AdapterResult(
                    status="eligibility_review",
                    review_required=False,
                    submitted=False,
                    message=f"Job explicitly requires a security clearance ({level}). Add a truthful locked eligibility.has_required_security_clearance value before continuing.",
                    blockers=[{"category": "eligibility", "reason": "security_clearance_profile_missing"}],
                )

        return None

    def run(self, page, profile, context: ApplicationContext) -> AdapterResult:
        resume_current = bool(context.metadata.get("resume_current_page"))
        active_page = page

        if not resume_current:
            active_page.goto(context.job.url, wait_until="domcontentloaded", timeout=90000)
            active_page.wait_for_timeout(1600)

            preflight = self._preflight_result(active_page, profile)
            if preflight is not None:
                return preflight

            active_page, opened = self._open_application(active_page)
            if opened:
                active_page.wait_for_timeout(600)

            preflight = self._preflight_result(active_page, profile)
            if preflight is not None:
                return preflight

            if not opened and not self._application_surface_present(active_page):
                return AdapterResult(
                    status="review",
                    review_required=True,
                    message="BrassRing Apply control was not found or did not open an application form.",
                    blockers=[{"category": "apply_control", "reason": "application_surface_not_open"}],
                    metadata={"page_url": active_page.url},
                )
        else:
            active_page = self._resume_page(page)
            active_page.wait_for_timeout(350)
            preflight = self._preflight_result(active_page, profile)
            if preflight is not None:
                return preflight

        if detect_submission_confirmation(active_page):
            return AdapterResult(
                status="submitted",
                submitted=True,
                message="BrassRing submission confirmation detected.",
            )

        account = handle_account_page(active_page, profile)
        if account.verification_required:
            return AdapterResult(
                status="verification_required",
                review_required=True,
                message=account.message,
                blockers=[{
                    "category": "verification",
                    "reason": "Complete CAPTCHA/MFA/email verification in the browser.",
                }],
                metadata={"account_state": account.state, "page_url": active_page.url},
            )
        if account.blockers:
            return AdapterResult(
                status="account_review",
                review_required=True,
                message=account.message,
                blockers=account.blockers,
                metadata={"account_state": account.state, "page_url": active_page.url},
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
                active_page,
                ['input[name*="first" i]', 'input[id*="first" i]', 'input[autocomplete="given-name"]'],
                first_name,
            ),
            "last_name": self._fill_if_empty(
                active_page,
                ['input[name*="last" i]', 'input[id*="last" i]', 'input[autocomplete="family-name"]'],
                last_name,
            ),
            "full_name": self._fill_if_empty(
                active_page,
                ['input[name="name"]', 'input[autocomplete="name"]'],
                full_name,
            ),
            "email": self._fill_if_empty(
                active_page,
                ['input[type="email"]', 'input[name*="email" i]', 'input[id*="email" i]'],
                email,
            ),
            "phone": self._fill_if_empty(
                active_page,
                ['input[type="tel"]', 'input[name*="phone" i]', 'input[id*="phone" i]'],
                phone,
            ),
            "linkedin": self._fill_if_empty(
                active_page,
                ['input[name*="linkedin" i]', 'input[id*="linkedin" i]'],
                linkedin,
            ),
            "github": self._fill_if_empty(
                active_page,
                ['input[name*="github" i]', 'input[id*="github" i]'],
                github,
            ),
        }

        resume_ok = self._upload_resume(active_page, context.resume_path)
        if not resume_ok:
            return AdapterResult(
                status="review",
                review_required=True,
                message="BrassRing resume upload control was not found or could not be filled.",
                blockers=[{"category": "resume", "reason": "resume_upload_failed"}],
                metadata={
                    "standard_fields": standard,
                    "account_state": account.state,
                    "page_url": active_page.url,
                },
            )

        memory = ApplicationMemory()
        try:
            questions = fill_generic_form_questions(
                active_page,
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
        submit = self._find_submit(active_page)

        if submit is None and not detect_submission_confirmation(active_page):
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
                metadata={"standard_fields": standard, "resume_uploaded": True, "page_url": active_page.url},
            )

        if not submission.may_submit:
            return AdapterResult(
                status="ready_for_review",
                review_required=False,
                submitted=False,
                message=submission.reason,
                decisions=decisions,
                metadata={"standard_fields": standard, "resume_uploaded": True, "page_url": active_page.url},
            )

        try:
            submit.click(timeout=5000)
            active_page.wait_for_timeout(1500)
        except Exception as exc:
            return AdapterResult(
                status="review",
                review_required=True,
                message="BrassRing submit click failed.",
                blockers=[{"category": "submit", "reason": str(exc)}],
                decisions=decisions,
            )

        if detect_submission_confirmation(active_page):
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
