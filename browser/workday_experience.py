# browser/workday_experience.py

VERSION = "5.1-final-fast-state-street"


# ======================================================
# BASIC HELPERS
# ======================================================

def normalize(value):

    if value is None:
        return ""

    return " ".join(
        str(value)
        .strip()
        .lower()
        .split()
    )


def profile_text(value):

    if value is None:
        return ""

    if isinstance(value, list):

        return " ".join(
            str(item).strip()
            for item in value
            if str(item).strip()
        )

    return str(value).strip()


def visible(element):

    try:
        return element.is_visible()
    except Exception:
        return False


# ======================================================
# PROFILE DATA
# ======================================================

def work_record(profile):

    records = profile.get(
        "work_experience",
        []
    )

    if (
        isinstance(records, list)
        and records
    ):
        return records[0]

    return None


def education_record(profile):

    records = profile.get(
        "education_history",
        []
    )

    if (
        isinstance(records, list)
        and records
    ):
        return records[0]

    school = profile.get(
        "education.university"
    )

    highest = profile.get(
        "education.highest_degree"
    )

    graduation = profile.get(
        "education.graduation_date"
    )

    if not school:
        return None

    degree = ""

    field = ""

    highest_normalized = normalize(
        highest
    )

    if "ms" in highest_normalized:
        degree = "Master of Science"

    if "computer science" in highest_normalized:
        field = "Computer Science"

    end_year = ""

    if graduation:

        parts = str(
            graduation
        ).split("-")

        if parts:
            end_year = parts[0]

    return {
        "school":
            school,

        "degree":
            degree,

        "field_of_study":
            field,

        "start_year":
            "2024",

        "end_year":
            end_year,
    }


# ======================================================
# FIND EXACT HEADING
# ======================================================

def find_heading(
    page,
    text
):

    for frame in page.frames:

        try:

            headings = frame.locator(
                "h1, h2, h3, h4, legend"
            )

            for index in range(
                headings.count()
            ):

                heading = headings.nth(
                    index
                )

                if not visible(
                    heading
                ):
                    continue

                try:

                    current = (
                        heading
                        .inner_text(
                            timeout=300
                        )
                        .strip()
                    )

                except Exception:
                    continue

                if (
                    normalize(current)
                    ==
                    normalize(text)
                ):

                    return (
                        frame,
                        heading
                    )

        except Exception:
            continue

    return (
        None,
        None
    )


# ======================================================
# CLICK NEAREST ADD BUTTON BELOW HEADING
#
# This avoids guessing which one of Workday's many
# add-button elements belongs to Education.
# ======================================================

def click_nearest_add(
    page,
    section_name
):

    frame, heading = (
        find_heading(
            page,
            section_name
        )
    )

    if (
        frame is None
        or
        heading is None
    ):

        print(
            f"HEADING_NOT_FOUND      "
            f"{section_name}"
        )

        return False

    try:

        heading_box = (
            heading.bounding_box()
        )

    except Exception:

        heading_box = None

    if not heading_box:

        return False

    heading_y = heading_box[
        "y"
    ]

    candidates = []

    selectors = [
        'button[data-automation-id="add-button"]',
        'button:has-text("Add Another")',
        'button:has-text("Add")',
    ]

    for selector in selectors:

        try:

            buttons = frame.locator(
                selector
            )

            for index in range(
                buttons.count()
            ):

                button = buttons.nth(
                    index
                )

                if not visible(
                    button
                ):
                    continue

                box = (
                    button.bounding_box()
                )

                if not box:
                    continue

                # Button must be below the section title.
                if box["y"] <= heading_y:
                    continue

                distance = (
                    box["y"]
                    - heading_y
                )

                candidates.append(
                    (
                        distance,
                        button
                    )
                )

        except Exception:
            continue

    if not candidates:

        print(
            f"ADD_NOT_FOUND          "
            f"{section_name}"
        )

        return False

    candidates.sort(
        key=lambda item:
            item[0]
    )

    _, button = candidates[0]

    try:

        button.click(
            timeout=3000
        )

        page.wait_for_timeout(
            700
        )

        print(
            f"CLICKED_ADD            "
            f"{section_name}"
        )

        return True

    except Exception as exc:

        print(
            f"ADD_CLICK_FAILED       "
            f"{section_name}: "
            f"{exc}"
        )

        return False


