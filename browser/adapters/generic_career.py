from __future__ import annotations

from pathlib import Path

from agent.submission_policy import SubmissionPolicy
from browser.account_manager import handle_account_page
from browser.submission_detector import detect_submission_confirmation
from learning.application_memory import ApplicationMemory
from pipeline.ats import ATS_CAREER_SITE, detect_ats

from .base import AdapterResult, ApplicationContext, ATSAdapter
from .generic_questions import fill_generic_form_questions


class GenericCareerSiteAdapter(ATSAdapter):
    """
    Conservative fallback for public career sites that do not have a dedicated ATS
    adapter yet. It follows the common real-world state machine:

      job -> apply -> sign-in/create-account -> verification -> resume/profile ->
      multi-step questions -> review -> submit confirmation

    Sensitive/legal questions still flow through the normal review/submission policy.
    """

    name = ATS_CAREER_SITE

    def supports(self, job) -> bool:
        return detect_ats(job.url) == ATS_CAREER_SITE

    @staticmethod
    def _first_visible(page, selectors):
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
    def _control(page, names):
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
        element = GenericCareerSiteAdapter._first_visible(page, selectors)
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
    def _page_context_text(page, limit: int = 18000) -> str:
        """Capture visible public job context before Apply hides/replaces it."""
        pieces = []
        for frame in page.frames:
            try:
                body = frame.locator("body")
                if not body.count() or not body.first.is_visible():
                    continue
                text = body.first.inner_text(timeout=1500).strip()
            except Exception:
                continue
            if text:
                pieces.append(text)
        value = "\n".join(pieces)
        return value[: max(0, int(limit))]

    @staticmethod
    def _application_surface_present(page) -> bool:
        selectors = (
            'input[type="file"]',
            'input[type="email"]',
            'input[type="password"]',
            'input[name*="first" i]',
            'input[name*="last" i]',
            'textarea',
            'select',
            '[role="combobox"]',
        )
        return GenericCareerSiteAdapter._first_visible(page, selectors) is not None

    @staticmethod
    def _find_apply(page):
        return GenericCareerSiteAdapter._control(
            page,
            (
                "Apply Now",
                "Apply now",
                "Apply to job",
                "Apply To Job",
                "Apply for this job",
                "Apply to this job",
                "Start Application",
                "Start application",
                "Quick Apply",
                "Apply",
            ),
        )

    @staticmethod
    def _find_next(page):
        return GenericCareerSiteAdapter._control(
            page,
            (
                "Save and Continue",
                "Save & Continue",
                "Continue Application",
                "Continue application",
                "Continue",
                "Next Step",
                "Next step",
                "Next",
            ),
        )

    @staticmethod
    def _find_submit(page):
        button = GenericCareerSiteAdapter._control(
            page,
            (
                "Submit Application",
                "Submit application",
                "Complete Application",
                "Complete application",
                "Finish Application",
                "Finish application",
                "Submit",
            ),
        )
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
                    if not item.is_visible() or not item.is_enabled():
                        continue
                    label = (
                        item.get_attribute("value")
                        or item.get_attribute("aria-label")
                        or item.inner_text(timeout=300)
                        or ""
                    ).lower()
                    if "submit" in label or "finish" in label or "complete application" in label:
                        return item
                except Exception:
                    continue
        return None

    @staticmethod
    def _upload_resume_if_present(page, resume_path: str):
        path = Path(resume_path)
        if not path.exists() or not path.is_file():
            return False

        name = path.name.lower()
        try:
            for frame in page.frames:
                body = frame.locator("body")
                if body.count() and body.first.is_visible():
                    if name in body.first.inner_text(timeout=500).lower():
                        return True
        except Exception:
            pass

        found = False
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
                    items = frame.locator(selector)
                except Exception:
                    continue
                for index in range(items.count()):
                    found = True
                    try:
                        items.nth(index).set_input_files(str(path.resolve()))
                        page.wait_for_timeout(800)
                        return True
                    except Exception:
                        continue
        return False if found else None

    def _open_application(self, page):
        apply = self._find_apply(page)
        if apply is None:
            return page, False

        context = page.context
        before = list(context.pages)
        try:
            apply.scroll_into_view_if_needed(timeout=1500)
        except Exception:
            pass
        try:
            apply.click(timeout=7000)
        except Exception:
            try:
                apply.click(timeout=3000, force=True)
            except Exception:
                return page, False

        page.wait_for_timeout(1400)
        created = [candidate for candidate in context.pages if candidate not in before]
        target = created[-1] if created else page
        try:
            target.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        try:
            target.bring_to_front()
        except Exception:
            pass
        target.wait_for_timeout(400)
        return target, True

    def _resume_page(self, page, context: ApplicationContext):
        remembered = str(context.metadata.get("generic_page_url") or "")
        pages = list(page.context.pages)
        if remembered:
            for candidate in reversed(pages):
                try:
                    if not candidate.is_closed() and candidate.url == remembered:
                        return candidate
                except Exception:
                    continue
        for candidate in reversed(pages):
            try:
                if candidate.is_closed():
                    continue
            except Exception:
                continue
            if self._application_surface_present(candidate):
                return candidate
        return pages[-1] if pages else page

    @staticmethod
    def _metadata(page, **extra):
        data = {"active_page_url": page.url}
        data.update(extra)
        return data

    def run(self, page, profile, context: ApplicationContext) -> AdapterResult:
        resume_current = bool(context.metadata.get("resume_current_page"))
        job_context_text = str(
            context.job.description
            or context.metadata.get("generic_job_text")
            or ""
        ).strip()

        if not resume_current:
            page.goto(context.job.url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(1100)

            # Direct generic ATS URLs are often ingested without metadata. Keep
            # the visible job posting text before clicking Apply so questions such
            # as "Why <Company>?" can be answered from the actual posting instead
            # of being blocked for missing context.
            if not job_context_text:
                job_context_text = self._page_context_text(page)
                if job_context_text:
                    context.metadata["generic_job_text"] = job_context_text

            if detect_submission_confirmation(page):
                return AdapterResult(
                    status="submitted",
                    submitted=True,
                    message="Submission confirmation detected.",
                    metadata=self._metadata(page),
                )

            active = page
            if not self._application_surface_present(active):
                active, opened = self._open_application(active)
                if not opened and not self._application_surface_present(active):
                    return AdapterResult(
                        status="review",
                        review_required=True,
                        message="No supported Apply control or application form was detected on this career site.",
                        blockers=[{"category": "apply_control", "reason": "application_surface_not_open"}],
                        metadata=self._metadata(active),
                    )
        else:
            active = self._resume_page(page, context)
            active.wait_for_timeout(300)
            if not job_context_text:
                job_context_text = self._page_context_text(active)
                if job_context_text:
                    context.metadata["generic_job_text"] = job_context_text

        context.metadata["generic_page_url"] = active.url
        decisions = []
        resume_seen = False

        for step in range(12):
            if detect_submission_confirmation(active):
                return AdapterResult(
                    status="submitted",
                    submitted=True,
                    message="Submission confirmation detected.",
                    decisions=decisions,
                    metadata=self._metadata(active, resume_uploaded=resume_seen),
                )

            account = handle_account_page(active, profile)
            if account.verification_required:
                return AdapterResult(
                    status="verification_required",
                    review_required=True,
                    message=account.message,
                    blockers=[{
                        "category": "verification",
                        "reason": "Complete CAPTCHA/MFA/email verification in the browser.",
                    }],
                    metadata=self._metadata(active, account_state=account.state),
                )
            if account.blockers:
                return AdapterResult(
                    status="account_review",
                    review_required=True,
                    message=account.message,
                    blockers=account.blockers,
                    metadata=self._metadata(active, account_state=account.state),
                )

            standard = {
                "first_name": self._fill_if_empty(
                    active,
                    ['input[name*="first" i]', 'input[id*="first" i]', 'input[autocomplete="given-name"]'],
                    profile.get("application_defaults.first_name"),
                ),
                "last_name": self._fill_if_empty(
                    active,
                    ['input[name*="last" i]', 'input[id*="last" i]', 'input[autocomplete="family-name"]'],
                    profile.get("application_defaults.last_name"),
                ),
                "email": self._fill_if_empty(
                    active,
                    ['input[type="email"]', 'input[name*="email" i]', 'input[id*="email" i]'],
                    profile.get("candidate.email"),
                ),
                "phone": self._fill_if_empty(
                    active,
                    ['input[type="tel"]', 'input[name*="phone" i]', 'input[id*="phone" i]'],
                    profile.get("application_defaults.phone_number") or profile.get("candidate.phone"),
                ),
                "linkedin": self._fill_if_empty(
                    active,
                    ['input[name*="linkedin" i]', 'input[id*="linkedin" i]'],
                    profile.get("candidate.linkedin"),
                ),
                "github": self._fill_if_empty(
                    active,
                    ['input[name*="github" i]', 'input[id*="github" i]'],
                    profile.get("candidate.github"),
                ),
            }

            upload = self._upload_resume_if_present(active, context.resume_path)
            if upload is False:
                return AdapterResult(
                    status="review",
                    review_required=True,
                    message="A resume upload control was found, but the generated resume could not be uploaded.",
                    blockers=[{"category": "resume", "reason": "resume_upload_failed"}],
                    decisions=decisions,
                    metadata=self._metadata(active, standard_fields=standard),
                )
            if upload is True:
                resume_seen = True

            memory = ApplicationMemory()
            try:
                questions = fill_generic_form_questions(
                    active,
                    profile,
                    company=context.company or context.job.company,
                    ats=self.name,
                    job_text=job_context_text,
                    memory=memory,
                )
            finally:
                memory.close()

            step_decisions = questions.get("decisions") or []
            decisions.extend(step_decisions)
            blockers = list(questions.get("blockers") or [])
            if blockers:
                return AdapterResult(
                    status="review",
                    review_required=True,
                    message="Application requires review before it can continue.",
                    blockers=blockers,
                    decisions=decisions,
                    metadata=self._metadata(
                        active,
                        standard_fields=standard,
                        resume_uploaded=resume_seen,
                        job_context_chars=len(job_context_text),
                    ),
                )

            submit = self._find_submit(active)
            if submit is not None:
                submission = SubmissionPolicy(context.submission_mode).decide(
                    decisions,
                    validation_errors=[],
                )
                if not submission.may_submit:
                    return AdapterResult(
                        status="ready_for_review",
                        submitted=False,
                        message=submission.reason,
                        decisions=decisions,
                        metadata=self._metadata(active, standard_fields=standard, resume_uploaded=resume_seen),
                    )

                try:
                    submit.click(timeout=5000)
                    active.wait_for_timeout(1400)
                except Exception as exc:
                    return AdapterResult(
                        status="review",
                        review_required=True,
                        message="Submit click failed.",
                        blockers=[{"category": "submit", "reason": str(exc)}],
                        decisions=decisions,
                        metadata=self._metadata(active),
                    )

                if detect_submission_confirmation(active):
                    return AdapterResult(
                        status="submitted",
                        submitted=True,
                        message="Application submitted and confirmation detected.",
                        decisions=decisions,
                        metadata=self._metadata(active, resume_uploaded=resume_seen),
                    )

                active.wait_for_timeout(400)
                continue

            next_button = self._find_next(active)
            if next_button is not None:
                try:
                    next_button.click(timeout=5000)
                    active.wait_for_timeout(1000)
                except Exception as exc:
                    return AdapterResult(
                        status="review",
                        review_required=True,
                        message="Could not advance to the next application step.",
                        blockers=[{"category": "navigation", "reason": str(exc)}],
                        decisions=decisions,
                        metadata=self._metadata(active),
                    )

                pages = list(active.context.pages)
                if pages and pages[-1] is not active:
                    candidate = pages[-1]
                    try:
                        if not candidate.is_closed():
                            active = candidate
                            active.bring_to_front()
                    except Exception:
                        pass
                context.metadata["generic_page_url"] = active.url
                continue

            apply = self._find_apply(active)
            if apply is not None:
                active, opened = self._open_application(active)
                context.metadata["generic_page_url"] = active.url
                if opened:
                    continue

            return AdapterResult(
                status="review",
                review_required=True,
                message="The career site reached a page with no safe automatic next action.",
                blockers=[{"category": "navigation", "reason": "no_safe_next_action"}],
                decisions=decisions,
                metadata=self._metadata(active, standard_fields=standard, resume_uploaded=resume_seen),
            )

        return AdapterResult(
            status="review",
            review_required=True,
            message="Application exceeded the automatic step limit and needs review.",
            blockers=[{"category": "navigation", "reason": "step_limit_reached"}],
            decisions=decisions,
            metadata=self._metadata(active, resume_uploaded=resume_seen),
        )
