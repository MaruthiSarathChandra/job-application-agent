from __future__ import annotations

from browser.workday_experience import (
    fill_experience_and_education as legacy_fill_experience_and_education,
    invalid_required_fields,
)


VERSION = "1.0-resilient-repair"


def _norm(value) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _visible(locator) -> bool:
    try:
        return locator.is_visible()
    except Exception:
        return False


def _profile_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def _education_record(profile):
    records = profile.get("education_history", []) or []
    if isinstance(records, list) and records:
        return records[0]

    school = profile.get("education.university")
    highest = profile.get("education.highest_degree")
    graduation = profile.get("education.graduation_date")
    if not school:
        return None

    highest_norm = _norm(highest)
    degree = "Master of Science" if "master" in highest_norm or "ms" in highest_norm else _profile_text(highest)
    field = "Computer Science" if "computer science" in highest_norm else ""
    end_year = ""
    if graduation:
        end_year = str(graduation).split("-")[0]

    return {
        "school": school,
        "degree": degree,
        "field_of_study": field,
        "start_year": "2024",
        "end_year": end_year,
    }


def _first_visible(frame, selectors):
    for selector in selectors:
        try:
            items = frame.locator(selector)
        except Exception:
            continue
        for index in range(items.count()):
            item = items.nth(index)
            if _visible(item):
                return item
    return None


def _find_text_control(frame, label_fragment: str):
    try:
        loc = frame.get_by_label(label_fragment, exact=False)
        for index in range(loc.count()):
            item = loc.nth(index)
            if _visible(item):
                return item
    except Exception:
        pass
    return None


def _visible_options(page):
    result = []
    seen = set()
    selectors = (
        '[data-automation-id="promptOption"]',
        '[role="option"]',
        '[data-automation-id="menuItem"]',
    )
    for frame in page.frames:
        for selector in selectors:
            try:
                items = frame.locator(selector)
            except Exception:
                continue
            for index in range(items.count()):
                item = items.nth(index)
                if not _visible(item):
                    continue
                try:
                    text = (item.inner_text(timeout=300) or "").strip()
                except Exception:
                    text = ""
                if not text:
                    try:
                        text = (item.get_attribute("data-automation-label") or "").strip()
                    except Exception:
                        text = ""
                normalized = _norm(text)
                if not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                result.append((text, item))
    return result


def _click(page, item) -> bool:
    try:
        item.scroll_into_view_if_needed(timeout=1000)
    except Exception:
        pass
    try:
        item.click(timeout=2200)
        page.wait_for_timeout(200)
        return True
    except Exception:
        try:
            item.click(timeout=1800, force=True)
            page.wait_for_timeout(200)
            return True
        except Exception:
            return False


def _close_prompt(page):
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(100)
        page.keyboard.press("Escape")
        page.wait_for_timeout(150)
    except Exception:
        pass


def _find_heading(page, text):
    desired = _norm(text)
    for frame in page.frames:
        try:
            headings = frame.locator("h1, h2, h3, h4, legend, [role=heading]")
        except Exception:
            continue
        for index in range(headings.count()):
            heading = headings.nth(index)
            if not _visible(heading):
                continue
            try:
                current = _norm(heading.inner_text(timeout=300))
            except Exception:
                continue
            if current == desired or desired in current:
                return frame, heading
    return None, None


def _click_add_for_section(page, section_name: str) -> bool:
    frame, heading = _find_heading(page, section_name)
    if frame is None or heading is None:
        return False

    # Prefer a button inside the closest compact container around the section.
    try:
        candidate = heading.locator(
            "xpath=ancestor::*[.//button][1]//button[contains(., 'Add')]"
        )
        for index in range(candidate.count()):
            button = candidate.nth(index)
            if _visible(button) and _click(page, button):
                print(f"REPAIR_CLICKED_ADD     {section_name}")
                return True
    except Exception:
        pass

    try:
        heading_box = heading.bounding_box()
    except Exception:
        heading_box = None
    if not heading_box:
        return False

    choices = []
    for selector in (
        'button[data-automation-id="add-button"]',
        'button:has-text("Add Another")',
        'button:has-text("Add")',
    ):
        try:
            buttons = frame.locator(selector)
        except Exception:
            continue
        for index in range(buttons.count()):
            button = buttons.nth(index)
            if not _visible(button):
                continue
            try:
                box = button.bounding_box()
            except Exception:
                box = None
            if not box or box["y"] <= heading_box["y"]:
                continue
            choices.append((box["y"] - heading_box["y"], button))

    for _distance, button in sorted(choices, key=lambda item: item[0]):
        if _click(page, button):
            print(f"REPAIR_CLICKED_ADD     {section_name}")
            return True
    return False


