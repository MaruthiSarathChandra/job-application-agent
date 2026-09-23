import json
import sys
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


REPORT_FILE = Path("data/fill_report.json")
SCREENSHOT_FILE = Path("data/after_fill.png")


# ======================================================
# PAGE HELPERS
# ======================================================

def get_live_page(context):
    live_pages = [
        page
        for page in context.pages
        if not page.is_closed()
    ]

    if not live_pages:
        raise RuntimeError(
            "No active browser page exists."
        )

    return live_pages[-1]


def safe_attribute(element, attribute):
    try:
        return element.get_attribute(attribute)
    except Exception:
        return None


def normalize_text(value):
    if value is None:
        return ""

    return " ".join(
        str(value)
        .strip()
        .lower()
        .split()
    )


def safe_label(frame, element):

    # --------------------------------------------------
    # aria-label
    # --------------------------------------------------

    aria = safe_attribute(
        element,
        "aria-label"
    )

    if aria:
        return aria.strip()

    # --------------------------------------------------
    # aria-labelledby
    # --------------------------------------------------

    labelledby = safe_attribute(
        element,
        "aria-labelledby"
    )

    if labelledby:

        pieces = []

        for item_id in labelledby.split():

            try:

                target = frame.locator(
                    f"#{item_id}"
                )

                if target.count() > 0:

                    text = (
                        target
                        .first
                        .inner_text(
                            timeout=1000
                        )
                        .strip()
                    )

                    if text:
                        pieces.append(text)

            except Exception:
                pass

        if pieces:
            return " ".join(pieces)

    # --------------------------------------------------
    # normal label
    # --------------------------------------------------

    element_id = safe_attribute(
        element,
        "id"
    )

    if element_id:

        try:

            label = frame.locator(
                f'label[for="{element_id}"]'
            )

            if label.count() > 0:

                text = (
                    label
                    .first
                    .inner_text(
                        timeout=1000
                    )
                    .strip()
                )

                if text:
                    return text

        except Exception:
            pass

    # --------------------------------------------------
    # placeholder
    # --------------------------------------------------

    placeholder = safe_attribute(
        element,
        "placeholder"
    )

    if placeholder:
        return placeholder.strip()

    # --------------------------------------------------
    # nearest readable parent
    # --------------------------------------------------

    try:

        nearby = element.evaluate(
            """
            el => {
                let node = el;

                for (
                    let i = 0;
                    i < 5 && node;
                    i++
                ) {
                    const text =
                        (node.innerText || "").trim();

                    if (
                        text.length > 0 &&
                        text.length < 350
                    ) {
                        return text;
                    }

                    node = node.parentElement;
                }

                return null;
            }
            """
        )

        if nearby:

            lines = [
                line.strip()
                for line in nearby.splitlines()
                if line.strip()
            ]

            if lines:
                return lines[0]

    except Exception:
        pass

    # --------------------------------------------------
    # name fallback
    # --------------------------------------------------

    name = safe_attribute(
        element,
        "name"
    )

    if name:
        return name.strip()

    return "UNKNOWN_FIELD"


# ======================================================
# FIELD COLLECTION
# ======================================================