# ======================================================
# INPUT HELPERS
# ======================================================

def first_visible(
    frame,
    selector
):

    try:

        locator = frame.locator(
            selector
        )

        for index in range(
            locator.count()
        ):

            element = locator.nth(
                index
            )

            if visible(
                element
            ):
                return element

    except Exception:
        pass

    return None


def fill_text(
    element,
    value,
    name,
    overwrite_bad_date=False
):

    value = profile_text(
        value
    )

    if not value:

        return {
            "field":
                name,

            "status":
                "PROFILE_EMPTY",
        }

    if element is None:

        print(
            f"NOT_FOUND              "
            f"{name:24}"
        )

        return {
            "field":
                name,

            "status":
                "NOT_FOUND",
        }

    current = ""

    try:

        current = (
            element
            .input_value()
            .strip()
        )

    except Exception:
        pass

    # Previous buggy runner may have put 02/2026
    # into a Month control. Allow correcting that.
    if (
        overwrite_bad_date
        and
        current
        and
        "/" in current
    ):

        current = ""

    if current:

        if (
            normalize(current)
            ==
            normalize(value)
        ):

            print(
                f"ALREADY_SET            "
                f"{name:24} "
                f"{current}"
            )

            return {
                "field":
                    name,

                "status":
                    "ALREADY_SET",

                "value":
                    current,
            }

        print(
            f"KEEP_EXISTING          "
            f"{name:24} "
            f"{current}"
        )

        return {
            "field":
                name,

            "status":
                "ALREADY_SET",

            "value":
                current,
        }

    try:

        element.fill(
            value
        )

        print(
            f"FILLED                 "
            f"{name:24} "
            f"{value}"
        )

        return {
            "field":
                name,

            "status":
                "FILLED",

            "value":
                value,
        }

    except Exception as exc:

        print(
            f"FILL_FAILED            "
            f"{name:24} "
            f"{exc}"
        )

        return {
            "field":
                name,

            "status":
                "FILL_FAILED",
        }


# ======================================================
# WORK EXPERIENCE
# ======================================================

MONTHS = {
    "january": "01",
    "february": "02",
    "march": "03",
    "april": "04",
    "may": "05",
    "june": "06",
    "july": "07",
    "august": "08",
    "september": "09",
    "october": "10",
    "november": "11",
    "december": "12",
}


def month_value(value):

    text = normalize(
        value
    )

    if text in MONTHS:
        return MONTHS[text]

    if text.isdigit():

        number = int(text)

        if 1 <= number <= 12:
            return f"{number:02d}"

    return ""


