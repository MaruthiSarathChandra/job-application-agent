import sys
import json
import hashlib
from pathlib import Path

from playwright.sync_api import sync_playwright


# ======================================================
# PROJECT ROOT
# ======================================================

ROOT = Path(__file__).resolve().parents[1]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from agent.profile import CandidateProfile
from agent.field_classifier import classify_field
from agent.company_policy import has_worked_for_company

from browser.form_filler import (
    get_live_page,
    collect_fields,
    fill_profile_field,
    safe_label,
)
from browser.workday_experience import (
    fill_experience_and_education,
)
from browser.workday_conflict_questions import (
    fill_conflict_questions,
)

# ======================================================
# PATHS
# ======================================================
REPORT_DIR = Path("data/workday_runs")
BROWSER_PROFILE = Path("data/browser_profile")

RESUME_FILE = Path(
    "resumes/resume_7_months.docx"
)
# ======================================================
# BASIC HELPERS
# ======================================================

def normalize_text(value):

    if value is None:
        return ""

    return " ".join(
        str(value)
        .strip()
        .lower()
        .split()
    )


def safe_attr(element, name):

    try:
        return element.get_attribute(name)

    except Exception:
        return None


# ======================================================
# SECTION NAME
# ======================================================

def get_section_title(page):

    selectors = [
        '[data-automation-id="pageHeaderTitle"]',
        '[data-automation-id="sectionTitle"]',
        '[data-automation-id*="pageTitle"]',
        "h1",
        "h2",
        "h3",
    ]

    ignored_fragments = [
        "accept cookies",
        "giving consent to cookies",
        "learn more",
        "state street careers",
    ]

    for frame in page.frames:

        for selector in selectors:

            try:

                items = frame.locator(selector)

                for index in range(
                    min(items.count(), 30)
                ):

                    item = items.nth(index)

                    try:

                        if not item.is_visible():
                            continue

                        text = (
                            item.inner_text(
                                timeout=1000
                            )
                            .strip()
                        )

                    except Exception:
                        continue

                    if not text:
                        continue

                    normalized = normalize_text(
                        text
                    )

                    if any(
                        fragment
                        in normalized
                        for fragment
                        in ignored_fragments
                    ):
                        continue

                    if len(text) > 180:
                        continue

                    return text

            except Exception:
                continue

    return "UNKNOWN_SECTION"


# ======================================================
# CURRENT FORM FINGERPRINT
# ======================================================

def get_page_fingerprint(page):
    """
    Fingerprint only meaningful application UI.

    We intentionally do not hash the entire body because
    Workday may update temporary messages while staying
    on the same application section.
    """

    pieces = [
        page.url,
        get_section_title(page),
    ]

    selectors = [
        "h1",
        "h2",
        "h3",
        '[aria-current="step"]',
        '[data-automation-id*="progress"]',
        'input:not([type="hidden"])',
        "textarea",
        "select",
        'button[aria-haspopup="listbox"]',
        'button[type="submit"]',
        'input[type="file"]',
    ]

    for frame_index, frame in enumerate(
        page.frames
    ):

        for selector in selectors:

            try:

                elements = frame.locator(
                    selector
                )

                count = min(
                    elements.count(),
                    150
                )

            except Exception:
                continue

            for index in range(count):

                element = elements.nth(
                    index
                )

                try:

                    if (
                        selector != 'input[type="file"]'
                        and
                        not element.is_visible()
                    ):
                        continue

                    tag = element.evaluate(
                        "el => el.tagName.toLowerCase()"
                    )

                    element_id = (
                        safe_attr(
                            element,
                            "id"
                        )
                        or ""
                    )

                    name = (
                        safe_attr(
                            element,
                            "name"
                        )
                        or ""
                    )

                    element_type = (
                        safe_attr(
                            element,
                            "type"
                        )
                        or ""
                    )

                    text = ""

                    if tag in {
                        "button",
                        "h1",
                        "h2",
                        "h3",
                    }:

                        try:

                            text = (
                                element
                                .inner_text(
                                    timeout=500
                                )
                                .strip()
                            )

                        except Exception:
                            pass

                    value = ""

                    if tag in {
                        "input",
                        "textarea",
                        "select",
                    }:

                        try:

                            value = (
                                element
                                .input_value(
                                    timeout=500
                                )
                            )

                        except Exception:
                            pass

                    pieces.append(
                        "|".join(
                            [
                                str(frame_index),
                                tag,
                                element_id,
                                name,
                                element_type,
                                normalize_text(text),
                                normalize_text(value),
                            ]
                        )
                    )

                except Exception:
                    continue

    joined = "\n".join(
        pieces
    )

    return hashlib.sha256(
        joined.encode("utf-8")
    ).hexdigest()


# ======================================================
# VALIDATION ERRORS
# ======================================================

