# browser/workday_conflict_questions.py

VERSION = "1.0-state-street-conflicts"


def normalize(value):

    if value is None:
        return ""

    return " ".join(
        str(value)
        .strip()
        .lower()
        .split()
    )


def visible(element):

    try:
        return element.is_visible()

    except Exception:
        return False


def profile_value(
    profile,
    path,
    default=None
):

    value = profile.get(
        path
    )

    if value is None:
        return default

    return value


# ======================================================
# FIND QUESTION
# ======================================================

def find_question_element(
    page,
    question_fragment
):

    wanted = normalize(
        question_fragment
    )

    for frame in page.frames:

        selectors = [
            "label",
            "div",
            "span",
            "p",
            "legend",
        ]

        for selector in selectors:

            try:

                elements = frame.locator(
                    selector
                )

                for index in range(
                    min(
                        elements.count(),
                        500
                    )
                ):

                    element = elements.nth(
                        index
                    )

                    if not visible(
                        element
                    ):
                        continue

                    try:

                        text = (
                            element
                            .inner_text(
                                timeout=250
                            )
                            .strip()
                        )

                    except Exception:
                        continue

                    if wanted in normalize(
                        text
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


# ======================================================
# FIND SMALLEST QUESTION CONTAINER
# ======================================================

def find_question_container(
    page,
    question_fragment,
    need_button=False,
    need_input=False
):

    frame, question = (
        find_question_element(
            page,
            question_fragment
        )
    )

    if (
        frame is None
        or
        question is None
    ):

        return (
            None,
            None
        )

    for level in range(
        1,
        10
    ):

        try:

            container = (
                question.locator(
                    f"xpath=ancestor::*[{level}]"
                )
                .first
            )

            if not visible(
                container
            ):
                continue

            if need_button:

                buttons = (
                    container.locator(
                        'button[aria-haspopup="listbox"], '
                        '[role="combobox"], '
                        'button'
                    )
                )

                if buttons.count() == 0:
                    continue

            if need_input:

                inputs = (
                    container.locator(
                        'input:not([type="hidden"]), '
                        "textarea"
                    )
                )

                if inputs.count() == 0:
                    continue

            return (
                frame,
                container
            )

        except Exception:
            continue

    return (
        frame,
        None
    )


# ======================================================
# VISIBLE OPTIONS
# ======================================================

def get_visible_options(page):

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

                    key = normalize(
                        text
                    )

                    if not key:
                        continue

                    if key in seen:
                        continue

                    seen.add(
                        key
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


# ======================================================
# SELECT QUESTION ANSWER
# ======================================================

def select_question(
    page,
    question_fragment,
    desired
):

    frame, container = (
        find_question_container(
            page,
            question_fragment,
            need_button=True
        )
    )

    if container is None:

        print(
            "QUESTION_NOT_FOUND      ",
            question_fragment
        )

        return False

    button = None

    try:

        candidates = (
            container.locator(
                'button[aria-haspopup="listbox"], '
                '[role="combobox"]'
            )
        )

        for index in range(
            candidates.count()
        ):

            candidate = (
                candidates.nth(
                    index
                )
            )

            if visible(
                candidate
            ):

                button = candidate
                break

    except Exception:
        pass

    if button is None:

        # Workday fallback
        try:

            candidates = (
                container.locator(
                    "button"
                )
            )

            for index in range(
                candidates.count()
            ):

                candidate = (
                    candidates.nth(
                        index
                    )
                )

                if not visible(
                    candidate
                ):
                    continue

                try:

                    text = (
                        candidate
                        .inner_text()
                        .strip()
                    )

                except Exception:
                    text = ""

                if (
                    "select one"
                    in normalize(
                        text
                    )
                ):

                    button = candidate
                    break

        except Exception:
            pass

    if button is None:

        print(
            "DROPDOWN_NOT_FOUND      ",
            question_fragment
        )

        return False

    try:

        current = (
            button
            .inner_text()
            .strip()
        )

    except Exception:
        current = ""

    if (
        normalize(current)
        ==
        normalize(desired)
    ):

        print(
            f"ALREADY_SET            "
            f"{desired}"
        )

        return True

    try:

        button.click(
            timeout=3000
        )

    except Exception as exc:

        print(
            "DROPDOWN_CLICK_FAILED:",
            exc
        )

        return False

    page.wait_for_timeout(
        400
    )

    options = get_visible_options(
        page
    )

    for text, option in options:

        if (
            normalize(text)
            ==
            normalize(desired)
        ):

            option.click(
                timeout=3000
            )

            print(
                f"SELECTED               "
                f"{desired}"
            )

            return True

    print(
        f"OPTION_NOT_FOUND        "
        f"{desired}"
    )

    print(
        "Available:",
        [
            text
            for text, _
            in options
        ]
    )

    try:
        page.keyboard.press(
            "Escape"
        )
    except Exception:
        pass

    return False


# ======================================================
# TEXT QUESTION
# ======================================================

def fill_question_text(
    page,
    question_fragment,
    value
):

    frame, container = (
        find_question_container(
            page,
            question_fragment,
            need_input=True
        )
    )

    if container is None:

        print(
            "TEXT_QUESTION_NOT_FOUND ",
            question_fragment
        )

        return False

    element = None

    try:

        controls = (
            container.locator(
                'input:not([type="hidden"]), '
                "textarea"
            )
        )

        for index in range(
            controls.count()
        ):

            candidate = controls.nth(
                index
            )

            if visible(
                candidate
            ):

                element = candidate
                break

    except Exception:
        pass

    if element is None:

        print(
            "TEXT_INPUT_NOT_FOUND    ",
            question_fragment
        )

        return False

    try:

        current = (
            element
            .input_value()
            .strip()
        )

    except Exception:
        current = ""

    if current:

        print(
            f"ALREADY_SET            "
            f"{current}"
        )

        return True

    try:

        element.fill(
            str(value)
        )

        print(
            f"FILLED                 "
            f"{value}"
        )

        return True

    except Exception as exc:

        print(
            "TEXT_FILL_FAILED:",
            exc
        )

        return False


# ======================================================
# INSPECT UNKNOWN DROPDOWN
# ======================================================

def inspect_dropdown_options(
    page,
    question_fragment
):

    frame, container = (
        find_question_container(
            page,
            question_fragment,
            need_button=True
        )
    )

    if container is None:

        return []

    button = None

    try:

        buttons = (
            container.locator(
                'button[aria-haspopup="listbox"], '
                '[role="combobox"], '
                "button"
            )
        )

        for index in range(
            buttons.count()
        ):

            candidate = (
                buttons.nth(
                    index
                )
            )

            if not visible(
                candidate
            ):
                continue

            try:

                text = (
                    candidate
                    .inner_text()
                    .strip()
                )

            except Exception:
                text = ""

            if (
                "select one"
                in normalize(
                    text
                )
            ):

                button = candidate
                break

    except Exception:
        pass

    if button is None:
        return []

    try:

        button.click(
            timeout=3000
        )

        page.wait_for_timeout(
            400
        )

    except Exception:
        return []

    options = [
        text
        for text, _
        in get_visible_options(
            page
        )
    ]

    print(
        "\nOPTIONS FOR:"
    )

    print(
        question_fragment
    )

    for option in options:

        print(
            " -",
            option
        )

    try:

        page.keyboard.press(
            "Escape"
        )

    except Exception:
        pass

    return options


# ======================================================
# MAIN
# ======================================================

def fill_conflict_questions(
    page,
    profile
):

    print(
        f"\nworkday_conflict_questions.py "
        f"VERSION {VERSION}"
    )

    prefix = (
        "application_questions."
        "conflicts_of_interest."
    )

    public_relative = (
        profile_value(
            profile,
            prefix
            + "relative_public_official"
        )
    )

    senior_relative = (
        profile_value(
            profile,
            prefix
            + "relative_senior_commercial_person"
        )
    )

    recruitment_option = (
        profile_value(
            profile,
            prefix
            + "recruitment_option"
        )
    )

    name_and_agency = (
        profile_value(
            profile,
            prefix
            + "name_and_agency"
        )
    )

    # ==================================================
    # DON'T GUESS COMPLIANCE ANSWERS
    # ==================================================

    if public_relative in {
        None,
        "REVIEW",
    }:

        print(
            "\nREVIEW REQUIRED:"
            "\nrelative_public_official"
        )

        return {
            "ready":
                False,

            "reason":
                "relative_public_official",
        }

    if senior_relative in {
        None,
        "REVIEW",
    }:

        print(
            "\nREVIEW REQUIRED:"
            "\nrelative_senior_commercial_person"
        )

        return {
            "ready":
                False,

            "reason":
                "relative_senior_commercial_person",
        }

    # ==================================================
    # PUBLIC OFFICIAL
    # ==================================================

    public_answer = (
        "Yes"
        if bool(
            public_relative
        )
        else "No"
    )

    if not select_question(
        page,
        "Are you a relative of a current Public Official?",
        public_answer
    ):

        return {
            "ready":
                False,
        }

    public_relationship = (
        profile_value(
            profile,
            prefix
            + "public_official_relationship"
        )
    )

    public_institution = (
        profile_value(
            profile,
            prefix
            + "public_official_institution_level"
        )
    )

    if not public_relative:

        public_relationship = "N/A"
        public_institution = "N/A"

    if not public_relationship:
        return {
            "ready":
                False,

            "reason":
                "public_relationship_missing",
        }

    if not public_institution:
        return {
            "ready":
                False,

            "reason":
                "public_institution_missing",
        }

    fill_question_text(
        page,
        "If yes, what is your relationship with this individual?",
        public_relationship
    )

    fill_question_text(
        page,
        "If yes, please list the institution name and level of the individual.",
        public_institution
    )

    # ==================================================
    # SENIOR COMMERCIAL PERSON
    # ==================================================

    senior_answer = (
        "Yes"
        if bool(
            senior_relative
        )
        else "No"
    )

    if not select_question(
        page,
        "Are you a relative of a current senior level person",
        senior_answer
    ):

        return {
            "ready":
                False,
        }

    senior_relationship = (
        profile_value(
            profile,
            prefix
            + "senior_commercial_relationship"
        )
    )

    senior_institution = (
        profile_value(
            profile,
            prefix
            + "senior_commercial_institution_level"
        )
    )

    if not senior_relative:

        senior_relationship = "N/A"
        senior_institution = "N/A"

    fill_question_text(
        page,
        "If yes, what is your relationship with this individual?",
        senior_relationship
    )

    fill_question_text(
        page,
        "If yes, please list the institution name and level of the individual.",
        senior_institution
    )

    # ==================================================
    # THIRD DROPDOWN
    # ==================================================

    if recruitment_option in {
        None,
        "REVIEW",
    }:

        options = (
            inspect_dropdown_options(
                page,
                "Please select one of the below options:"
            )
        )

        return {
            "ready":
                False,

            "reason":
                "recruitment_option_review",

            "available_options":
                options,
        }

    if not select_question(
        page,
        "Please select one of the below options:",
        recruitment_option
    ):

        return {
            "ready":
                False,
        }

    # ==================================================
    # NAME / AGENCY
    # ==================================================

    if name_and_agency in {
        None,
        "",
        "REVIEW",
    }:

        return {
            "ready":
                False,

            "reason":
                "name_and_agency_review",
        }

    if not fill_question_text(
        page,
        "Enter your name (required) and the name of your agency",
        name_and_agency
    ):

        return {
            "ready":
                False,
        }

    return {
        "ready":
            True,
    }