def fill_work_experience(
    page,
    profile
):

    print(
        "\n================================="
    )
    print(
        "WORK EXPERIENCE"
    )
    print(
        "================================="
    )

    record = work_record(
        profile
    )

    if not record:

        return {
            "status":
                "PROFILE_MISSING",

            "review_required":
                True,
        }

    frame = page.main_frame

    title = first_visible(
        frame,
        'input[name="jobTitle"], '
        'input[aria-label="jobTitle"]'
    )

    # If record not currently visible, click Add ONCE.
    if title is None:

        click_nearest_add(
            page,
            "Work Experience"
        )

        title = first_visible(
            frame,
            'input[name="jobTitle"], '
            'input[aria-label="jobTitle"]'
        )

    if title is None:

        return {
            "status":
                "FORM_NOT_OPEN",

            "review_required":
                True,
        }

    company = first_visible(
        frame,
        'input[name="companyName"], '
        'input[aria-label="companyName"]'
    )

    location = first_visible(
        frame,
        'input[name="location"], '
        'input[aria-label="location"]'
    )

    checkbox = first_visible(
        frame,
        'input[name="currentlyWorkHere"], '
        'input[type="checkbox"]'
    )

    description = first_visible(
        frame,
        "textarea"
    )

    results = []

    results.append(
        fill_text(
            title,
            record.get(
                "job_title"
            ),
            "job_title"
        )
    )

    results.append(
        fill_text(
            company,
            record.get(
                "employer"
            ),
            "employer"
        )
    )

    location_value = record.get(
        "location"
    )

    if isinstance(
        location_value,
        dict
    ):

        location_value = ", ".join(
            value
            for value in [
                location_value.get(
                    "city"
                ),
                location_value.get(
                    "state"
                ),
                location_value.get(
                    "country"
                ),
            ]
            if value
        )

    results.append(
        fill_text(
            location,
            location_value,
            "work_location"
        )
    )

    current_job = bool(
        record.get(
            "current_job",
            False
        )
    )

    if checkbox is not None:

        try:

            if (
                checkbox.is_checked()
                != current_job
            ):

                if current_job:
                    checkbox.check(
                        force=True
                    )
                else:
                    checkbox.uncheck(
                        force=True
                    )

                page.wait_for_timeout(
                    350
                )

                print(
                    f"SET                    "
                    f"current_job              "
                    f"{current_job}"
                )

            else:

                print(
                    f"ALREADY_SET            "
                    f"current_job              "
                    f"{current_job}"
                )

        except Exception:
            pass

    # ==================================================
    # Month + Year are separate in State Street Workday
    # ==================================================

    months = frame.locator(
        'input[aria-label="Month"]'
    )

    years = frame.locator(
        'input[aria-label="Year"]'
    )

    start_month = month_value(
        record.get(
            "start_month"
        )
    )

    start_year = profile_text(
        record.get(
            "start_year"
        )
    )

    month_element = (
        months.first
        if months.count() > 0
        else None
    )

    year_element = (
        years.first
        if years.count() > 0
        else None
    )

    results.append(
        fill_text(
            month_element,
            start_month,
            "work_start_month",
            overwrite_bad_date=True
        )
    )

    results.append(
        fill_text(
            year_element,
            start_year,
            "work_start_year"
        )
    )

    results.append(
        fill_text(
            description,
            record.get(
                "description"
            ),
            "description"
        )
    )

    bad = {
        "NOT_FOUND",
        "FILL_FAILED",
    }

    review = any(
        result.get(
            "status"
        )
        in bad
        for result
        in results
    )

    return {
        "status":
            "PROCESSED",

        "records":
            1,

        "review_required":
            review,

        "fields":
            results,
    }


# ======================================================
# DEGREE DROPDOWN
# ======================================================

def visible_options(
    page
):

    results = []

    selectors = [
        '[role="option"]',
        '[data-automation-id="promptOption"]',
        '[data-automation-id="menuItem"]',
    ]

    for frame in page.frames:

        for selector in selectors:

            try:

                options = frame.locator(
                    selector
                )

                for index in range(
                    options.count()
                ):

                    option = options.nth(
                        index
                    )

                    if not visible(
                        option
                    ):
                        continue

                    text = (
                        option
                        .inner_text(
                            timeout=300
                        )
                        .strip()
                    )

                    if text:
                        results.append(
                            (
                                text,
                                option
                            )
                        )

            except Exception:
                continue

    return results