def get_validation_errors(page):

    errors = []
    seen = set()

    # --------------------------------------------------
    # Explicit Workday errors
    # --------------------------------------------------

    selectors = [
        '[role="alert"]',
        '[data-automation-id="errorMessage"]',
        '[data-automation-id*="errorMessage"]',
        '[data-automation-id*="validation"]',
    ]

    for frame in page.frames:

        for selector in selectors:

            try:

                elements = frame.locator(
                    selector
                )

                for index in range(
                    min(elements.count(), 50)
                ):

                    element = elements.nth(
                        index
                    )

                    try:

                        if not element.is_visible():
                            continue

                        text = (
                            element
                            .inner_text(
                                timeout=1000
                            )
                            .strip()
                        )

                    except Exception:
                        continue

                    normalized = normalize_text(
                        text
                    )

                    if not normalized:
                        continue

                    if normalized in seen:
                        continue

                    seen.add(
                        normalized
                    )

                    errors.append(
                        text
                    )

            except Exception:
                continue

    # --------------------------------------------------
    # aria-invalid controls: block only required fields.
    # --------------------------------------------------

    for frame in page.frames:

        try:

            invalid = frame.locator(
                '[aria-invalid="true"]'
            )

            for index in range(
                min(invalid.count(), 50)
            ):

                element = invalid.nth(
                    index
                )

                try:

                    if not element.is_visible():
                        continue

                    aria_required = (
                        element.get_attribute(
                            "aria-required"
                        )
                        or ""
                    ).strip().lower()

                    required_attr = (
                        element.get_attribute(
                            "required"
                        )
                    )

                    if (
                        aria_required != "true"
                        and
                        required_attr is None
                    ):
                        continue

                    label = safe_label(
                        frame,
                        element
                    )

                except Exception:
                    label = "Unknown required field"

                text = (
                    f"Invalid required field: {label}"
                )

                normalized = normalize_text(
                    text
                )

                if normalized in seen:
                    continue

                seen.add(
                    normalized
                )

                errors.append(
                    text
                )

        except Exception:
            continue

    return errors


# ======================================================
# FILE / RESUME DETECTION
# ======================================================

def detect_file_upload(page):

    results = []

    for frame_index, frame in enumerate(
        page.frames
    ):

        try:

            inputs = frame.locator(
                'input[type="file"]'
            )

            for index in range(
                inputs.count()
            ):

                element = inputs.nth(
                    index
                )

                results.append(
                    {
                        "frame_index":
                            frame_index,

                        "element_index":
                            index,

                        "id":
                            safe_attr(
                                element,
                                "id"
                            ),

                        "name":
                            safe_attr(
                                element,
                                "name"
                            ),

                        "accept":
                            safe_attr(
                                element,
                                "accept"
                            ),
                    }
                )

        except Exception:
            continue

    return results


# ======================================================
# RESUME / EXPERIENCE PAGE DETECTION
# ======================================================

def get_visible_page_text(page):

    parts = []

    for frame in page.frames:

        try:

            body = frame.locator("body")

            if body.count() == 0:
                continue

            text = body.inner_text(
                timeout=2000
            )

            if text:
                parts.append(
                    text
                )

        except Exception:
            continue

    return "\n".join(
        parts
    )


def is_resume_experience_page(page):
    """
    Workday can keep a hidden file input mounted on later wizard steps,
    so input[type=file] alone is not enough to identify the resume page.
    Require visible Experience-page text too.
    """

    text = normalize_text(
        get_visible_page_text(
            page
        )
    )

    if not text:
        return False

    has_work_experience = (
        "work experience"
        in text
    )

    has_education = (
        "school or university"
        in text
        or
        "education 1"
        in text
        or
        " education "
        in f" {text} "
    )

    has_resume_context = (
        "resume"
        in text
        or
        "select files"
        in text
        or
        "upload"
        in text
    )

    return (
        has_work_experience
        and
        (
            has_education
            or
            has_resume_context
        )
    )


def wait_for_resume_page_exit(
    page,
    timeout_ms=20000
):
    """
    Require the visible Experience page to disappear twice in a row.
    A small DOM update must not be mistaken for wizard navigation.
    """

    elapsed = 0
    interval = 500
    consecutive_exits = 0

    while elapsed < timeout_ms:

        page.wait_for_timeout(
            interval
        )

        elapsed += interval

        if not is_resume_experience_page(
            page
        ):

            consecutive_exits += 1

            if consecutive_exits >= 2:

                page.wait_for_timeout(
                    500
                )

                return True

        else:

            consecutive_exits = 0

    return False


# ======================================================
# PREVIOUS WORKER
# ======================================================