def collect_fields(page):

    selectors = [
        'input:not([type="hidden"])',
        "textarea",
        "select",
        '[role="textbox"]',
        '[role="combobox"]',
        'button[aria-haspopup="listbox"]',
    ]

    results = []
    seen = set()

    for frame_index, frame in enumerate(page.frames):

        for selector in selectors:

            try:

                controls = frame.locator(
                    selector
                )

                count = controls.count()

            except Exception:
                continue

            for index in range(count):

                element = controls.nth(index)

                try:

                    if not element.is_visible():
                        continue

                    tag = element.evaluate(
                        "el => el.tagName.toLowerCase()"
                    )

                    element_id = safe_attribute(
                        element,
                        "id"
                    )

                    name = safe_attribute(
                        element,
                        "name"
                    )

                    role = safe_attribute(
                        element,
                        "role"
                    )

                    field_type = (
                        safe_attribute(
                            element,
                            "type"
                        )
                        or role
                        or tag
                    )

                    aria_haspopup = (
                        safe_attribute(
                            element,
                            "aria-haspopup"
                        )
                    )

                    label = safe_label(
                        frame,
                        element
                    )

                    identity = (
                        frame_index,
                        element_id,
                        name,
                        role,
                        field_type,
                        label,
                    )

                    if identity in seen:
                        continue

                    seen.add(identity)

                    field = {
                        "frame_index":
                            frame_index,

                        "element_index":
                            index,

                        "selector_source":
                            selector,

                        "tag":
                            tag,

                        "type":
                            field_type,

                        "role":
                            role,

                        "aria_haspopup":
                            aria_haspopup,

                        "aria_expanded":
                            safe_attribute(
                                element,
                                "aria-expanded"
                            ),

                        "data_automation_id":
                            safe_attribute(
                                element,
                                "data-automation-id"
                            ),

                        "id":
                            element_id,

                        "name":
                            name,

                        "label":
                            label,

                        "required":
                            (
                                safe_attribute(
                                    element,
                                    "required"
                                )
                                is not None

                                or

                                safe_attribute(
                                    element,
                                    "aria-required"
                                )
                                == "true"

                                or

                                "required"
                                in label.lower()
                            ),

                        "_element":
                            element,

                        "_frame":
                            frame,
                    }

                    results.append(field)

                except Exception:
                    continue

    return results


# ======================================================
# GENERIC WORKDAY PROMPT HELPERS
# ======================================================

def workday_prompt_is_open(frame):
    """
    Returns True when a Workday prompt/menu currently
    has visible selectable items.
    """

    selectors = [
        '[data-automation-id="promptOption"]',
        '[data-automation-id="menuItem"]',
        '[role="option"]',
    ]

    for selector in selectors:

        try:

            items = frame.locator(
                selector
            )

            for index in range(
                items.count()
            ):

                try:

                    if items.nth(
                        index
                    ).is_visible():

                        return True

                except Exception:
                    continue

        except Exception:
            continue

    return False


def close_workday_prompt(page):
    """
    Close an existing Workday dropdown/prompt.

    Workday can occasionally keep nested prompt levels
    open, so Escape is sent twice.
    """

    try:

        page.keyboard.press(
            "Escape"
        )

        page.wait_for_timeout(
            150
        )

        page.keyboard.press(
            "Escape"
        )

        page.wait_for_timeout(
            200
        )

    except Exception:
        pass




def get_visible_prompt_items(frame):

    selectors = [
        '[data-automation-id="promptOption"]',
        '[role="option"]',
        '[data-automation-id="menuItem"]',
    ]

    results = []
    seen = set()

    for selector in selectors:

        try:

            items = frame.locator(
                selector
            )

            for index in range(
                items.count()
            ):

                item = items.nth(index)

                try:

                    if not item.is_visible():
                        continue

                    text = ""

                    try:

                        text = (
                            item
                            .inner_text()
                            .strip()
                        )

                    except Exception:
                        pass

                    if not text:

                        text = (
                            item.get_attribute(
                                "data-automation-label"
                            )
                            or ""
                        ).strip()

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

                    results.append(
                        (
                            text,
                            item
                        )
                    )

                except Exception:
                    continue

        except Exception:
            continue

    return results


def find_visible_prompt_item(
    frame,
    desired_text
):

    desired = normalize_text(
        desired_text
    )

    candidates = (
        get_visible_prompt_items(
            frame
        )
    )

    # exact
    for text, item in candidates:

        if normalize_text(text) == desired:
            return item

    return None


def click_prompt_item(
    page,
    item
):

    try:

        item.click(
            timeout=4000
        )

        page.wait_for_timeout(
            250
        )

        return True

    except Exception:

        try:

            item.click(
                force=True,
                timeout=4000
            )

            page.wait_for_timeout(
                250
            )

            return True

        except Exception:

            return False


