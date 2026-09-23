# browser/workday_conflict_questions.py

VERSION = "2.1-user-review-resume"


def normalize(value):
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


def visible(element):
    try:
        return element.is_visible()
    except Exception:
        return False


def profile_value(profile, path, default=None):
    value = profile.get(path)
    return default if value is None else value


def close_open_prompts(page):
    """Close any Workday prompt/menu before opening the question we want."""
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(120)
        page.keyboard.press("Escape")
        page.wait_for_timeout(180)
    except Exception:
        pass


def _nearest_question_context(control, question_fragment):
    """
    Return the nearest ancestor text that contains the question fragment.

    Starting from the control instead of searching arbitrary DIV/SPAN text keeps
    us attached to the actual question. This avoids matching Workday's language
    menu, utility controls, or a large page ancestor containing many questions.
    """
    wanted = normalize(question_fragment)

    try:
        result = control.evaluate(
            r"""
            (el, wanted) => {
                const norm = s => (s || '').trim().toLowerCase().replace(/\s+/g, ' ');
                let node = el;
                for (let i = 0; i < 10 && node; i++, node = node.parentElement) {
                    const text = (node.innerText || '').trim();
                    const n = norm(text);
                    if (n.includes(wanted)) {
                        return { text, length: text.length, level: i };
                    }
                }
                return null;
            }
            """,
            wanted,
        )
    except Exception:
        return None

    if not result:
        return None

    if int(result.get("length", 999999)) > 2200:
        return None

    return result


def find_question_controls(page, question_fragment, selector):
    matches = []

    for frame in page.frames:
        try:
            controls = frame.locator(selector)
            count = min(controls.count(), 100)
        except Exception:
            continue

        for index in range(count):
            control = controls.nth(index)
            if not visible(control):
                continue

            context = _nearest_question_context(control, question_fragment)
            if context is None:
                continue

            matches.append((frame, control, context))

    return matches


def find_question_control(page, question_fragment, selector, occurrence=0):
    matches = find_question_controls(page, question_fragment, selector)

    if occurrence < 0 or occurrence >= len(matches):
        return None, None

    frame, control, _ = matches[occurrence]
    return frame, control


def _visible_options_in(locator):
    results = []
    seen = set()

    selectors = [
        '[role="option"]',
        '[data-automation-id="promptOption"]',
        '[data-automation-id="menuItem"]',
    ]

    for selector in selectors:
        try:
            options = locator.locator(selector)
            count = options.count()
        except Exception:
            continue

        for index in range(count):
            option = options.nth(index)
            if not visible(option):
                continue

            try:
                text = option.inner_text(timeout=300).strip()
            except Exception:
                text = ""

            if not text:
                try:
                    text = (option.get_attribute("data-automation-label") or "").strip()
                except Exception:
                    text = ""

            key = normalize(text)
            if not key or key in seen:
                continue

            seen.add(key)
            results.append((text, option))

    return results


def get_open_options(page, frame, button):
    """Get options belonging to the dropdown just opened."""
    for attr in ("aria-controls", "aria-owns"):
        try:
            popup_id = button.get_attribute(attr)
        except Exception:
            popup_id = None

        if not popup_id:
            continue

        try:
            escaped = str(popup_id).replace('"', '\\"')
            popup = frame.locator(f'[id="{escaped}"]')
            if popup.count():
                options = _visible_options_in(popup.first)
                if options:
                    return options
        except Exception:
            pass

    options = _visible_options_in(frame)
    if options:
        return options

    results = []
    seen = set()
    for candidate_frame in page.frames:
        for text, option in _visible_options_in(candidate_frame):
            key = normalize(text)
            if key in seen:
                continue
            seen.add(key)
            results.append((text, option))
    return results


def _dropdown_current(page, question_fragment, occurrence=0):
    _frame, button = find_question_control(
        page,
        question_fragment,
        'button[aria-haspopup="listbox"], [role="combobox"]',
        occurrence=occurrence,
    )
    if button is None:
        return ""
    try:
        text = button.inner_text(timeout=500).strip()
    except Exception:
        return ""
    value = normalize(text).replace(" required", "").strip()
    if not value or "select one" in value or value in {"select", "required"}:
        return ""
    return text