def fill_previous_worker(
    page,
    profile,
    company
):

    worked_before = (
        has_worked_for_company(
            profile,
            company
        )
    )

    if worked_before is None:

        print(
            "Previous worker answer "
            "requires review."
        )

        return False

    desired_value = (
        "true"
        if worked_before
        else "false"
    )

    desired_answer = (
        "Yes"
        if worked_before
        else "No"
    )

    selector = (
        'input['
        'name="candidateIsPreviousWorker"'
        f'][value="{desired_value}"]'
    )

    for frame in page.frames:

        try:

            radio = frame.locator(
                selector
            )

            if radio.count() == 0:
                continue

            radio = radio.first

            # ------------------------------------------
            # Already selected
            # ------------------------------------------

            try:

                if radio.is_checked():

                    print(
                        f"ALREADY_SET            "
                        f"previous_worker        "
                        f"{desired_answer}"
                    )

                    return True

            except Exception:
                pass

            radio_id = (
                safe_attr(
                    radio,
                    "id"
                )
            )

            # ------------------------------------------
            # Label click
            # ------------------------------------------

            if radio_id:

                try:

                    label = frame.locator(
                        f'label[for="{radio_id}"]'
                    )

                    if label.count() > 0:

                        label.first.click(
                            timeout=3000
                        )

                        frame.page.wait_for_timeout(
                            200
                        )

                except Exception:
                    pass

            try:

                if radio.is_checked():

                    print(
                        f"ANSWERED               "
                        f"previous_worker        "
                        f"{desired_answer}"
                    )

                    return True

            except Exception:
                pass

            # ------------------------------------------
            # Parent
            # ------------------------------------------

            try:

                radio.locator(
                    "xpath=.."
                ).click(
                    timeout=3000
                )

                frame.page.wait_for_timeout(
                    200
                )

            except Exception:
                pass

            try:

                if radio.is_checked():

                    print(
                        f"ANSWERED               "
                        f"previous_worker        "
                        f"{desired_answer}"
                    )

                    return True

            except Exception:
                pass

            # ------------------------------------------
            # Native click
            # ------------------------------------------

            try:

                radio.evaluate(
                    "el => el.click()"
                )

                frame.page.wait_for_timeout(
                    200
                )

            except Exception:
                pass

            try:

                if radio.is_checked():

                    print(
                        f"ANSWERED               "
                        f"previous_worker        "
                        f"{desired_answer}"
                    )

                    return True

            except Exception:
                pass

        except Exception:
            continue

    print(
        "Could not safely answer "
        "previous-worker question."
    )

    return False


# ======================================================
# CHECK IF PROFILE FIELD IS ALREADY CORRECT
# ======================================================

def profile_field_already_correct(
    profile,
    field,
    classification
):

    path = classification.get(
        "profile_path"
    )

    category = classification.get(
        "category"
    )

    if not path:
        return False

    desired = profile.get(
        path
    )

    if desired is None:
        return False

    desired = str(
        desired
    ).strip()

    if not desired:
        return False

    element = field[
        "_element"
    ]

    tag = (
        field.get(
            "tag"
        )
        or ""
    ).lower()

    # --------------------------------------------------
    # Inputs / textareas
    # --------------------------------------------------

    if tag in {
        "input",
        "textarea",
        "select",
    }:

        try:

            current = (
                element
                .input_value()
                .strip()
            )

        except Exception:

            current = ""

        if not current:
            return False

        current_norm = normalize_text(
            current
        )

        desired_norm = normalize_text(
            desired
        )

        if current_norm == desired_norm:
            return True

        # ----------------------------------------------
        # Job source
        # ----------------------------------------------

        if category == "job_source":

            if (
                desired_norm
                in current_norm
                or
                current_norm
                in desired_norm
            ):

                return True

        # ----------------------------------------------
        # Country phone code
        # ----------------------------------------------

        if category == "country_phone_code":

            if (
                "+1" in current
                and
                "+1" in desired
            ):

                return True

    # --------------------------------------------------
    # Workday button listboxes
    # --------------------------------------------------

    if tag == "button":

        try:

            current = (
                element
                .inner_text()
                .strip()
            )

        except Exception:

            current = ""

        if current:

            if (
                normalize_text(desired)
                in
                normalize_text(current)
            ):

                return True

    return False


# ======================================================
# FILL CURRENT SECTION
# ======================================================