# ======================================================
# WORKDAY JOB SOURCE
# ======================================================

def search_current_source_level(
    frame,
    desired_source
):

    page = frame.page

    search_selectors = [
        'input[placeholder="Search"]',
        'input[aria-label="Search"]',
        'input[aria-label*="Search"]',
    ]

    for selector in search_selectors:

        try:

            searches = frame.locator(
                selector
            )

            for index in range(
                searches.count()
            ):

                search = searches.nth(
                    index
                )

                if not search.is_visible():
                    continue

                try:

                    search.fill(
                        desired_source
                    )

                    page.wait_for_timeout(
                        450
                    )

                except Exception:
                    continue

                match = (
                    find_visible_prompt_item(
                        frame,
                        desired_source
                    )
                )

                if match is not None:

                    if click_prompt_item(
                        page,
                        match
                    ):

                        return True

        except Exception:
            continue

    return False


def open_job_source_selector(
    frame,
    element
):
    """
    Open How Did You Hear About Us?.

    Important:
    If Workday already has the popup open, do NOT
    click the input underneath it.
    """

    page = frame.page

    # ==================================================
    # ALREADY OPEN
    # ==================================================

    if workday_prompt_is_open(
        frame
    ):

        print(
            "Job-source prompt is already open."
        )

        return True

    # ==================================================
    # NORMAL CLICK
    # ==================================================

    try:

        element.click(
            timeout=3500
        )

        page.wait_for_timeout(
            350
        )

        if workday_prompt_is_open(
            frame
        ):

            return True

    except Exception as exc:

        # Workday sometimes reports interception because
        # the prompt opened between our check and click.
        if workday_prompt_is_open(
            frame
        ):

            print(
                "Job-source prompt opened during click."
            )

            return True

        print(
            "Could not open job-source selector:",
            exc
        )

        return False

    # ==================================================
    # FALLBACK: FOCUS + KEYBOARD
    # ==================================================

    try:

        element.focus()

        element.press(
            "ArrowDown"
        )

        page.wait_for_timeout(
            300
        )

        if workday_prompt_is_open(
            frame
        ):

            return True

    except Exception:
        pass

    print(
        "Job-source selector did not open."
    )

    return False



def select_workday_job_source(
    frame,
    element,
    desired_source
):

    page = frame.page

    desired_source = str(
        desired_source
    ).strip()

    print(
        f"\nLooking for job source: "
        f"{desired_source}"
    )

    # ==================================================
    # OPEN ROOT
    # ==================================================

    if not open_job_source_selector(
        frame,
        element
    ):
        return False

    # ==================================================
    # MAYBE SOURCE IS DIRECTLY AVAILABLE
    # ==================================================

    direct = (
        find_visible_prompt_item(
            frame,
            desired_source
        )
    )

    if direct is not None:

        if click_prompt_item(
            page,
            direct
        ):

            print(
                f"Matched job source directly: "
                f"{desired_source}"
            )

            return True

    # ==================================================
    # WORKDAY TOP-LEVEL CATEGORIES
    # ==================================================

    source_categories = [
        "Online Source",
        "Social Media",
        "Campus / University",
        "Agency / Executive Search Firm",
        "Employees",
        "Other",
        "Professional Association/Organization",
        "Online Source - Asia Job Boards",
    ]

    print(
        "Trying Workday source categories..."
    )

    for category in source_categories:

        # ----------------------------------------------
        # REOPEN ROOT EVERY ITERATION
        # ----------------------------------------------

        close_workday_prompt(
            page
        )

        if not open_job_source_selector(
            page,
            element
        ):
            continue

        category_item = (
            find_visible_prompt_item(
                frame,
                category
            )
        )

        if category_item is None:
            continue

        print(
            f"Checking category: "
            f"{category}"
        )

        if not click_prompt_item(
            page,
            category_item
        ):
            continue

        page.wait_for_timeout(
            300
        )

        # ----------------------------------------------
        # LOOK FOR SOURCE
        # ----------------------------------------------

        match = (
            find_visible_prompt_item(
                frame,
                desired_source
            )
        )

        if match is not None:

            if click_prompt_item(
                page,
                match
            ):

                print(
                    f"Matched job source: "
                    f"{category} "
                    f"-> {desired_source}"
                )

                return True

        # ----------------------------------------------
        # SEARCH INSIDE CATEGORY
        # ----------------------------------------------

        if search_current_source_level(
            frame,
            desired_source
        ):

            print(
                f"Matched job source: "
                f"{category} "
                f"-> {desired_source}"
            )

            return True

    # ==================================================
    # NOTHING MATCHED
    # ==================================================

    close_workday_prompt(
        page
    )

    print(
        f"Could not safely locate "
        f"job source '{desired_source}'."
    )

    return False