def _fill_school(page, frame, school, desired: str) -> bool:
    if school is None or not desired:
        return False
    try:
        current = (school.input_value(timeout=300) or "").strip()
    except Exception:
        current = ""
    if current and _norm(desired) in _norm(current):
        return True

    try:
        school.fill(desired)
        page.wait_for_timeout(500)
    except Exception:
        return False

    options = _visible_options(page)
    for text, option in options:
        if _norm(text) == _norm(desired) or _norm(desired) in _norm(text):
            if _click(page, option):
                print(f"REPAIR_SELECTED        school                   {text}")
                return True

    # Some tenants accept free-text school names.
    try:
        return _norm(school.input_value(timeout=300)) == _norm(desired)
    except Exception:
        return False


def _find_degree_control(frame):
    control = _find_text_control(frame, "Degree")
    if control is not None:
        return control
    return _first_visible(
        frame,
        (
            'button[aria-label*="Degree" i]',
            '[role="combobox"][aria-label*="Degree" i]',
            'button[id*="degree" i]',
            'button[data-automation-id*="degree" i]',
            'input[aria-label*="Degree" i]',
        ),
    )


def _control_value(control) -> str:
    if control is None:
        return ""
    try:
        value = (control.input_value(timeout=300) or "").strip()
        if value:
            return value
    except Exception:
        pass
    try:
        return (control.inner_text(timeout=300) or "").strip()
    except Exception:
        return ""


def _select_degree(page, control, desired: str) -> bool:
    if control is None:
        return False

    current = _control_value(control)
    if current and "select one" not in _norm(current) and "search" not in _norm(current):
        return True

    try:
        control.click(timeout=2200)
    except Exception:
        try:
            control.focus()
            control.press("ArrowDown")
        except Exception:
            return False
    page.wait_for_timeout(350)

    desired_values = [
        desired,
        "Master of Science",
        "Master's Degree",
        "Masters Degree",
        "Master Degree",
        "Masters",
    ]
    options = _visible_options(page)
    for wanted in desired_values:
        if not wanted:
            continue
        for text, option in options:
            if _norm(text) == _norm(wanted):
                if _click(page, option):
                    print(f"REPAIR_SELECTED        degree                   {text}")
                    return True

    for text, option in options:
        if "master" in _norm(text):
            if _click(page, option):
                print(f"REPAIR_SELECTED        degree                   {text}")
                return True
    return False


def repair_education(page, profile) -> dict:
    record = _education_record(profile)
    if not record:
        return {"status": "PROFILE_MISSING", "review_required": True}

    frame = page.main_frame
    school_selectors = (
        'input[name="schoolName"]',
        'input[name*="school" i]',
        'input[id*="school" i]',
        'input[aria-label*="school" i]',
        'input[data-automation-id*="school" i]',
    )
    school = _find_text_control(frame, "School") or _first_visible(frame, school_selectors)

    if school is None:
        _close_prompt(page)
        if _click_add_for_section(page, "Education"):
            page.wait_for_timeout(1000)
        school = _find_text_control(frame, "School") or _first_visible(frame, school_selectors)

    if school is None:
        print("REPAIR_EDUCATION_FAIL  school control not found")
        return {"status": "FORM_NOT_OPEN", "review_required": True}

    school_ok = _fill_school(page, frame, school, _profile_text(record.get("school")))
    degree = _find_degree_control(frame)
    degree_ok = _select_degree(page, degree, _profile_text(record.get("degree")))
    _close_prompt(page)

    print(f"REPAIR_EDUCATION       school={school_ok} degree={degree_ok}")
    return {
        "status": "PROCESSED" if school_ok and degree_ok else "REVIEW",
        "review_required": not (school_ok and degree_ok),
        "school_ok": school_ok,
        "degree_ok": degree_ok,
    }


def _selected_skill_names(page):
    selected = set()
    for frame in page.frames:
        for selector in (
            'button[aria-label*="Remove" i]',
            'button[title*="Remove" i]',
            '[data-automation-id*="selectedItem"]',
        ):
            try:
                items = frame.locator(selector)
            except Exception:
                continue
            for index in range(items.count()):
                item = items.nth(index)
                if not _visible(item):
                    continue
                try:
                    text = (
                        item.get_attribute("aria-label")
                        or item.get_attribute("title")
                        or item.inner_text(timeout=300)
                        or ""
                    )
                except Exception:
                    text = ""
                cleaned = text.replace("Remove", "").replace("remove", "").strip()
                if cleaned:
                    selected.add(_norm(cleaned))
    return selected