def select_degree(
    page,
    button,
    desired
):

    if button is None:

        print(
            "NOT_FOUND              degree"
        )

        return {
            "field":
                "degree",

            "status":
                "NOT_FOUND",
        }

    try:

        current = (
            button
            .inner_text()
            .strip()
        )

    except Exception:

        current = ""

    if (
        current
        and
        "select one"
        not in normalize(
            current
        )
    ):

        print(
            f"ALREADY_SET            "
            f"degree                   "
            f"{current}"
        )

        return {
            "field":
                "degree",

            "status":
                "ALREADY_SET",

            "value":
                current,
        }

    button.click(
        timeout=3000
    )

    page.wait_for_timeout(
        600
    )

    options = visible_options(
        page
    )

    desired_values = [
        desired,
        "Master of Science",
        "Master's Degree",
        "Masters Degree",
        "Master Degree",
        "Masters",
    ]

    # exact
    for wanted in desired_values:

        for text, option in options:

            if (
                normalize(text)
                ==
                normalize(wanted)
            ):

                option.click(
                    timeout=3000
                )

                print(
                    f"SELECTED               "
                    f"degree                   "
                    f"{text}"
                )

                return {
                    "field":
                        "degree",

                    "status":
                        "SELECTED",

                    "value":
                        text,
                }

    # Fallback: first option containing master.
    for text, option in options:

        if "master" in normalize(
            text
        ):

            option.click(
                timeout=3000
            )

            print(
                f"SELECTED               "
                f"degree                   "
                f"{text}"
            )

            return {
                "field":
                    "degree",

                "status":
                    "SELECTED",

                "value":
                    text,
            }

    print(
        "SELECT_FAILED          degree"
    )

    return {
        "field":
            "degree",

        "status":
            "SELECT_FAILED",
    }


# ======================================================
# EDUCATION — FAST MODE
#
# Required in screenshot:
# School *
# Degree *
#
# Field of Study / GPA / From / To are optional.
# ======================================================

def fill_education(
    page,
    profile
):

    print(
        "\n================================="
    )
    print(
        "EDUCATION"
    )
    print(
        "================================="
    )

    record = education_record(
        profile
    )

    if not record:

        return {
            "status":
                "PROFILE_MISSING",

            "review_required":
                True,
        }

    frame = page.main_frame

    school = first_visible(
        frame,
        'input[name="schoolName"], '
        'input[aria-label="schoolName"]'
    )

    # ==================================================
    # CLICK EDUCATION ADD AUTOMATICALLY
    # ==================================================

    if school is None:

        clicked = (
            click_nearest_add(
                page,
                "Education"
            )
        )

        if clicked:

            page.wait_for_timeout(
                700
            )

        school = first_visible(
            frame,
            'input[name="schoolName"], '
            'input[aria-label="schoolName"]'
        )

    if school is None:

        print(
            "EDUCATION_FORM_NOT_OPEN"
        )

        return {
            "status":
                "FORM_NOT_OPEN",

            "review_required":
                True,
        }

    results = []

    results.append(
        fill_text(
            school,
            record.get(
                "school"
            ),
            "school"
        )
    )

    # ==================================================
    # DEGREE REQUIRED
    # ==================================================

    degree_button = None

    try:

        buttons = frame.locator(
            "button"
        )

        for index in range(
            buttons.count()
        ):

            button = buttons.nth(
                index
            )

            if not visible(
                button
            ):
                continue

            text = ""

            try:

                text = (
                    button
                    .inner_text(
                        timeout=300
                    )
                    .strip()
                )

            except Exception:
                pass

            aria = (
                button.get_attribute(
                    "aria-label"
                )
                or ""
            )

            combined = normalize(
                text
                + " "
                + aria
            )

            if (
                "degree"
                in combined
                and
                (
                    "select one"
                    in combined
                    or
                    "required"
                    in combined
                )
            ):

                degree_button = (
                    button
                )

                break

    except Exception:
        pass

    results.append(
        select_degree(
            page,
            degree_button,
            record.get(
                "degree"
            )
        )
    )

    # ==================================================
    # OPTIONAL FIELD OF STUDY
    # Try once. Never block application.
    # ==================================================

    try:

        searches = frame.locator(
            'input[placeholder="Search"]'
        )

        search = first_visible(
            searches
        )

        if search is not None:

            desired_field = (
                record.get(
                    "field_of_study"
                )
            )

            if desired_field:

                search.click(
                    timeout=2000
                )

                search.fill(
                    desired_field
                )

                page.wait_for_timeout(
                    500
                )

                options = visible_options(
                    page
                )

                matched = False

                for text, option in options:

                    if (
                        normalize(
                            desired_field
                        )
                        in normalize(
                            text
                        )
                    ):

                        option.click(
                            timeout=2000
                        )

                        print(
                            f"SELECTED               "
                            f"field_of_study           "
                            f"{text}"
                        )

                        matched = True
                        break

                if not matched:

                    # Workday can mark an unmatched autocomplete search
                    # aria-invalid even when Field of Study is optional.
                    # Clear the typed search value before closing the menu.
                    try:
                        search.fill("")
                    except Exception:
                        pass

                    try:
                        page.keyboard.press(
                            "Escape"
                        )
                    except Exception:
                        pass

                    page.wait_for_timeout(
                        200
                    )

                    print(
                        "SKIPPED_OPTIONAL       "
                        "field_of_study"
                    )

    except Exception:

        print(
            "SKIPPED_OPTIONAL       "
            "field_of_study"
        )

    # ==================================================
    # OPTIONAL YEARS
    # Fill if controls are present.
    # ==================================================

    try:

        year_inputs = frame.locator(
            'input[placeholder="YYYY"]'
        )

        visible_years = []

        for index in range(
            year_inputs.count()
        ):

            element = (
                year_inputs.nth(
                    index
                )
            )

            if visible(
                element
            ):

                visible_years.append(
                    element
                )

        if (
            len(visible_years) >= 1
            and
            record.get(
                "start_year"
            )
        ):

            fill_text(
                visible_years[0],
                record.get(
                    "start_year"
                ),
                "education_from"
            )

        if (
            len(visible_years) >= 2
            and
            record.get(
                "end_year"
            )
        ):

            fill_text(
                visible_years[1],
                record.get(
                    "end_year"
                ),
                "education_to"
            )

    except Exception:
        pass

    # Only SCHOOL + DEGREE block progress.

    required_results = (
        results
    )

    review = any(
        result.get(
            "status"
        )
        in {
            "NOT_FOUND",
            "FILL_FAILED",
            "SELECT_FAILED",
        }
        for result
        in required_results
    )

    return {
        "status":
            "PROCESSED",

        "records":
            1,

        "review_required":
            review,

        "fields":
            results,
    }