# ======================================================
# WORKDAY BUTTON LISTBOX
# Country / State / Phone Type
# ======================================================

def select_workday_listbox(
    frame,
    element,
    desired_value
):

    page = frame.page

    desired_value = str(
        desired_value
    ).strip()

    desired = normalize_text(
        desired_value
    )

    # --------------------------------------------------
    # ALREADY SELECTED?
    # --------------------------------------------------

    try:

        current = normalize_text(
            element.inner_text()
        )

        if (
            desired
            and
            desired in current
        ):
            return True

    except Exception:
        pass

    close_workday_prompt(
        page
    )

    # --------------------------------------------------
    # OPEN
    # --------------------------------------------------

    try:

        element.click(
            timeout=4000
        )

    except Exception as exc:

        print(
            "\nCould not open Workday listbox:",
            exc
        )

        return False

    page.wait_for_timeout(
        350
    )

    candidates = (
        get_visible_prompt_items(
            frame
        )
    )

    print(
        f"\nLooking for Workday option: "
        f"{desired_value}"
    )

    print(
        "Visible options:",
        len(candidates)
    )

    chosen = None

    # --------------------------------------------------
    # EXACT
    # --------------------------------------------------

    for text, option in candidates:

        if normalize_text(text) == desired:

            chosen = option

            break

    # --------------------------------------------------
    # SAFE PARTIAL
    # --------------------------------------------------

    if chosen is None:

        for text, option in candidates:

            normalized = normalize_text(
                text
            )

            if (
                desired in normalized
                or
                normalized == desired
            ):

                chosen = option

                break

    if chosen is None:

        close_workday_prompt(
            page
        )

        return False

    success = click_prompt_item(
        page,
        chosen
    )

    if not success:

        close_workday_prompt(
            page
        )

    return success


# ======================================================
# INPUT-BASED WORKDAY DROPDOWN
# Source / Phone Code
# ======================================================

def select_workday_input_dropdown(
    frame,
    element,
    desired_value,
    category=None
):

    desired_value = str(
        desired_value
    ).strip()

    # ==================================================
    # JOB SOURCE
    # ==================================================

    if category == "job_source":

        return select_workday_job_source(
            frame,
            element,
            desired_value
        )

    page = frame.page

    desired = normalize_text(
        desired_value
    )

    close_workday_prompt(
        page
    )

    # ==================================================
    # OPEN CONTROL
    # ==================================================

    try:

        element.click(
            timeout=3000
        )

    except Exception:
        pass

    # ==================================================
    # TYPE FILTER TEXT
    # ==================================================

    try:

        element.fill(
            desired_value
        )

    except Exception:
        pass

    page.wait_for_timeout(
        500
    )

    candidates = (
        get_visible_prompt_items(
            frame
        )
    )

    print(
        f"\nLooking for input dropdown option: "
        f"{desired_value}"
    )

    print(
        f"Visible options: "
        f"{len(candidates)}"
    )

    chosen = None

    # ==================================================
    # COUNTRY PHONE CODE
    # ==================================================

    if category == "country_phone_code":

        for text, option in candidates:

            lower = normalize_text(
                text
            )

            if (
                "united states"
                in lower
                and
                "+1"
                in lower
            ):

                chosen = option

                print(
                    "Matched phone code option: "
                    f"{text}"
                )

                break

    # ==================================================
    # EXACT
    # ==================================================

    if chosen is None:

        for text, option in candidates:

            if normalize_text(text) == desired:

                chosen = option

                break

    # ==================================================
    # SAFE CONTAINS
    # ==================================================

    if chosen is None:

        for text, option in candidates:

            normalized = normalize_text(
                text
            )

            if desired in normalized:

                chosen = option

                break

    # ==================================================
    # DO NOT GUESS
    # ==================================================

    if chosen is None:

        print(
            f"Could not safely find option: "
            f"{desired_value}"
        )

        close_workday_prompt(
            page
        )

        return False

    success = click_prompt_item(
        page,
        chosen
    )

    if not success:

        close_workday_prompt(
            page
        )

        return False

    return True