def fill_current_page(
    page,
    profile,
    company
):

    fields = collect_fields(
        page
    )

    print(
        f"\nFound "
        f"{len(fields)} controls."
    )

    blockers = []

    handled_count = 0

    previous_worker_handled = False

    for field in fields:

        clean_field = {
            key: value
            for key, value
            in field.items()
            if key not in {
                "_element",
                "_frame",
            }
        }

        classification = (
            classify_field(
                clean_field
            )
        )

        mode = classification.get(
            "mode",
            "IGNORE"
        )

        category = classification.get(
            "category",
            "unknown"
        )

        # ==============================================
        # PREVIOUS WORKER
        # ==============================================

        if category == "previous_worker":

            if previous_worker_handled:
                continue

            success = (
                fill_previous_worker(
                    page,
                    profile,
                    company
                )
            )

            previous_worker_handled = True

            if success:

                handled_count += 1

            else:

                blockers.append(
                    {
                        "category":
                            "previous_worker",

                        "status":
                            "FAILED",
                    }
                )

            continue

        # ==============================================
        # PROFILE FIELD
        # ==============================================

        if mode == "PROFILE":

            # ------------------------------------------
            # Already saved by Workday
            # ------------------------------------------

            if profile_field_already_correct(
                profile,
                field,
                classification
            ):

                print(
                    f"ALREADY_SET            "
                    f"{category:24} "
                    f"{field.get('label')}"
                )

                handled_count += 1

                continue

            try:

                result = (
                    fill_profile_field(
                        profile,
                        field,
                        classification
                    )
                )

                status = result[
                    "status"
                ]

                print(
                    f"{status:22} "
                    f"{category:24} "
                    f"{field.get('label')}"
                )

                if status in {
                    "FILLED",
                    "SELECTED",
                    "EMPTY_OPTIONAL_VALUE",
                }:

                    handled_count += 1

                if (
                    field.get("required")
                    and
                    status
                    not in {
                        "FILLED",
                        "SELECTED",
                    }
                ):

                    blockers.append(
                        {
                            "category":
                                category,

                            "status":
                                status,

                            "label":
                                field.get(
                                    "label"
                                ),
                        }
                    )

            except Exception as exc:

                print(
                    f"ERROR                  "
                    f"{category:24} "
                    f"{exc}"
                )

                blockers.append(
                    {
                        "category":
                            category,

                        "status":
                            "ERROR",

                        "error":
                            str(exc),
                    }
                )

            continue

        # ==============================================
        # MANUAL / SPECIAL
        # ==============================================

        if mode in {
            "MANUAL",
            "SPECIAL",
        }:

            print(
                f"MANUAL_REQUIRED        "
                f"{category:24} "
                f"{field.get('label')}"
            )

            blockers.append(
                {
                    "category":
                        category,

                    "status":
                        "MANUAL_REQUIRED",

                    "label":
                        field.get(
                            "label"
                        ),
                }
            )

            continue

        # ==============================================
        # UNKNOWN REQUIRED FIELD
        # ==============================================

        if (
            field.get("required")
            and
            mode == "IGNORE"
        ):

            print(
                f"REVIEW_REQUIRED        "
                f"{category:24} "
                f"{field.get('label')}"
            )

            blockers.append(
                {
                    "category":
                        category,

                    "status":
                        "REVIEW_REQUIRED",

                    "label":
                        field.get(
                            "label"
                        ),
                }
            )

    return {
        "fields":
            fields,

        "blockers":
            blockers,

        "handled_count":
            handled_count,
    }


# ======================================================
# CONTINUE / SUBMIT
# ======================================================

def find_continue_button(page):

    names = [
        "Save and Continue",
        "Next",
        "Continue",
    ]

    for frame in page.frames:

        for name in names:

            try:

                locator = (
                    frame
                    .get_by_role(
                        "button",
                        name=name,
                        exact=True
                    )
                )

                for index in range(
                    locator.count()
                ):

                    button = locator.nth(
                        index
                    )

                    if (
                        button.is_visible()
                        and
                        button.is_enabled()
                    ):

                        return button

            except Exception:
                continue

    return None


def find_submit_button(page):

    for frame in page.frames:

        try:

            locator = (
                frame
                .get_by_role(
                    "button",
                    name="Submit",
                    exact=True
                )
            )

            for index in range(
                locator.count()
            ):

                button = locator.nth(
                    index
                )

                if (
                    button.is_visible()
                    and
                    button.is_enabled()
                ):

                    return button

        except Exception:
            continue

    return None


# ======================================================
# WAIT FOR REAL SECTION CHANGE
# ======================================================

def wait_for_application_advance(
    page,
    old_fingerprint,
    timeout_ms=20000
):

    elapsed = 0

    interval = 500

    consecutive_changes = 0

    while elapsed < timeout_ms:

        page.wait_for_timeout(
            interval
        )

        elapsed += interval

        current_fingerprint = (
            get_page_fingerprint(
                page
            )
        )

        if (
            current_fingerprint
            != old_fingerprint
        ):

            consecutive_changes += 1

            # Require change twice so a tiny temporary
            # UI update is not mistaken for navigation.
            if consecutive_changes >= 2:

                page.wait_for_timeout(
                    800
                )

                return True

        else:

            consecutive_changes = 0

    return False


# ======================================================
# SAVE DEBUG EVIDENCE
# ======================================================

def save_evidence(
    page,
    step,
    prefix="page"
):

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    screenshot = (
        REPORT_DIR
        / f"{prefix}_{step:02d}.png"
    )

    text_file = (
        REPORT_DIR
        / f"{prefix}_{step:02d}.txt"
    )

    try:

        page.screenshot(
            path=str(
                screenshot
            ),
            full_page=True
        )

    except Exception:
        pass

    try:

        body = (
            page.locator("body")
            .inner_text(
                timeout=3000
            )
        )

        text_file.write_text(
            body,
            encoding="utf-8"
        )

    except Exception:
        pass
# ======================================================
# RESUME UPLOAD
# ======================================================