# ======================================================
# VALIDATION
# ======================================================

def invalid_required_fields(
    page
):

    """
    Return only invalid controls that are actually required.

    Workday may leave an optional autocomplete/search control with
    aria-invalid=true when no list option was selected. That should
    not block Save and Continue.
    """

    result = []

    for frame in page.frames:

        try:

            controls = frame.locator(
                '[aria-invalid="true"]'
            )

            for index in range(
                controls.count()
            ):

                control = controls.nth(
                    index
                )

                if not visible(
                    control
                ):
                    continue

                aria_required = (
                    control.get_attribute(
                        "aria-required"
                    )
                    or ""
                ).strip().lower()

                required_attr = (
                    control.get_attribute(
                        "required"
                    )
                )

                if (
                    aria_required != "true"
                    and
                    required_attr is None
                ):
                    continue

                label = (
                    control.get_attribute(
                        "aria-label"
                    )
                    or
                    control.get_attribute(
                        "name"
                    )
                    or
                    control.get_attribute(
                        "placeholder"
                    )
                    or
                    "required_unknown"
                )

                result.append(
                    label
                )

        except Exception:
            continue

    return list(
        dict.fromkeys(
            result
        )
    )

# ======================================================
# SKILLS
# ======================================================

def get_verified_skills(profile):

    skills = profile.get(
        "verified_facts.skills",
        []
    )

    if not isinstance(
        skills,
        list
    ):
        return []

    # Limit first run to strong/common Workday matches.
    return skills[:10]