# ======================================================
# PROFILE FILLING
# ======================================================

def fill_profile_field(
    profile,
    field,
    classification
):

    path = classification[
        "profile_path"
    ]

    category = classification[
        "category"
    ]

    value = profile.get(
        path
    )

    if value is None:

        return {
            "status":
                "MISSING_PROFILE_VALUE",

            "value":
                None,
        }

    value = str(
        value
    )

    # --------------------------------------------------
    # SAFETY:
    # JOB SOURCE MUST NEVER BE URL
    # --------------------------------------------------

    if (
        category == "job_source"
        and
        (
            value.startswith(
                "http://"
            )
            or
            value.startswith(
                "https://"
            )
        )
    ):

        return {
            "status":
                "INVALID_PROFILE_VALUE",

            "value":
                value,
        }

    # --------------------------------------------------
    # EMPTY OPTIONAL
    # --------------------------------------------------

    if not value.strip():

        return {
            "status":
                "EMPTY_OPTIONAL_VALUE",

            "value":
                "",
        }

    element = field[
        "_element"
    ]

    frame = field[
        "_frame"
    ]

    field_type = (
        field.get(
            "type"
        )
        or ""
    ).lower()

    tag = (
        field.get(
            "tag"
        )
        or ""
    ).lower()

    role = (
        field.get(
            "role"
        )
        or ""
    ).lower()

    aria_haspopup = (
        field.get(
            "aria_haspopup"
        )
        or ""
    ).lower()

    # ==================================================
    # WORKDAY BUTTON LISTBOX
    #
    # Country
    # State
    # Phone Device Type
    # ==================================================

    if (
        tag == "button"
        and
        aria_haspopup == "listbox"
    ):

        success = (
            select_workday_listbox(
                frame,
                element,
                value
            )
        )

        return {
            "status":
                (
                    "SELECTED"
                    if success
                    else
                    "SELECT_FAILED"
                ),

            "value":
                value,
        }

    # ==================================================
    # INPUT-BASED WORKDAY DROPDOWNS
    #
    # Job Source
    # Country Phone Code
    # ==================================================

    if category in {
        "job_source",
        "country_phone_code",
    }:

        success = (
            select_workday_input_dropdown(
                frame,
                element,
                value,
                category
            )
        )

        return {
            "status":
                (
                    "SELECTED"
                    if success
                    else
                    "SELECT_FAILED"
                ),

            "value":
                value,
        }

    # ==================================================
    # GENERIC COMBOBOX
    # ==================================================

    if role == "combobox":

        success = (
            select_workday_input_dropdown(
                frame,
                element,
                value,
                category
            )
        )

        return {
            "status":
                (
                    "SELECTED"
                    if success
                    else
                    "SELECT_FAILED"
                ),

            "value":
                value,
        }

    # ==================================================
    # ORDINARY TEXT INPUT
    # ==================================================

    if tag in {
        "input",
        "textarea",
    }:

        if field_type not in {
            "radio",
            "checkbox",
            "file",
            "submit",
            "button",
        }:

            element.fill(
                value
            )

            return {
                "status":
                    "FILLED",

                "value":
                    value,
            }

    return {
        "status":
            "UNSUPPORTED_CONTROL",

        "value":
            None,
    }