def _find_skill_input(page):
    for frame in page.frames:
        try:
            labels = frame.get_by_label("Type to Add Skills", exact=False)
            for index in range(labels.count()):
                item = labels.nth(index)
                if _visible(item):
                    return frame, item
        except Exception:
            pass

        input_control = _first_visible(
            frame,
            (
                'input[id="skills--skills"]',
                'input[data-uxi-multiselect-id]',
                'input[aria-label*="Add Skills" i]',
                'input[placeholder="Search"]',
            ),
        )
        if input_control is not None:
            try:
                parent_text = _norm(input_control.evaluate("el => (el.closest('section') || el.parentElement)?.innerText || ''"))
            except Exception:
                parent_text = ""
            if "skill" in parent_text or input_control.get_attribute("id") == "skills--skills":
                return frame, input_control
    return None, None


def _verified_skills(profile):
    skills = profile.get("verified_facts.skills", []) or []
    if not isinstance(skills, list):
        return []
    priority = [
        "Java", "Python", "MySQL", "Linux", "Git", "Spring Boot",
        "REST APIs", "AWS EC2", "AWS S3", "Spring Security", "JWT",
    ]
    result = []
    for skill in priority:
        if skill in skills and skill not in result:
            result.append(skill)
    for skill in skills:
        if skill not in result:
            result.append(skill)
    return result[:8]


def repair_skills(page, profile) -> dict:
    existing = _selected_skill_names(page)
    if existing:
        print(f"REPAIR_SKILLS          existing={len(existing)}")
        return {
            "status": "PROCESSED",
            "selected_count": len(existing),
            "review_required": False,
        }

    skills = _verified_skills(profile)
    if not skills:
        return {"status": "PROFILE_MISSING", "selected_count": 0, "review_required": True}

    selected = set()
    for skill in skills:
        _close_prompt(page)
        frame, skill_input = _find_skill_input(page)
        if skill_input is None:
            break

        try:
            skill_input.fill("")
            skill_input.fill(skill)
            page.wait_for_timeout(650)
        except Exception:
            continue

        options = _visible_options(page)
        if not options:
            try:
                skill_input.press("Enter")
                page.wait_for_timeout(500)
            except Exception:
                pass
            options = _visible_options(page)

        match = None
        skill_norm = _norm(skill)
        for text, option in options:
            if _norm(text) == skill_norm:
                match = (text, option)
                break
        if match is None:
            for text, option in options:
                option_norm = _norm(text)
                if skill_norm in option_norm or option_norm in skill_norm:
                    match = (text, option)
                    break

        if match is None:
            try:
                skill_input.fill("")
            except Exception:
                pass
            continue

        text, option = match
        if _click(page, option):
            selected.add(_norm(text))
            print(f"REPAIR_SELECTED        skill                    {text}")
            _close_prompt(page)
        if len(selected) >= 4:
            break

    selected.update(_selected_skill_names(page))
    return {
        "status": "PROCESSED" if selected else "NO_MATCH",
        "selected_count": len(selected),
        "review_required": not bool(selected),
    }


def fill_experience_and_education(page, profile):
    """
    Run the proven legacy Workday filler first, then repair tenant-specific
    education/skills controls when the legacy State-Street selectors miss them.
    """
    print(f"\nworkday_experience_resilient.py VERSION {VERSION}")
    result = legacy_fill_experience_and_education(page, profile)

    work = result.get("work_experience") or {"review_required": True}
    education = result.get("education") or {"review_required": True}
    skills = result.get("skills") or {"review_required": True}

    if education.get("review_required"):
        _close_prompt(page)
        education = repair_education(page, profile)

    # Avoid repeatedly fighting a Workday autocomplete when at least one skill
    # is already selected. Otherwise use a non-clicking input repair path.
    if skills.get("review_required") or int(skills.get("selected_count") or 0) <= 0:
        _close_prompt(page)
        skills = repair_skills(page, profile)

    _close_prompt(page)
    invalid = invalid_required_fields(page)
    ready = (
        not work.get("review_required", True)
        and not education.get("review_required", True)
        and not skills.get("review_required", True)
        and not invalid
    )

    print("\nRESILIENT CHECK:")
    print("work_ready:", not work.get("review_required", True))
    print("education_ready:", not education.get("review_required", True))
    print("skills_ready:", not skills.get("review_required", True))
    print("invalid_fields:", invalid)
    print("ready_to_continue:", ready)

    return {
        "work_experience": work,
        "education": education,
        "skills": skills,
        "invalid_fields": invalid,
        "ready_to_continue": ready,
    }