def find_skills_input(page):

    for frame in page.frames:

        # ----------------------------------------------
        # LABEL LOOKUP
        # ----------------------------------------------

        try:

            locator = frame.get_by_label(
                "Type to Add Skills",
                exact=False
            )

            for index in range(
                locator.count()
            ):

                element = locator.nth(
                    index
                )

                if visible(element):

                    return (
                        frame,
                        element
                    )

        except Exception:
            pass

        # ----------------------------------------------
        # ARIA / PLACEHOLDER
        # ----------------------------------------------

        selectors = [
            'input[aria-label*="Type to Add Skills"]',
            'input[placeholder*="Type to Add Skills"]',
            'input[aria-label*="Add Skills"]',
            'input[placeholder*="Add Skills"]',
        ]

        for selector in selectors:

            try:

                locator = frame.locator(
                    selector
                )

                for index in range(
                    locator.count()
                ):

                    element = locator.nth(
                        index
                    )

                    if visible(
                        element
                    ):

                        return (
                            frame,
                            element
                        )

            except Exception:
                continue

    return (
        None,
        None
    )


def get_skill_options(page):

    results = []

    seen = set()

    selectors = [
        '[role="option"]',
        '[data-automation-id="promptOption"]',
        '[data-automation-id="menuItem"]',
    ]

    for frame in page.frames:

        for selector in selectors:

            try:

                options = frame.locator(
                    selector
                )

                for index in range(
                    options.count()
                ):

                    option = options.nth(
                        index
                    )

                    if not visible(
                        option
                    ):
                        continue

                    try:

                        text = (
                            option
                            .inner_text(
                                timeout=300
                            )
                            .strip()
                        )

                    except Exception:
                        continue

                    normalized = normalize(
                        text
                    )

                    if not normalized:
                        continue

                    if normalized in {
                        "no items",
                        "no items.",
                    }:
                        continue

                    if normalized in seen:
                        continue

                    seen.add(
                        normalized
                    )

                    results.append(
                        (
                            text,
                            option
                        )
                    )

            except Exception:
                continue

    return results


def find_existing_selected_skills(page):

    selected = set()

    # Workday commonly places a remove button
    # beside selected skill chips.

    for frame in page.frames:

        selectors = [
            'button[aria-label*="Remove"]',
            'button[title*="Remove"]',
        ]

        for selector in selectors:

            try:

                buttons = frame.locator(
                    selector
                )

                for index in range(
                    buttons.count()
                ):

                    button = buttons.nth(
                        index
                    )

                    if not visible(
                        button
                    ):
                        continue

                    text = (
                        button.get_attribute(
                            "aria-label"
                        )
                        or
                        button.get_attribute(
                            "title"
                        )
                        or
                        ""
                    )

                    text = (
                        text
                        .replace(
                            "Remove",
                            ""
                        )
                        .strip()
                    )

                    if text:

                        selected.add(
                            normalize(
                                text
                            )
                        )

            except Exception:
                continue

    return selected