def upload_resume(
    page,
    resume_path
):

    resume_path = Path(
        resume_path
    )

    if not resume_path.is_absolute():

        resume_path = (
            ROOT
            / resume_path
        )

    resume_path = (
        resume_path
        .resolve()
    )

    # --------------------------------------------------
    # VERIFY FILE EXISTS
    # --------------------------------------------------

    if not resume_path.exists():

        print(
            "\nRESUME FILE NOT FOUND:"
        )

        print(
            resume_path
        )

        return False

    if not resume_path.is_file():

        print(
            "\nRESUME PATH IS NOT A FILE:"
        )

        print(
            resume_path
        )

        return False

    print(
        "\nUploading resume:"
    )

    print(
        resume_path
    )



    # ==================================================
    # ALREADY UPLOADED?
    # ==================================================

    try:

        body_text = (
            page.locator("body")
            .inner_text(
                timeout=3000
            )
        )

        if (
            resume_path.name.lower()
            in body_text.lower()
        ):

            print(
                "\nRESUME ALREADY ATTACHED:"
            )

            print(
                resume_path.name
            )

            return True

    except Exception:
        pass



    # --------------------------------------------------
    # FIND WORKDAY FILE INPUT
    # --------------------------------------------------

    for frame_index, frame in enumerate(
        page.frames
    ):

        try:

            inputs = frame.locator(
                'input[type="file"]'
            )

            count = inputs.count()

        except Exception:

            continue

        if count == 0:
            continue

        print(
            f"Found {count} file input(s) "
            f"in frame {frame_index}."
        )

        for index in range(
            count
        ):

            file_input = inputs.nth(
                index
            )

            try:

                # Works even when Workday hides
                # the real input behind an Upload button.
                file_input.set_input_files(
                    str(
                        resume_path
                    )
                )

                print(
                    "Resume file sent "
                    "to Workday."
                )

                # --------------------------------------
                # WAIT FOR WORKDAY UPLOAD/PARSING
                # --------------------------------------

                page.wait_for_timeout(
                    1500
                )

                filename = (
                    resume_path.name
                )

                previous_body = ""

                try:

                    previous_body = (
                        page.locator(
                            "body"
                        )
                        .inner_text(
                            timeout=3000
                        )
                    )

                except Exception:
                    pass

                for second in range(
                    1,
                    21
                ):

                    page.wait_for_timeout(
                        1000
                    )

                    try:

                        body = (
                            page.locator(
                                "body"
                            )
                            .inner_text(
                                timeout=3000
                            )
                        )

                    except Exception:

                        body = ""

                    body_lower = (
                        body.lower()
                    )

                    # ----------------------------------
                    # EXPLICIT ERROR
                    # ----------------------------------

                    error_phrases = [
                        "upload failed",
                        "file upload failed",
                        "unable to upload",
                        "invalid file",
                    ]

                    if any(
                        phrase
                        in body_lower
                        for phrase
                        in error_phrases
                    ):

                        print(
                            "\nWorkday reported "
                            "an upload problem."
                        )

                        return False

                    # ----------------------------------
                    # FILE NAME APPEARED
                    # ----------------------------------

                    if (
                        filename.lower()
                        in body_lower
                    ):

                        print(
                            "\nRESUME UPLOAD CONFIRMED:"
                        )

                        print(
                            filename
                        )

                        print(
                            "Workday is processing "
                            "the resume."
                        )

                        # Give parsing a little more time.
                        page.wait_for_timeout(
                            4000
                        )

                        return True

                    # ----------------------------------
                    # DOM/BODY CHANGED AFTER UPLOAD
                    # ----------------------------------

                    if (
                        body
                        and
                        previous_body
                        and
                        body != previous_body
                    ):

                        # Do not immediately return.
                        # Workday may still be parsing.
                        previous_body = body

                # --------------------------------------
                # set_input_files succeeded, but
                # Workday gave no textual confirmation.
                #
                # Treat this as REVIEW, not failure.
                # --------------------------------------

                print(
                    "\nResume was sent, but "
                    "Workday did not expose a "
                    "clear upload confirmation."
                )

                print(
                    "Manual inspection required."
                )

                return True

            except Exception as exc:

                print(
                    f"File input {index} failed:"
                )

                print(
                    exc
                )

                continue

    print(
        "\nCould not find a usable "
        "resume file input."
    )

    return False





# ======================================================
# DEBUG: VISIBLE CONTROL INVENTORY
# ======================================================

def print_visible_control_inventory(page):

    print(
        "\nVISIBLE CONTROL INVENTORY"
    )

    print(
        "-" * 72
    )

    seen = set()

    for frame_index, frame in enumerate(
        page.frames
    ):

        try:

            controls = frame.locator(
                'input:not([type="hidden"]), '
                'textarea, select, button, '
                '[role="combobox"], [role="radio"], '
                '[role="checkbox"]'
            )

            for index in range(
                min(controls.count(), 150)
            ):

                control = controls.nth(
                    index
                )

                try:

                    if not control.is_visible():
                        continue

                    tag = control.evaluate(
                        "el => el.tagName.toLowerCase()"
                    )

                    label = (
                        safe_attr(
                            control,
                            "aria-label"
                        )
                        or
                        safe_attr(
                            control,
                            "name"
                        )
                        or
                        safe_attr(
                            control,
                            "placeholder"
                        )
                        or
                        safe_attr(
                            control,
                            "data-automation-id"
                        )
                        or
                        ""
                    )

                    text = ""

                    if tag == "button":

                        try:

                            text = (
                                control.inner_text(
                                    timeout=300
                                )
                                .strip()
                            )

                        except Exception:
                            pass

                    key = (
                        frame_index,
                        tag,
                        normalize_text(label),
                        normalize_text(text),
                    )

                    if key in seen:
                        continue

                    seen.add(
                        key
                    )

                    print(
                        f"[frame={frame_index}] "
                        f"{tag:10} "
                        f"{(label or text)[:120]}"
                    )

                except Exception:
                    continue

        except Exception:
            continue

    print(
        "-" * 72
    )