def _text_current(page, question_fragment, occurrence=0):
    _frame, element = find_question_control(
        page,
        question_fragment,
        'textarea, input:not([type="hidden"]):not([type="radio"]):not([type="checkbox"])',
        occurrence=occurrence,
    )
    if element is None:
        return ""
    try:
        return element.input_value(timeout=500).strip()
    except Exception:
        return ""


def conflict_page_has_user_values(page):
    """
    Detect a conflict page that the user has already completed manually.

    This does not learn or infer the answers. It only permits navigation after
    the user supplied every required value. The final submission policy still
    classifies this page as conflict_of_interest and blocks automatic submit.
    """
    checks = [
        _dropdown_current(page, "Are you a relative of a current Public Official?"),
        _text_current(page, "If yes, what is your relationship with this individual?", 0),
        _text_current(page, "If yes, please list the institution name and level of the individual.", 0),
        _dropdown_current(page, "Are you a relative of a current senior level person"),
        _text_current(page, "If yes, what is your relationship with this individual?", 1),
        _text_current(page, "If yes, please list the institution name and level of the individual.", 1),
        _dropdown_current(page, "Please select one of the below options:"),
        _text_current(page, "Enter your name (required) and the name of your agency"),
    ]
    return all(bool(str(value).strip()) for value in checks)


def select_question(page, question_fragment, desired, occurrence=0):
    frame, button = find_question_control(
        page,
        question_fragment,
        'button[aria-haspopup="listbox"], [role="combobox"]',
        occurrence=occurrence,
    )

    if button is None:
        print("QUESTION_DROPDOWN_NOT_FOUND", question_fragment)
        return False

    try:
        current = button.inner_text(timeout=500).strip()
    except Exception:
        current = ""

    desired_norm = normalize(desired)
    current_norm = normalize(current)

    if desired_norm and (
        current_norm == desired_norm
        or current_norm.startswith(desired_norm + " ")
        or desired_norm in current_norm.split(" required")[0]
    ):
        print(f"ALREADY_SET            {desired}")
        return True

    close_open_prompts(page)

    try:
        button.scroll_into_view_if_needed()
        page.wait_for_timeout(100)
        button.click(timeout=4000)
    except Exception as exc:
        print("DROPDOWN_CLICK_FAILED:", exc)
        return False

    page.wait_for_timeout(350)
    options = get_open_options(page, frame, button)

    for text, option in options:
        if normalize(text) != desired_norm:
            continue

        try:
            option.click(timeout=3000)
        except Exception:
            try:
                option.click(timeout=3000, force=True)
            except Exception as exc:
                print("OPTION_CLICK_FAILED:", exc)
                close_open_prompts(page)
                return False

        page.wait_for_timeout(250)
        print(f"SELECTED               {desired}")
        return True

    print(f"OPTION_NOT_FOUND        {desired}")
    print("Available:", [text for text, _ in options])
    close_open_prompts(page)
    return False


def fill_question_text(page, question_fragment, value, occurrence=0):
    frame, element = find_question_control(
        page,
        question_fragment,
        'textarea, input:not([type="hidden"]):not([type="radio"]):not([type="checkbox"])',
        occurrence=occurrence,
    )

    if element is None:
        print("TEXT_QUESTION_NOT_FOUND ", question_fragment, "occurrence", occurrence)
        return False

    try:
        current = element.input_value(timeout=500).strip()
    except Exception:
        current = ""

    desired = "" if value is None else str(value).strip()

    if current == desired and desired:
        print(f"ALREADY_SET            {desired}")
        return True

    if current and not desired:
        print(f"ALREADY_SET            {current}")
        return True

    try:
        element.fill(desired)
        print(f"FILLED                 {desired}")
        return True
    except Exception as exc:
        print("TEXT_FILL_FAILED:", exc)
        return False


def inspect_dropdown_options(page, question_fragment, occurrence=0):
    frame, button = find_question_control(
        page,
        question_fragment,
        'button[aria-haspopup="listbox"], [role="combobox"]',
        occurrence=occurrence,
    )

    if button is None:
        print("QUESTION_DROPDOWN_NOT_FOUND", question_fragment)
        return []

    close_open_prompts(page)

    try:
        button.scroll_into_view_if_needed()
        button.click(timeout=4000)
        page.wait_for_timeout(350)
    except Exception as exc:
        print("DROPDOWN_INSPECT_FAILED:", exc)
        return []

    options = [text for text, _ in get_open_options(page, frame, button)]

    print("\nOPTIONS FOR:")
    print(question_fragment)
    for option in options:
        print(" -", option)

    close_open_prompts(page)
    return options


