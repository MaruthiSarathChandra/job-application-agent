from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from agent.submission_policy import SubmissionPolicy
from browser.account_manager import handle_account_page
from browser.submission_detector import detect_submission_confirmation
from learning.application_memory import ApplicationMemory
from pipeline.ats import ATS_AVATURE, detect_ats

from .base import AdapterResult, ApplicationContext, ATSAdapter
from .generic_questions import fill_generic_form_questions


CLOSED_MARKERS = (
    "job is no longer available",
    "position is no longer available",
    "job posting is no longer available",
    "this job has been filled",
    "this position has been filled",
    "job has expired",
)


def _norm(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def normalize_avature_job_url(url: str) -> str:
    """
    Convert Avature confirmation-style deep links back to a stable JobDetail URL.

    MetLife/Avature links from job boards can point at ApplicationConfirmation
    with a jobId even before an application has been started. The public JobDetail
    route accepts the same jobId and is the correct place to begin automation.
    """
    parsed = urlparse((url or "").strip())
    if not parsed.scheme or not parsed.netloc:
        return url

    if "/applicationconfirmation" not in parsed.path.lower():
        return url

    params = parse_qsl(parsed.query, keep_blank_values=True)
    job_id = ""
    source = ""
    for key, value in params:
        if key.lower() == "jobid" and value:
            job_id = value
        elif key.lower() == "source" and value:
            source = value

    if not job_id:
        return url

    prefix = parsed.path.rsplit("/", 1)[0]
    new_query = [("jobId", job_id)]
    if source:
        new_query.append(("source", source))

    return urlunparse(
        parsed._replace(
            path=f"{prefix}/JobDetail",
            query=urlencode(new_query),
            fragment="",
        )
    )


def classify_avature_page(text: str) -> str:
    normalized = _norm(text)
    if any(marker in normalized for marker in CLOSED_MARKERS):
        return "closed"
    return "open"


class AvatureAdapter(ATSAdapter):
    name = ATS_AVATURE

    def supports(self, job) -> bool:
        return detect_ats(job.url) == ATS_AVATURE

    @staticmethod
    def _page_text(page) -> str:
        parts = []
        for frame in page.frames:
            try:
                body = frame.locator("body")
                if body.count() and body.first.is_visible():
                    parts.append(body.first.inner_text(timeout=1000))
            except Exception:
                continue
        return "\n".join(parts)

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
        element = AvatureAdapter._first_visible(page, selectors)
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
        return name in AvatureAdapter._page_text(page).lower()

    @staticmethod
    def _upload_resume_if_present(page, resume_path: str):
        """Return True on upload/present, False on upload failure, None when no control exists."""
        path = Path(resume_path)
        if not path.exists() or not path.is_file():
            return False
        if AvatureAdapter._resume_present(page, resume_path):
            return True

        found = False
        selectors = (
            'input[type="file"][name*="resume" i]',
            'input[type="file"][id*="resume" i]',
            'input[type="file"][aria-label*="resume" i]',
            'input[type="file"]',
        )
        for frame in page.frames:
            for selector in selectors:
                try:
                    items = frame.locator(selector)
                except Exception:
                    continue
                for index in range(items.count()):
                    element = items.nth(index)
                    found = True
                    try:
                        element.set_input_files(str(path.resolve()))
                        page.wait_for_timeout(900)
                        return True
                    except Exception:
                        continue
        return False if found else None

    @staticmethod
    def _find_apply(page):
        return AvatureAdapter._button_or_link(
            page,
            (
                "Apply Now",
                "Apply now",
                "Apply for this job",
                "Apply to job",
                "Apply",
                "Start Application",
                "Start application",
            ),
        )

    @staticmethod
    def _find_next(page):
        return AvatureAdapter._button_or_link(
            page,
            (
                "Save and Continue",
                "Save & Continue",
                "Continue Application",
                "Continue application",
                "Continue",
                "Next",
            ),
        )

    @staticmethod
    def _find_submit(page):
        button = AvatureAdapter._button_or_link(
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
                submits = frame.locator('button[type="submit"], input[type="submit"]')
            except Exception:
                continue
            for index in range(submits.count()):
                item = submits.nth(index)
                try:
                    if item.is_visible() and item.is_enabled():
                        value = ""
                        try:
                            value = item.get_attribute("value") or item.inner_text(timeout=300)
                        except Exception:
                            pass
                        if "submit" in _norm(value) or "finish" in _norm(value):
                            return item
                except Exception:
                    continue
        return None

    @staticmethod
    def _application_surface_present(page) -> bool:
        selectors = (
            'input[type="file"]',
            'input[type="email"]',
            'input[name*="first" i]',
            'input[name*="last" i]',
            'textarea',
            'select',
        )
        return AvatureAdapter._first_visible(page, selectors) is not None

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

        page.wait_for_timeout(1600)
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
        target.wait_for_timeout(500)
        return target, True

    def _resume_page(self, page, context: ApplicationContext):
        remembered = str(context.metadata.get("avature_page_url") or "")
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

        if not resume_current:
            target_url = normalize_avature_job_url(context.job.url)
            page.goto(target_url, wait_until="domcontentloaded", timeout=90000)
            page.wait_for_timeout(1200)

            if classify_avature_page(self._page_text(page)) == "closed":
                return AdapterResult(
                    status="closed",
                    message="Avature job is closed or no longer available; skipped.",
                    metadata=self._metadata(page),
                )

            if detect_submission_confirmation(page):
                return AdapterResult(
                    status="submitted",
                    submitted=True,
                    message="Avature submission confirmation detected.",
                    metadata=self._metadata(page),
                )

            active, opened = self._open_application(page)
            if not opened and not self._application_surface_present(page):
                return AdapterResult(
                    status="review",
                    review_required=True,
                    message="Avature Apply control was not found or did not open an application form.",
                    blockers=[{"category": "apply_control", "reason": "application_surface_not_open"}],
                    metadata=self._metadata(page),
                )
        else:
            active = self._resume_page(page, context)
            active.wait_for_timeout(300)

        context.metadata["avature_page_url"] = active.url

        decisions = []
        resume_seen = False

        for step in range(8):
            if detect_submission_confirmation(active):
                return AdapterResult(
                    status="submitted",
                    submitted=True,
                    message="Avature submission confirmation detected.",
                    decisions=decisions,
                    metadata=self._metadata(active, resume_uploaded=resume_seen),
                )

            if classify_avature_page(self._page_text(active)) == "closed":
                return AdapterResult(
                    status="closed",
                    message="Avature job is closed or no longer available; skipped.",
                    metadata=self._metadata(active),
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
                    message="Avature displayed a resume upload control, but the generated resume could not be uploaded.",
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
                    job_text=context.job.description,
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
                    message="Avature application requires review before it can continue.",
                    blockers=blockers,
                    decisions=decisions,
                    metadata=self._metadata(active, standard_fields=standard, resume_uploaded=resume_seen),
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
                        message="Avature submit click failed.",
                        blockers=[{"category": "submit", "reason": str(exc)}],
                        decisions=decisions,
                        metadata=self._metadata(active),
                    )

                if detect_submission_confirmation(active):
                    return AdapterResult(
                        status="submitted",
                        submitted=True,
                        message="Avature application submitted and confirmation detected.",
                        decisions=decisions,
                        metadata=self._metadata(active, resume_uploaded=resume_seen),
                    )
                return AdapterResult(
                    status="review",
                    review_required=True,
                    message="Avature submit was clicked, but no submission confirmation was detected.",
                    blockers=[{"category": "submit_confirmation", "reason": "confirmation_not_detected"}],
                    decisions=decisions,
                    metadata=self._metadata(active),
                )

            next_button = self._find_next(active)
            if next_button is None:
                return AdapterResult(
                    status="review",
                    review_required=True,
                    message="Avature application page has no recognized Continue/Next/Submit control.",
                    blockers=[{"category": "navigation_control", "reason": "continue_or_submit_not_found"}],
                    decisions=decisions,
                    metadata=self._metadata(active, standard_fields=standard, resume_uploaded=resume_seen),
                )

            before_pages = list(active.context.pages)
            try:
                next_button.click(timeout=5000)
                active.wait_for_timeout(900)
            except Exception as exc:
                return AdapterResult(
                    status="review",
                    review_required=True,
                    message="Avature Continue/Next click failed.",
                    blockers=[{"category": "navigation", "reason": str(exc)}],
                    decisions=decisions,
                    metadata=self._metadata(active),
                )

            new_pages = [candidate for candidate in active.context.pages if candidate not in before_pages]
            if new_pages:
                active = new_pages[-1]
                try:
                    active.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
            context.metadata["avature_page_url"] = active.url

        return AdapterResult(
            status="review",
            review_required=True,
            message="Avature application exceeded the safe automatic navigation step limit.",
            blockers=[{"category": "navigation", "reason": "step_limit_reached"}],
            decisions=decisions,
            metadata=self._metadata(active, resume_uploaded=resume_seen),
        )