def fill_skills(
    page,
    profile
):

    print(
        "\n================================="
    )

    print(
        "SKILLS"
    )

    print(
        "================================="
    )

    skills = get_verified_skills(
        profile
    )

    if not skills:

        print(
            "No verified skills found "
            "in candidate_profile.yaml."
        )

        return {
            "status":
                "PROFILE_MISSING",

            "selected_count":
                0,

            "review_required":
                True,
        }

    frame, skill_input = (
        find_skills_input(
            page
        )
    )

    if skill_input is None:

        print(
            "SKILLS_INPUT_NOT_FOUND"
        )

        return {
            "status":
                "INPUT_NOT_FOUND",

            "selected_count":
                0,

            "review_required":
                True,
        }

    existing = (
        find_existing_selected_skills(
            page
        )
    )

    selected_count = len(
        existing
    )

    if selected_count:

        print(
            f"ALREADY_SELECTED       "
            f"{selected_count} skill(s)"
        )

    selected_names = []

    # Strong/common ATS matches first.
    priority = [
        "Java",
        "Python",
        "MySQL",
        "Linux",
        "Git",
        "Spring Boot",
        "REST APIs",
        "AWS EC2",
        "AWS S3",
        "Spring Security",
    ]

    ordered = []

    for skill in priority:

        if skill in skills:
            ordered.append(
                skill
            )

    for skill in skills:

        if skill not in ordered:
            ordered.append(
                skill
            )

    # Don't overload the application.
    ordered = ordered[:8]

    for skill in ordered:

        if normalize(
            skill
        ) in existing:

            print(
                f"ALREADY_SET            "
                f"skill                    "
                f"{skill}"
            )

            continue

        try:

            # ------------------------------------------
            # Workday instructions explicitly require
            # typing a skill and pressing Enter before
            # options are loaded.
            # ------------------------------------------

            skill_input.click(
                timeout=2000
            )

            skill_input.fill(
                skill
            )

            skill_input.press(
                "Enter"
            )

            page.wait_for_timeout(
                700
            )

            options = get_skill_options(
                page
            )

            match = None

            # ------------------------------------------
            # EXACT MATCH FIRST
            # ------------------------------------------

            for text, option in options:

                if (
                    normalize(text)
                    ==
                    normalize(skill)
                ):

                    match = (
                        text,
                        option
                    )

                    break

            # ------------------------------------------
            # SAFE CONTAINS MATCH
            # Examples:
            # AWS -> Amazon Web Services (AWS)
            # ------------------------------------------

            if match is None:

                for text, option in options:

                    option_normalized = (
                        normalize(
                            text
                        )
                    )

                    skill_normalized = (
                        normalize(
                            skill
                        )
                    )

                    if (
                        skill_normalized
                        in option_normalized
                        or
                        option_normalized
                        in skill_normalized
                    ):

                        match = (
                            text,
                            option
                        )

                        break

            if match is None:

                print(
                    f"NO_MATCH               "
                    f"skill                    "
                    f"{skill}"
                )

                try:

                    skill_input.fill(
                        ""
                    )

                except Exception:
                    pass

                try:

                    page.keyboard.press(
                        "Escape"
                    )

                except Exception:
                    pass

                continue

            text, option = match

            option.click(
                timeout=2500
            )

            page.wait_for_timeout(
                300
            )

            selected_count += 1

            selected_names.append(
                text
            )

            print(
                f"SELECTED               "
                f"skill                    "
                f"{text}"
            )

        except Exception as exc:

            print(
                f"SKILL_FAILED           "
                f"{skill}: {exc}"
            )

            try:

                skill_input.fill(
                    ""
                )

            except Exception:
                pass

    # --------------------------------------------------
    # Workday requires at least one selected skill.
    # --------------------------------------------------

    ready = (
        selected_count > 0
    )

    print(
        f"\nSkills selected: "
        f"{selected_count}"
    )

    return {
        "status":
            (
                "PROCESSED"
                if ready
                else "NO_MATCH"
            ),

        "selected_count":
            selected_count,

        "selected":
            selected_names,

        "review_required":
            not ready,
    }



# ======================================================
# MAIN ENTRY
# ======================================================

def fill_experience_and_education(
    page,
    profile
):

    print(
        f"\nworkday_experience.py "
        f"VERSION {VERSION}"
    )

    # Resume parsing should already mostly be done.
    page.wait_for_timeout(
        1000
    )

    work = fill_work_experience(
        page,
        profile
    )

    education = fill_education(
        page,
        profile
    )

    skills = fill_skills(
        page,
        profile
    )

    invalid = invalid_required_fields(
        page
    )

    ready = (
            not work.get(
                "review_required",
                True
            )
            and
            not education.get(
                "review_required",
                True
            )
            and
            not skills.get(
                "review_required",
                True
            )
            and
            not invalid
    )

    print(
        "\nFAST CHECK:"
    )

    print(
        "work_ready:",
        not work.get(
            "review_required",
            True
        )
    )

    print(
        "education_ready:",
        not education.get(
            "review_required",
            True
        )
    )

    print(
        "invalid_fields:",
        invalid
    )

    print(
        "ready_to_continue:",
        ready
    )

    return {
        "work_experience":
            work,

        "education":
            education,

        "skills":
            skills,

        "invalid_fields":
            invalid,

        "ready_to_continue":
            ready,
    }
