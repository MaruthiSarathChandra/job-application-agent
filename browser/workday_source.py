from __future__ import annotations


PROMPT_SELECTORS = (
    '[data-automation-id="promptOption"]',
    '[data-automation-id="menuItem"]',
    '[role="option"]',
)


def _norm(value) -> str:
    return " ".join(str(value or "").strip().lower().split())


def normalize_job_source(value: str) -> str:
    """Map truthful profile source values to common Workday leaf labels."""
    raw = " ".join(str(value or "").strip().split())
    normalized = _norm(raw)
    aliases = {
        "linkedin": "LinkedIn Job Post",
        "linkedin job": "LinkedIn Job Post",
        "linkedin job post": "LinkedIn Job Post",
        "indeed": "Indeed",
        "naukri": "Naukri",
        "employee referral": "Employee Referral",
        "referral": "Employee Referral",
        "website": "Website",
        "company website": "Website",
        "event": "Event",
        "social media": "Social Media",
        "other": "Other",
    }
    return aliases.get(normalized, raw)


def job_source_categories(value: str):
    """Return likely Workday root categories in conservative priority order."""
    target = _norm(normalize_job_source(value))

    if target in {"indeed", "linkedin job post", "naukri"}:
        preferred = ["Third Party Job Boards"]
    elif target == "employee referral":
        preferred = ["Employee Referral", "Employees"]
    elif target == "website":
        preferred = ["Website", "Online Source"]
    elif target == "event":
        preferred = ["Event"]
    elif target == "social media":
        preferred = ["Social Media"]
    elif target == "other":
        preferred = ["Other"]
    else:
        preferred = []

    fallback = [
        "Third Party Job Boards",
        "Online Source",
        "Social Media",
        "Website",
        "Employee Referral",
        "Employees",
        "Event",
        "Other",
        "Campus / University",
        "Agency / Executive Search Firm",
        "Professional Association/Organization",
        "Online Source - Asia Job Boards",
    ]

    result = []
    for item in [*preferred, *fallback]:
        if item not in result:
            result.append(item)
    return result


def _visible(locator) -> bool:
    try:
        return locator.is_visible()
    except Exception:
        return False


def _visible_prompt_items(frame):
    results = []
    seen = set()
    for selector in PROMPT_SELECTORS:
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
            results.append((text, item))
    return results


def _find_prompt_item(frame, candidates):
    wanted = {_norm(value) for value in candidates if str(value or "").strip()}
    options = _visible_prompt_items(frame)

    for text, item in options:
        if _norm(text) in wanted:
            return item, text

    # Conservative decorated-label fallback, e.g. "LinkedIn Job Post (US)".
    for text, item in options:
        option = _norm(text)
        for desired in wanted:
            if len(desired) >= 6 and (desired in option or option in desired):
                return item, text
    return None, ""


def _click(page, item) -> bool:
    try:
        item.scroll_into_view_if_needed(timeout=1200)
    except Exception:
        pass
    try:
        item.click(timeout=2500)
        page.wait_for_timeout(250)
        return True
    except Exception:
        try:
            item.click(timeout=2000, force=True)
            page.wait_for_timeout(250)
            return True
        except Exception:
            return False


def _prompt_open(frame) -> bool:
    return bool(_visible_prompt_items(frame))


def _close_prompt(page):
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(120)
        page.keyboard.press("Escape")
        page.wait_for_timeout(180)
    except Exception:
        pass


def _find_source_control(page):
    selectors = (
        'input[id*="source--source" i]',
        'input[name*="source" i]',
        'input[aria-label*="How Did You Hear About Us" i]',
        '[role="combobox"][aria-label*="How Did You Hear About Us" i]',
        'button[aria-label*="How Did You Hear About Us" i]',
    )

    for frame in page.frames:
        for selector in selectors:
            try:
                items = frame.locator(selector)
            except Exception:
                continue
            for index in range(items.count()):
                item = items.nth(index)
                if _visible(item):
                    return frame, item

        try:
            labels = frame.get_by_text("How Did You Hear About Us?", exact=False)
        except Exception:
            labels = None
        if labels is not None:
            for index in range(labels.count()):
                label = labels.nth(index)
                if not _visible(label):
                    continue
                try:
                    container = label.locator("xpath=..")
                    controls = container.locator('input, [role="combobox"], button[aria-haspopup]')
                    for j in range(controls.count()):
                        control = controls.nth(j)
                        if _visible(control):
                            return frame, control
                except Exception:
                    continue

    return None, None


def _current_value(control) -> str:
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


def _is_real_selection(value: str) -> bool:
    normalized = _norm(value)
    return bool(
        normalized
        and normalized not in {"search", "select one", "select an option", "choose an option"}
    )


def _open_prompt(page, frame, control) -> bool:
    if _prompt_open(frame):
        return True

    try:
        control.scroll_into_view_if_needed(timeout=1200)
    except Exception:
        pass

    try:
        control.click(timeout=2500)
    except Exception:
        try:
            control.focus()
            control.press("ArrowDown")
        except Exception:
            return False

    page.wait_for_timeout(300)
    return _prompt_open(frame)


def _search_visible_level(page, frame, target_names) -> bool:
    target_names = [name for name in target_names if name]

    item, matched = _find_prompt_item(frame, target_names)
    if item is not None and _click(page, item):
        print(f"SELECTED               job_source               {matched}")
        return True

    for selector in ('input[placeholder="Search"]', 'input[aria-label="Search"]'):
        try:
            searches = frame.locator(selector)
        except Exception:
            continue
        for index in range(searches.count()):
            search = searches.nth(index)
            if not _visible(search):
                continue
            for target in target_names:
                try:
                    search.fill(target)
                    page.wait_for_timeout(400)
                except Exception:
                    continue
                item, matched = _find_prompt_item(frame, target_names)
                if item is not None and _click(page, item):
                    print(f"SELECTED               job_source               {matched}")
                    return True
    return False


def ensure_workday_job_source(page, profile) -> dict:
    """
    Fill Workday's hierarchical "How Did You Hear About Us?" control.

    The answer comes only from the explicit local candidate profile. This helper
    never invents a referral/source from the employer URL.
    """
    configured = profile.get("application_defaults.job_source")
    if not configured or not str(configured).strip():
        return {"handled": False, "reason": "profile_missing"}

    frame, control = _find_source_control(page)
    if control is None:
        return {"handled": False, "reason": "control_not_found"}

    current = _current_value(control)
    if _is_real_selection(current):
        print(f"ALREADY_SET            job_source               {current}")
        return {"handled": True, "value": current}

    target = normalize_job_source(str(configured))
    target_names = [target]
    if _norm(target) == "linkedin job post":
        target_names.extend(["LinkedIn", "LinkedIn Job Post"])

    print(f"\nLooking for Workday job source: {target}")

    _close_prompt(page)
    if not _open_prompt(page, frame, control):
        return {"handled": False, "reason": "prompt_not_open"}

    if _search_visible_level(page, frame, target_names):
        return {"handled": True, "value": target}

    for category in job_source_categories(target):
        _close_prompt(page)
        if not _open_prompt(page, frame, control):
            continue

        category_item, category_text = _find_prompt_item(frame, [category])
        if category_item is None:
            continue

        print(f"Checking source category: {category_text}")
        if not _click(page, category_item):
            continue

        page.wait_for_timeout(250)
        if _search_visible_level(page, frame, target_names):
            return {"handled": True, "value": target, "category": category_text}

    _close_prompt(page)
    return {"handled": False, "reason": "source_not_found", "target": target}