# ======================================================
# MAIN TEST MODE
# ======================================================

def main():

    if len(sys.argv) < 2:

        print(
            'Usage:\n'
            'python browser/form_filler.py '
            '"https://company.com/job"'
        )

        sys.exit(1)

    url = sys.argv[1]

    profile = CandidateProfile(
        "candidate_profile.yaml"
    )

    REPORT_FILE.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with sync_playwright() as playwright:

        browser = (
            playwright
            .chromium
            .launch(
                headless=False
            )
        )

        context = (
            browser
            .new_context(
                viewport={
                    "width": 1400,
                    "height": 900,
                }
            )
        )

        page = (
            context
            .new_page()
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
            timeout=90000,
        )

        print(
            "\nUse Chromium manually."
        )

        print(
            "\n1. Click Apply"
            "\n2. Sign in if necessary"
            "\n3. Navigate to the application form"
            "\n4. Stop when fields are visible"
            "\n5. DO NOT press Submit"
        )

        input(
            "\nWhen the application form is "
            "visible, press ENTER here..."
        )

        page = get_live_page(
            context
        )

        print(
            "\nActive page:"
        )

        print(
            page.url
        )

        fields = collect_fields(
            page
        )

        print(
            f"\nFound "
            f"{len(fields)} "
            f"visible controls."
        )

        report = []

        print(
            "\n"
            + "=" * 75
        )

        print(
            "SAFE AUTOFILL"
        )

        print(
            "=" * 75
        )

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

            mode = classification[
                "mode"
            ]

            category = classification[
                "category"
            ]

            entry = {
                **clean_field,

                "classification":
                    classification,
            }

            # ==========================================
            # PROFILE
            # ==========================================

            if mode == "PROFILE":

                try:

                    result = (
                        fill_profile_field(
                            profile,
                            field,
                            classification
                        )
                    )

                    entry.update(
                        result
                    )

                    print(
                        f'{result["status"]:22} '
                        f'{category:24} '
                        f'{field["label"]}'
                    )

                except Exception as exc:

                    entry[
                        "status"
                    ] = "FILL_ERROR"

                    entry[
                        "error"
                    ] = str(exc)

                    print(
                        f'ERROR                  '
                        f'{category:24} '
                        f'{field["label"]}'
                    )

            # ==========================================
            # MANUAL / SPECIAL
            # ==========================================

            elif mode in {
                "MANUAL",
                "SPECIAL",
            }:

                entry[
                    "status"
                ] = "MANUAL_REQUIRED"

                print(
                    f'MANUAL_REQUIRED        '
                    f'{category:24} '
                    f'{field["label"]}'
                )

            # ==========================================
            # IGNORE
            # ==========================================

            else:

                entry[
                    "status"
                ] = "IGNORED"

                print(
                    f'IGNORED                '
                    f'{category:24} '
                    f'{field["label"]}'
                )

            report.append(
                entry
            )

        # ==============================================
        # REPORT
        # ==============================================

        with REPORT_FILE.open(
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                {
                    "url":
                        page.url,

                    "title":
                        page.title(),

                    "fields":
                        report,
                },
                file,
                indent=2,
                ensure_ascii=False
            )

        # ==============================================
        # SCREENSHOT
        # ==============================================

        try:

            page.screenshot(
                path=str(
                    SCREENSHOT_FILE
                ),
                full_page=True
            )

        except Exception as exc:

            print(
                "\nScreenshot failed:",
                exc
            )

        print(
            "\nSaved report:"
        )

        print(
            REPORT_FILE
        )

        print(
            "\nSaved screenshot:"
        )

        print(
            SCREENSHOT_FILE
        )

        print(
            "\nIMPORTANT:"
            "\nThe agent has NOT clicked "
            "Next or Submit."
        )

        input(
            "\nInspect Chromium carefully."
            "\nPress ENTER here when finished..."
        )

        browser.close()


if __name__ == "__main__":
    main()