def fill_conflict_questions(page, profile):
    print(f"\nworkday_conflict_questions.py VERSION {VERSION}")

    # If the user already completed every required control during a manual
    # review cycle, do not force those sensitive answers into the profile or
    # learned memory. Just allow the adapter to validate/advance the page.
    if conflict_page_has_user_values(page):
        print("USER_PROVIDED          conflict page complete")
        return {"ready": True, "source": "USER_PROVIDED"}

    prefix = "application_questions.conflicts_of_interest."

    public_relative = profile_value(profile, prefix + "relative_public_official")
    senior_relative = profile_value(
        profile,
        prefix + "relative_senior_commercial_person",
    )
    recruitment_option = profile_value(profile, prefix + "recruitment_option")
    name_and_agency = profile_value(profile, prefix + "name_and_agency")

    if public_relative in {None, "REVIEW"}:
        return {"ready": False, "reason": "relative_public_official"}

    if senior_relative in {None, "REVIEW"}:
        return {"ready": False, "reason": "relative_senior_commercial_person"}

    public_answer = "Yes" if bool(public_relative) else "No"
    if not select_question(
        page,
        "Are you a relative of a current Public Official?",
        public_answer,
    ):
        return {"ready": False, "reason": "public_official_dropdown"}

    public_relationship = profile_value(
        profile,
        prefix + "public_official_relationship",
    )
    public_institution = profile_value(
        profile,
        prefix + "public_official_institution_level",
    )

    if not public_relative:
        public_relationship = "N/A"
        public_institution = "N/A"

    if not public_relationship:
        return {"ready": False, "reason": "public_relationship_missing"}
    if not public_institution:
        return {"ready": False, "reason": "public_institution_missing"}

    if not fill_question_text(
        page,
        "If yes, what is your relationship with this individual?",
        public_relationship,
        occurrence=0,
    ):
        return {"ready": False, "reason": "public_relationship_control"}

    if not fill_question_text(
        page,
        "If yes, please list the institution name and level of the individual.",
        public_institution,
        occurrence=0,
    ):
        return {"ready": False, "reason": "public_institution_control"}

    senior_answer = "Yes" if bool(senior_relative) else "No"
    if not select_question(
        page,
        "Are you a relative of a current senior level person",
        senior_answer,
    ):
        return {"ready": False, "reason": "senior_commercial_dropdown"}

    senior_relationship = profile_value(
        profile,
        prefix + "senior_commercial_relationship",
    )
    senior_institution = profile_value(
        profile,
        prefix + "senior_commercial_institution_level",
    )

    if not senior_relative:
        senior_relationship = "N/A"
        senior_institution = "N/A"

    if not senior_relationship:
        return {"ready": False, "reason": "senior_relationship_missing"}
    if not senior_institution:
        return {"ready": False, "reason": "senior_institution_missing"}

    if not fill_question_text(
        page,
        "If yes, what is your relationship with this individual?",
        senior_relationship,
        occurrence=1,
    ):
        return {"ready": False, "reason": "senior_relationship_control"}

    if not fill_question_text(
        page,
        "If yes, please list the institution name and level of the individual.",
        senior_institution,
        occurrence=1,
    ):
        return {"ready": False, "reason": "senior_institution_control"}

    if recruitment_option in {None, "REVIEW"}:
        options = inspect_dropdown_options(
            page,
            "Please select one of the below options:",
        )
        return {
            "ready": False,
            "reason": "recruitment_option_review",
            "available_options": options,
        }

    if not select_question(
        page,
        "Please select one of the below options:",
        recruitment_option,
    ):
        return {"ready": False, "reason": "recruitment_option"}

    if name_and_agency in {None, "", "REVIEW"}:
        return {"ready": False, "reason": "name_and_agency_review"}

    if not fill_question_text(
        page,
        "Enter your name (required) and the name of your agency",
        name_and_agency,
    ):
        return {"ready": False, "reason": "name_and_agency"}

    return {"ready": True, "source": "LOCKED_PROFILE"}
