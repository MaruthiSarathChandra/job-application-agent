from __future__ import annotations

from pathlib import Path

from agent.submission_policy import SubmissionPolicy
from browser.account_manager import handle_account_page
from browser.workday_conflict_questions import fill_conflict_questions
from browser.workday_experience import fill_experience_and_education
from browser.workday_generic_questions import fill_generic_questions
from browser.workday_router import wait_for_application_step, wait_for_step_change
from browser.workday_runner import (
    fill_my_information,
    find_continue_button,
    find_submit_button,
    upload_resume,
)
from learning.application_memory import ApplicationMemory
from pipeline.ats import ATS_WORKDAY, detect_ats

from .base import AdapterResult, ApplicationContext, ATSAdapter


NEGATIVE_ALERT_MARKERS = (
    "error",
    "invalid",
    "required",
    "missing",
    "failed",
    "unable",
    "cannot",
    "can't",
    "please correct",
    "must be",
)

SUCCESS_ALERT_MARKERS = (
    "successfully uploaded",
    "upload complete",
    "saved successfully",
    "successfully saved",
)


class WorkdayAdapter(ATSAdapter):
    name = ATS_WORKDAY

    def supports(self, job) -> bool:
        return detect_ats(job.url) == ATS_WORKDAY

    @staticmethod
    def _norm(value) -> str:
        return " ".join(str(value or "").strip().lower().split())

    def _validation_errors(self, page):
        errors = []
        seen = set()

        for frame in page.frames:
            try:
                invalid = frame.locator('[aria-invalid="true"]')
            except Exception:
                continue

            for index in range(min(invalid.count(), 100)):
                element = invalid.nth(index)
                try:
                    if not element.is_visible():
                        continue
                    required = (
                        self._norm(element.get_attribute("aria-required")) == "true"
                        or element.get_attribute("required") is not None
                    )
                except Exception:
                    continue
                if not required:
                    continue

                try:
                    label = (
                        element.get_attribute("aria-label")
                        or element.get_attribute("name")
                        or element.get_attribute("placeholder")
                        or "required field"
                    )
                except Exception:
                    label = "required field"
                message = f"Invalid required field: {label}"
                key = self._norm(message)
                if key not in seen:
                    seen.add(key)
                    errors.append(message)

        for frame in page.frames:
            selectors = [
                '[data-automation-id="errorMessage"]',
                '[data-automation-id*="errorMessage"]',
                '[data-automation-id*="validation"]',
                '[role="alert"]',
            ]
            for selector in selectors:
                try:
                    items = frame.locator(selector)
                except Exception:
                    continue

                for index in range(min(items.count(), 80)):
                    item = items.nth(index)
                    try:
                        if not item.is_visible():
                            continue
                        text = item.inner_text(timeout=500).strip()
                    except Exception:
                        continue

                    normalized = self._norm(text)
                    if not normalized or normalized in seen:
                        continue
                    if any(marker in normalized for marker in SUCCESS_ALERT_MARKERS):
                        continue

                    # role=alert is also used for positive upload notifications.
                    # Keep it only when it actually resembles an error.
                    if selector == '[role="alert"]' and not any(
                        marker in normalized for marker in NEGATIVE_ALERT_MARKERS
                    ):
                        continue

                    seen.add(normalized)
                    errors.append(text)

        return errors

    @staticmethod
    def _apply_url(url: str) -> str:
        value = (url or "").rstrip("/")
        return value if value.endswith("/apply") else value + "/apply"

    def _advance(self, page, old_step):
        button = find_continue_button(page)
        if button is None:
            return None
        try:
            button.scroll_into_view_if_needed()
            page.wait_for_timeout(150)
            button.click(timeout=5000)
        except Exception:
            return None

        result = wait_for_step_change(page, old_step, timeout_ms=25000)
        if result.get("step") not in {old_step, "unknown"}:
            return result
        return None

    def run(self, page, profile, context: ApplicationContext) -> AdapterResult:
        page.goto(self._apply_url(context.job.url), wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(1200)

        route = wait_for_application_step(page, timeout_ms=6000)
        if route.get("step") == "unknown":
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
            if not account.ready:
                # Some Workday tenants show an intermediate shell after account
                # handling. Give the wizard one more chance to render.
                page.wait_for_timeout(1200)

        route = wait_for_application_step(page, timeout_ms=15000)
        if route.get("step") == "unknown":
            return AdapterResult(
                status="review",
                review_required=True,
                message="Workday application wizard could not be identified after account handling.",
                blockers=[{"category": "routing", "reason": route.get("evidence", "unknown step")}],
            )

        decisions = []
        memory = ApplicationMemory()

        try:
            for iteration in range(1, 14):
                route = wait_for_application_step(page, timeout_ms=10000)
                step = route.get("step", "unknown")

                if step == "review" or find_submit_button(page) is not None:
                    errors = self._validation_errors(page)
                    policy = SubmissionPolicy(context.submission_mode)
                    decision = policy.decide(decisions, validation_errors=errors)

                    if errors:
                        return AdapterResult(
                            status="review",
                            review_required=True,
                            message="Workday Review page still has validation errors.",
                            blockers=[{"category": "validation", "reason": value} for value in errors],
                            decisions=decisions,
                        )

                    if not decision.may_submit:
                        return AdapterResult(
                            status="ready_for_review",
                            review_required=False,
                            submitted=False,
                            message=decision.reason,
                            decisions=decisions,
                            metadata={"workday_step": step},
                        )

                    submit = find_submit_button(page)
                    if submit is None:
                        return AdapterResult(
                            status="review",
                            review_required=True,
                            message="Safe-submit policy passed but Workday Submit button was not found.",
                            blockers=[{"category": "submit_control", "reason": "button_not_found"}],
                            decisions=decisions,
                        )

                    try:
                        submit.click(timeout=5000)
                        page.wait_for_timeout(1200)
                    except Exception as exc:
                        return AdapterResult(
                            status="review",
                            review_required=True,
                            message="Workday Submit click failed.",
                            blockers=[{"category": "submit", "reason": str(exc)}],
                            decisions=decisions,
                        )

                    return AdapterResult(
                        status="submitted",
                        submitted=True,
                        message="Workday application submitted after the safe-submit policy passed.",
                        decisions=decisions,
                    )

                if step == "my_information":
                    result = fill_my_information(
                        page,
                        profile,
                        context.company or context.job.company,
                    )
                    blockers = result.get("blockers") or []
                    if blockers:
                        return AdapterResult(
                            status="review",
                            review_required=True,
                            message="Workday My Information needs review.",
                            blockers=blockers,
                            decisions=decisions,
                        )

                elif step == "my_experience":
                    if not upload_resume(page, context.resume_path):
                        return AdapterResult(
                            status="review",
                            review_required=True,
                            message="Workday resume upload failed.",
                            blockers=[{"category": "resume", "reason": "upload_failed"}],
                            decisions=decisions,
                        )
                    page.wait_for_timeout(900)
                    result = fill_experience_and_education(page, profile)
                    if not result.get("ready_to_continue"):
                        return AdapterResult(
                            status="review",
                            review_required=True,
                            message="Workday experience/education needs review.",
                            blockers=[{
                                "category": "experience",
                                "reason": "required experience/education/skills field unresolved",
                                "detail": result,
                            }],
                            decisions=decisions,
                        )

                elif step == "application_questions_1":
                    result = fill_conflict_questions(page, profile)
                    decisions.append({
                        "question": "Workday conflict-of-interest questions",
                        "answer": "profile-driven" if result.get("ready") else None,
                        "source": "LOCKED_PROFILE",
                        "confidence": 1.0,
                        "review_required": not bool(result.get("ready")),
                        "category": "conflict_of_interest",
                        "rationale": "State Street/Workday conflict answers must come from explicit profile values.",
                    })
                    if not result.get("ready"):
                        return AdapterResult(
                            status="review",
                            review_required=True,
                            message="Workday conflict-of-interest questions require explicit user/profile values.",
                            blockers=[result],
                            decisions=decisions,
                        )

                elif step == "application_questions_2":
                    result = fill_generic_questions(
                        page,
                        profile,
                        job_text=context.job.description,
                        company=context.company or context.job.company,
                        ats=self.name,
                        memory=memory,
                    )
                    decisions.extend(result.get("decisions") or [])
                    if result.get("blockers"):
                        return AdapterResult(
                            status="review",
                            review_required=True,
                            message="Workday Application Questions require review.",
                            blockers=result.get("blockers") or [],
                            decisions=decisions,
                        )

                elif step in {"voluntary_disclosures", "self_identify"}:
                    result = fill_generic_questions(
                        page,
                        profile,
                        job_text=context.job.description,
                        company=context.company or context.job.company,
                        ats=self.name,
                        memory=memory,
                    )
                    decisions.extend(result.get("decisions") or [])
                    if result.get("blockers"):
                        return AdapterResult(
                            status="review",
                            review_required=True,
                            message=f"Workday {step} requires manual/voluntary review.",
                            blockers=result.get("blockers") or [],
                            decisions=decisions,
                        )

                else:
                    return AdapterResult(
                        status="review",
                        review_required=True,
                        message=f"Unsupported Workday wizard step: {step}",
                        blockers=[{"category": "routing", "reason": route.get("evidence", "unknown")}],
                        decisions=decisions,
                    )

                errors = self._validation_errors(page)
                if errors:
                    return AdapterResult(
                        status="review",
                        review_required=True,
                        message=f"Workday {step} has validation errors.",
                        blockers=[{"category": "validation", "reason": value} for value in errors],
                        decisions=decisions,
                    )

                if self._advance(page, step) is None:
                    return AdapterResult(
                        status="review",
                        review_required=True,
                        message=f"Workday could not advance from {step}.",
                        blockers=[{"category": "navigation", "reason": "Save and Continue did not advance"}],
                        decisions=decisions,
                    )

            return AdapterResult(
                status="review",
                review_required=True,
                message="Workday maximum transition limit reached.",
                blockers=[{"category": "routing", "reason": "transition_limit"}],
                decisions=decisions,
            )
        finally:
            memory.close()