# ======================================================
# MAIN
# ======================================================

def main():

    if len(sys.argv) < 4:

        print(
            "\nUsage:\n"
            "python browser/workday_runner.py "
            '"JOB_URL" '
            '"COMPANY" '
            '"ROLE"'
        )

        sys.exit(1)

    url = sys.argv[1]
    company = sys.argv[2]
    role = sys.argv[3]

    profile = CandidateProfile(
        "candidate_profile.yaml"
    )

    REPORT_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    with sync_playwright() as playwright:

        context = (
            playwright
            .chromium
            .launch_persistent_context(
                user_data_dir=str(
                    BROWSER_PROFILE.resolve()
                ),

                headless=False,

                viewport={
                    "width":
                        1400,

                    "height":
                        900,
                },
            )
        )

        pages = context.pages

        page = (
            pages[-1]
            if pages
            else context.new_page()
        )

        print(
            "\nOpening:"
        )

        print(
            url
        )

        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=90000
        )

        print(
            "\nJOB:"
        )

        print(
            f"{company} - {role}"
        )

        print(
            "\nNavigate manually into the "
            "saved Workday application."
        )

        print(
            "Complete login, CAPTCHA, MFA, "
            "or cookie consent yourself."
        )

        print(
            "\nStop when the actual application "
            "section is visible."
        )

        input(
            "\nThen press ENTER here..."
        )

        page = get_live_page(
            context
        )

        MAX_SECTIONS = 12

        for step in range(
            1,
            MAX_SECTIONS + 1
        ):

            page = get_live_page(
                context
            )

            print(
                "\n"
                + "=" * 78
            )

            print(
                f"WORKDAY SECTION {step}"
            )

            print(
                "=" * 78
            )

            print(
                "SECTION:",
                get_section_title(
                    page
                )
            )

            print(
                "URL:",
                page.url
            )

            # ==========================================
            # FINAL SUBMIT
            # ==========================================

            submit_button = (
                find_submit_button(
                    page
                )
            )

            if submit_button is not None:

                save_evidence(
                    page,
                    step,
                    "review"
                )

                print(
                    "\n================================="
                )

                print(
                    "FINAL REVIEW PAGE REACHED"
                )

                print(
                    "================================="
                )

                print(
                    "\nThe agent intentionally "
                    "did NOT click Submit."
                )

                print(
                    "Review the complete application "
                    "and submit manually."
                )

                input(
                    "\nPress ENTER to close..."
                )

                context.close()

                return

            # ==========================================
            # RESUME / EXPERIENCE PAGE
            # ==========================================

            if is_resume_experience_page(
                page
            ):

                uploads = (
                    detect_file_upload(
                        page
                    )
                )

                print(
                    "\n================================="
                )

                print(
                    "RESUME / EXPERIENCE PAGE DETECTED"
                )

                print(
                    "================================="
                )

                if uploads:

                    print(
                        json.dumps(
                            uploads,
                            indent=2
                        )
                    )

                resume_name = RESUME_FILE.name
                resume_already_present = False

                try:

                    body_text = (
                        page.locator("body")
                        .inner_text(
                            timeout=3000
                        )
                    )

                    resume_already_present = (
                        resume_name.lower()
                        in body_text.lower()
                    )

                except Exception:
                    pass

                if resume_already_present:

                    print(
                        f"\nALREADY_SET            "
                        f"resume                  "
                        f"{resume_name}"
                    )

                    success = True

                elif uploads:

                    success = (
                        upload_resume(
                            page,
                            RESUME_FILE
                        )
                    )

                else:

                    print(
                        "\nResume upload control was not found "
                        "on the visible Experience page."
                    )

                    success = False

                save_evidence(
                    page,
                    step,
                    "resume_after_upload"
                )

                if not success:

                    print(
                        "\nRESUME UPLOAD / DETECTION FAILED."
                    )

                    input(
                        "\nInspect Chromium. "
                        "Press ENTER to close..."
                    )

                    context.close()

                    return

                print(
                    "\n================================="
                )

                print(
                    "RESUME READY"
                )

                print(
                    "================================="
                )

                print(
                    "\nWaiting briefly for Workday "
                    "resume parsing..."
                )

                page.wait_for_timeout(
                    1800
                )

                experience_result = (
                    fill_experience_and_education(
                        page,
                        profile
                    )
                )

                print(
                    "\n================================="
                )

                print(
                    "EXPERIENCE / EDUCATION RESULT"
                )

                print(
                    "================================="
                )

                print(
                    json.dumps(
                        experience_result,
                        indent=2
                    )
                )

                save_evidence(
                    page,
                    step,
                    "experience_education"
                )

                if not experience_result.get(
                    "ready_to_continue",
                    False
                ):

                    print(
                        "\nSTOPPING BEFORE SAVE AND CONTINUE."
                    )

                    print(
                        "Experience / Education still "
                        "contains required problems."
                    )

                    input(
                        "\nInspect Chromium, "
                        "then press ENTER to close..."
                    )

                    context.close()

                    return

                continue_button = (
                    find_continue_button(
                        page
                    )
                )

                if continue_button is None:

                    print(
                        "\nExperience / Education is ready, "
                        "but Save and Continue was not found."
                    )

                    input(
                        "\nInspect Chromium, "
                        "then press ENTER to close..."
                    )

                    context.close()

                    return

                print(
                    "\nEXPERIENCE / EDUCATION READY."
                )

                print(
                    "Clicking Save and Continue..."
                )

                try:

                    continue_button.scroll_into_view_if_needed()

                    page.wait_for_timeout(
                        200
                    )

                    continue_button.click(
                        timeout=5000
                    )

                except Exception as exc:

                    print(
                        "\nCould not click Save and Continue:"
                    )

                    print(
                        exc
                    )

                    save_evidence(
                        page,
                        step,
                        "experience_continue_click_error"
                    )

                    input(
                        "\nPress ENTER to close..."
                    )

                    context.close()

                    return

                advanced = (
                    wait_for_resume_page_exit(
                        page,
                        timeout_ms=20000
                    )
                )

                if advanced:

                    print(
                        "\nSUCCESS:"
                    )

                    print(
                        "Workday left the Experience page."
                    )

                    continue

                print(
                    "\nEXPERIENCE PAGE DID NOT ADVANCE."
                )

                validation_errors = (
                    get_validation_errors(
                        page
                    )
                )

                if validation_errors:

                    print(
                        "Workday validation:"
                    )

                    for error in validation_errors:

                        print(
                            " -",
                            error
                        )

                else:

                    print(
                        "No required validation error "
                        "was detected."
                    )

                save_evidence(
                    page,
                    step,
                    "experience_stuck"
                )

                input(
                    "\nInspect Chromium, "
                    "then press ENTER to close..."
                )

                context.close()

                return

            body_text = ""

            try:

                body_text = (
                    page.locator("body")
                    .inner_text(
                        timeout=3000
                    )
                )

            except Exception:
                pass

            if (
                    "Are you a relative of a current Public Official?"
                    in body_text
            ):

                conflict_result = (
                    fill_conflict_questions(
                        page,
                        profile
                    )
                )

                print(
                    "\nCONFLICT QUESTION RESULT:"
                )

                print(
                    json.dumps(
                        conflict_result,
                        indent=2
                    )
                )

                if not conflict_result.get(
                        "ready",
                        False
                ):
                    input(
                        "\nReview required. "
                        "Press ENTER to close..."
                    )

                    context.close()

                    return

                continue_button = (
                    find_continue_button(
                        page
                    )
                )

                if continue_button is None:
                    input(
                        "\nSave and Continue not found. "
                        "Press ENTER to close..."
                    )

                    context.close()

                    return

                before_fingerprint = (
                    get_page_fingerprint(
                        page
                    )
                )

                print(
                    "\nConflict questions complete."
                )

                print(
                    "Clicking Save and Continue..."
                )

                continue_button.click(
                    timeout=5000
                )

                advanced = (
                    wait_for_application_advance(
                        page,
                        before_fingerprint,
                        timeout_ms=20000
                    )
                )

                if advanced:
                    print(
                        "\nSUCCESS:"
                    )

                    print(
                        "Moved past Application Questions 1."
                    )

                    continue

                print(
                    "\nApplication Questions 1 "
                    "did not advance."
                )

                input(
                    "\nInspect Chromium. "
                    "Press ENTER to close..."
                )

                context.close()

                return


            # ==========================================
            # FILL CURRENT SECTION
            # ==========================================

            result = (
                fill_current_page(
                    page,
                    profile,
                    company
                )
            )

            # ==========================================
            # APPLICATION QUESTIONS 1 OF 2
            # ==========================================

            body_text = ""

            try:

                body_text = (
                    page.locator("body")
                    .inner_text(
                        timeout=3000
                    )
                )

            except Exception:

                pass

            # ==========================================
            # TRUE ONLY WHEN THE ACTUAL QUESTION
            # IS VISIBLE ON THE CURRENT PAGE.
            #
            # Do NOT use "Application Questions 1 of 2"
            # because Workday shows that text permanently
            # in the progress/navigation sidebar.
            # ==========================================

            is_conflict_page = False

            for frame in page.frames:

                try:

                    questions = frame.get_by_text(
                        "Are you a relative of a current Public Official?",
                        exact=False
                    )

                    for index in range(
                            questions.count()
                    ):

                        question = questions.nth(
                            index
                        )

                        if question.is_visible():
                            is_conflict_page = True
                            break

                    if is_conflict_page:
                        break

                except Exception:
                    continue

            if is_conflict_page:

                print(
                    "\n================================="
                )

                print(
                    "APPLICATION QUESTIONS 1 DETECTED"
                )

                print(
                    "================================="
                )

                conflict_result = (
                    fill_conflict_questions(
                        page,
                        profile
                    )
                )

                print(
                    "\nCONFLICT QUESTION RESULT:"
                )

                print(
                    json.dumps(
                        conflict_result,
                        indent=2
                    )
                )

                if not conflict_result.get(
                        "ready",
                        False
                ):
                    print(
                        "\nApplication Questions 1 "
                        "requires profile review."
                    )

                    input(
                        "\nPress ENTER to close..."
                    )

                    context.close()

                    return

                continue_button = (
                    find_continue_button(
                        page
                    )
                )

                if continue_button is None:
                    print(
                        "\nSave and Continue "
                        "was not found."
                    )

                    input(
                        "\nPress ENTER to close..."
                    )

                    context.close()

                    return

                before_fingerprint = (
                    get_page_fingerprint(
                        page
                    )
                )

                print(
                    "\nApplication Questions 1 complete."
                )

                print(
                    "Clicking Save and Continue..."
                )

                continue_button.click(
                    timeout=5000
                )

                advanced = (
                    wait_for_application_advance(
                        page,
                        before_fingerprint,
                        timeout_ms=20000
                    )
                )

                if advanced:
                    print(
                        "\nSUCCESS:"
                    )

                    print(
                        "Moved past Application Questions 1."
                    )

                    continue

                print(
                    "\nApplication Questions 1 "
                    "did not advance."
                )

                errors = (
                    get_validation_errors(
                        page
                    )
                )

                for error in errors:
                    print(
                        " -",
                        error
                    )

                input(
                    "\nInspect Chromium. "
                    "Press ENTER to close..."
                )

                context.close()

                return



            blockers = result[
                "blockers"
            ]

            handled_count = result[
                "handled_count"
            ]

            save_evidence(
                page,
                step
            )

            if blockers:

                print(
                    "\nSTOPPING."
                )

                print(
                    "Fields requiring review:"
                )

                for blocker in blockers:

                    print(
                        " -",
                        blocker
                    )

                input(
                    "\nInspect Chromium. "
                    "Press ENTER to close..."
                )

                context.close()

                return

            # ==========================================
            # UNKNOWN PAGE
            # ==========================================

            if handled_count == 0:

                print(
                    "\n================================="
                )

                print(
                    "UNHANDLED WORKDAY SECTION"
                )

                print(
                    "================================="
                )

                print(
                    "\nThe runner did not recognize "
                    "any safe fields on this page."
                )

                print(
                    "It will NOT blindly click Next."
                )

                print(
                    "\nSECTION:"
                )

                print(
                    get_section_title(
                        page
                    )
                )

                print(
                    "\nDebug files saved in:"
                )

                print(
                    REPORT_DIR
                )

                print_visible_control_inventory(
                    page
                )

                input(
                    "\nPress ENTER to close..."
                )

                context.close()

                return

            # ==========================================
            # VALIDATION BEFORE CONTINUE
            # ==========================================

            errors_before = (
                get_validation_errors(
                    page
                )
            )

            if errors_before:

                print(
                    "\nValidation problems found "
                    "before navigation:"
                )

                for error in errors_before:

                    print(
                        " -",
                        error
                    )

                input(
                    "\nInspect Chromium. "
                    "Press ENTER to close..."
                )

                context.close()

                return

            # ==========================================
            # CONTINUE
            # ==========================================

            continue_button = (
                find_continue_button(
                    page
                )
            )

            if continue_button is None:

                print(
                    "\nNo Save and Continue / "
                    "Next button found."
                )

                input(
                    "\nInspect Chromium. "
                    "Press ENTER to close..."
                )

                context.close()

                return

            # IMPORTANT:
            # Fingerprint after all fields are filled.
            before_fingerprint = (
                get_page_fingerprint(
                    page
                )
            )

            print(
                "\nAll known required fields "
                "were handled."
            )

            print(
                "Clicking Save and Continue..."
            )

            try:

                continue_button.scroll_into_view_if_needed()

                page.wait_for_timeout(
                    200
                )

                continue_button.click(
                    timeout=5000
                )

            except Exception as exc:

                print(
                    "\nCould not click "
                    "Save and Continue:"
                )

                print(
                    exc
                )

                save_evidence(
                    page,
                    step,
                    "click_error"
                )

                input(
                    "\nPress ENTER to close..."
                )

                context.close()

                return

            # ==========================================
            # WAIT UP TO 20 SEC
            # ==========================================

            advanced = (
                wait_for_application_advance(
                    page,
                    before_fingerprint,
                    timeout_ms=20000
                )
            )

            if advanced:

                print(
                    "\nSUCCESS:"
                )

                print(
                    "Workday application "
                    "section changed."
                )

                continue

            # ==========================================
            # DID NOT ADVANCE
            # ==========================================

            print(
                "\n================================="
            )

            print(
                "PAGE DID NOT ADVANCE"
            )

            print(
                "================================="
            )

            errors = (
                get_validation_errors(
                    page
                )
            )

            if errors:

                print(
                    "\nWorkday validation:"
                )

                for error in errors:

                    print(
                        " -",
                        error
                    )

            else:

                print(
                    "\nNo explicit validation "
                    "message was detected."
                )

            save_evidence(
                page,
                step,
                "stuck"
            )

            print(
                "\nSaved:"
            )

            print(
                REPORT_DIR
            )

            print(
                "\nDo not rerun yet."
            )

            print(
                "Inspect the browser and send me "
                "what is visible after the click."
            )

            input(
                "\nPress ENTER to close..."
            )

            context.close()

            return

        print(
            "\nMaximum section limit reached."
        )

        context.close()


if __name__ == "__main__":
    main()