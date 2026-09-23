import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from agent.company_policy import has_worked_for_company
from agent.field_classifier import classify_field
from agent.profile import CandidateProfile
from browser.form_filler import (
    collect_fields,
    fill_profile_field,
    get_live_page,
    safe_label,
)
from browser.workday_conflict_questions import fill_conflict_questions
from browser.workday_experience import fill_experience_and_education
from browser.workday_generic_questions import fill_generic_questions
from browser.workday_router import (
    detect_current_step,
    wait_for_application_step,
    wait_for_step_change,
)


VERSION = "6.0-deterministic-router"
REPORT_DIR = Path("data/workday_runs")
BROWSER_PROFILE = Path("data/browser_profile")
RESUME_FILE = Path("resumes/resume_7_months.docx")


def normalize(value):
    if value is None:
        return ""
    return " ".join(str(value).strip().lower().split())


def safe_attr(element, name):
    try:
        return element.get_attribute(name)
    except Exception:
        return None


def save_evidence(page, step_number, step_name, prefix="page"):
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    safe_step = step_name.replace("/", "_").replace(" ", "_")
    base = f"{prefix}_{step_number:02d}_{safe_step}"

    try:
        page.screenshot(
            path=str(REPORT_DIR / f"{base}.png"),
            full_page=True,
        )
    except Exception:
        pass

    try:
        body = page.locator("body").inner_text(timeout=3000)
        (REPORT_DIR / f"{base}.txt").write_text(body, encoding="utf-8")
    except Exception:
        pass


def get_validation_errors(page):
    errors = []
    seen = set()

    # Required controls marked invalid by Workday.
    for frame in page.frames:
        try:
            controls = frame.locator('[aria-invalid="true"]')
        except Exception:
            continue

        for index in range(min(controls.count(), 100)):
            control = controls.nth(index)
            try:
                if not control.is_visible():
                    continue

                aria_required = normalize(control.get_attribute("aria-required"))
                required_attr = control.get_attribute("required")
                if aria_required != "true" and required_attr is None:
                    continue

                label = safe_label(frame, control)
            except Exception:
                label = "Unknown required field"

            text = f"Invalid required field: {label}"
            key = normalize(text)
            if key not in seen:
                seen.add(key)
                errors.append(text)

    # Explicit visible Workday errors.
    selectors = [
        '[data-automation-id="errorMessage"]',
        '[data-automation-id*="errorMessage"]',
        '[data-automation-id*="validation"]',
        '[role="alert"]',
    ]

    for frame in page.frames:
        for selector in selectors:
            try:
                items = frame.locator(selector)
            except Exception:
                continue

            for index in range(min(items.count(), 50)):
                item = items.nth(index)
                try:
                    if not item.is_visible():
                        continue
                    text = item.inner_text(timeout=500).strip()
                except Exception:
                    continue

                key = normalize(text)
                if not key or key in seen:
                    continue

                seen.add(key)
                errors.append(text)

    return errors


def find_continue_button(page):
    for frame in page.frames:
        for name in ("Save and Continue", "Next", "Continue"):
            try:
                buttons = frame.get_by_role("button", name=name, exact=True)
                for index in range(buttons.count()):
                    button = buttons.nth(index)
                    if button.is_visible() and button.is_enabled():
                        return button
            except Exception:
                continue

        # Workday automation-id fallback.
        try:
            buttons = frame.locator('[data-automation-id="pageFooterNextButton"]')
            for index in range(buttons.count()):
                button = buttons.nth(index)
                if button.is_visible() and button.is_enabled():
                    return button
        except Exception:
            pass

    return None


def find_submit_button(page):
    for frame in page.frames:
        try:
            buttons = frame.get_by_role("button", name="Submit", exact=True)
            for index in range(buttons.count()):
                button = buttons.nth(index)
                if button.is_visible() and button.is_enabled():
                    return button
        except Exception:
            continue
    return None


def print_visible_control_inventory(page):
    print("\nVISIBLE CONTROL INVENTORY")
    print("-" * 72)
    seen = set()

    for frame_index, frame in enumerate(page.frames):
        try:
            controls = frame.locator(
                'input:not([type="hidden"]), textarea, select, button, '
                '[role="combobox"], [role="radio"], [role="checkbox"]'
            )
        except Exception:
            continue

        for index in range(min(controls.count(), 180)):
            control = controls.nth(index)
            try:
                if not control.is_visible():
                    continue
                tag = control.evaluate("el => el.tagName.toLowerCase()")
                label = (
                    safe_attr(control, "aria-label")
                    or safe_attr(control, "name")
                    or safe_attr(control, "placeholder")
                    or safe_attr(control, "data-automation-id")
                    or ""
                )
                text = ""
                if tag == "button":
                    try:
                        text = control.inner_text(timeout=300).strip()
                    except Exception:
                        pass
                key = (frame_index, tag, normalize(label), normalize(text))
                if key in seen:
                    continue
                seen.add(key)
                print(f"[frame={frame_index}] {tag:10} {(label or text)[:120]}")
            except Exception:
                continue

    print("-" * 72)


def _current_value(field):
    element = field["_element"]
    tag = normalize(field.get("tag"))

    if tag in {"input", "textarea", "select"}:
        try:
            return str(element.input_value()).strip()
        except Exception:
            return ""

    try:
        return str(element.inner_text()).strip()
    except Exception:
        return ""


def _profile_field_already_correct(profile, field, classification):
    path = classification.get("profile_path")
    if not path:
        return False

    desired = profile.get(path)
    if desired is None:
        return False

    desired_norm = normalize(desired)
    if not desired_norm:
        return False

    current_norm = normalize(_current_value(field))
    if not current_norm:
        return False

    # Buttons often include words such as "Required" after the selected value.
    return current_norm == desired_norm or desired_norm in current_norm


def fill_previous_worker(page, profile, company):
    worked_before = has_worked_for_company(profile, company)
    if worked_before is None:
        return False

    desired_bool = bool(worked_before)
    desired_text = "Yes" if desired_bool else "No"
    desired_values = {"true", "yes", "1"} if desired_bool else {"false", "no", "0"}

    for frame in page.frames:
        try:
            radios = frame.locator('input[name="candidateIsPreviousWorker"]')
        except Exception:
            continue

        for index in range(radios.count()):
            radio = radios.nth(index)
            try:
                value = normalize(radio.get_attribute("value"))
            except Exception:
                value = ""

            if value not in desired_values:
                continue

            try:
                if radio.is_checked():
                    print(f"ALREADY_SET            previous_worker        {desired_text}")
                    return True
            except Exception:
                pass

            radio_id = safe_attr(radio, "id")
            if radio_id:
                try:
                    label = frame.locator(f'label[for="{radio_id}"]')
                    if label.count() and label.first.is_visible():
                        label.first.click(timeout=3000)
                        print(f"ANSWERED               previous_worker        {desired_text}")
                        return True
                except Exception:
                    pass

            try:
                radio.click(timeout=3000, force=True)
                print(f"ANSWERED               previous_worker        {desired_text}")
                return True
            except Exception:
                pass

    return False


def fill_my_information(page, profile, company):
    fields = collect_fields(page)
    blockers = []
    handled = 0

    for field in fields:
        classification = classify_field(field)
        mode = classification.get("mode")
        category = classification.get("category")

        if category in {"navigation", "workday_utility"}:
            continue

        if category == "previous_worker":
            success = fill_previous_worker(page, profile, company)
            if success:
                handled += 1
            elif field.get("required"):
                blockers.append({
                    "category": category,
                    "label": field.get("label"),
                    "reason": "Could not safely answer previous-employer question.",
                })
            continue

        if mode == "PROFILE":
            if _profile_field_already_correct(profile, field, classification):
                print(f"ALREADY_SET            {category:24} {field.get('label')}")
                handled += 1
                continue

            try:
                result = fill_profile_field(profile, field, classification)
                status = result.get("status")
            except Exception as exc:
                status = "ERROR"
                result = {"error": str(exc)}

            print(f"{status:22} {category:24} {field.get('label')}")

            if status in {"FILLED", "SELECTED", "EMPTY_OPTIONAL_VALUE"}:
                handled += 1

            if field.get("required") and status not in {"FILLED", "SELECTED"}:
                blockers.append({
                    "category": category,
                    "label": field.get("label"),
                    "status": status,
                    "detail": result,
                })
            continue

        if field.get("required") and mode in {"MANUAL", "SPECIAL"}:
            blockers.append({
                "category": category,
                "label": field.get("label"),
                "reason": "Manual/special required field.",
            })
            continue

        if field.get("required") and mode == "IGNORE":
            label = normalize(field.get("label"))
            # Search inputs and Workday prompt internals are not application
            # questions, even when aria-required happens to be true.
            if label in {"search", "select one required", "select one"}:
                continue
            blockers.append({
                "category": category,
                "label": field.get("label"),
                "reason": "Unknown required field.",
            })

    return {
        "handled_count": handled,
        "blockers": blockers,
        "field_count": len(fields),
    }


def detect_resume_upload(page):
    results = []
    for frame_index, frame in enumerate(page.frames):
        try:
            inputs = frame.locator('input[type="file"]')
        except Exception:
            continue
        for index in range(inputs.count()):
            results.append((frame_index, index, inputs.nth(index)))
    return results


def upload_resume(page, resume_path):
    path = Path(resume_path)
    if not path.is_absolute():
        path = (ROOT / path).resolve()

    if not path.exists() or not path.is_file():
        print(f"\nRESUME FILE NOT FOUND: {path}")
        return False

    try:
        body = page.locator("body").inner_text(timeout=2000)
        if path.name.lower() in body.lower():
            print(f"ALREADY_SET            resume                  {path.name}")
            return True
    except Exception:
        pass

    uploads = detect_resume_upload(page)
    for frame_index, index, element in uploads:
        try:
            element.set_input_files(str(path))
            print(f"UPLOADED               resume                  {path.name}")
            page.wait_for_timeout(2500)
            return True
        except Exception as exc:
            print(f"Resume input frame={frame_index} index={index} failed: {exc}")

    return False


def manual_review_then_validate(page, title, blockers=None):
    print("\n" + "=" * 72)
    print(title)
    print("=" * 72)

    if blockers:
        print("\nThe agent will not guess these fields:")
        for blocker in blockers:
            print(" -", blocker)

    print(
        "\nComplete only the review-required fields in Chromium. "
        "Do not click Save and Continue yet."
    )
    input("Press ENTER here after those fields are complete...")

    errors = get_validation_errors(page)
    if errors:
        print("\nWorkday still reports required validation problems:")
        for error in errors:
            print(" -", error)
        return False

    return True


def click_continue_and_wait(page, old_step):
    button = find_continue_button(page)
    if button is None:
        print("\nNo Save and Continue / Next button found.")
        return None

    try:
        button.scroll_into_view_if_needed()
        page.wait_for_timeout(200)
        button.click(timeout=5000)
    except Exception as exc:
        print("\nCould not click Save and Continue:")
        print(exc)
        return None

    result = wait_for_step_change(page, old_step, timeout_ms=25000)
    if result.get("step") != old_step and result.get("step") != "unknown":
        print(f"\nSUCCESS: {old_step} -> {result.get('step')}")
        return result

    print("\nPAGE DID NOT ADVANCE.")
    for error in get_validation_errors(page):
        print(" -", error)
    return None


def handle_my_information(page, profile, company, step_number):
    # Workday sometimes paints the wizard shell before all inputs. Give this
    # page one short settling period if only prompt/search controls are visible.
    result = None
    for attempt in range(3):
        result = fill_my_information(page, profile, company)
        if result["handled_count"] > 0 or result["blockers"]:
            break
        page.wait_for_timeout(1200)

    save_evidence(page, step_number, "my_information", "after_fill")

    if result["blockers"]:
        print("\nMY INFORMATION BLOCKERS:")
        for blocker in result["blockers"]:
            print(" -", blocker)
        return False

    if result["handled_count"] == 0:
        print("\nMy Information was detected, but its application controls did not render.")
        print_visible_control_inventory(page)
        return False

    errors = get_validation_errors(page)
    if errors:
        print("\nMY INFORMATION VALIDATION:")
        for error in errors:
            print(" -", error)
        return False

    return True


def handle_experience(page, profile, step_number):
    if not upload_resume(page, RESUME_FILE):
        save_evidence(page, step_number, "my_experience", "resume_failed")
        return False

    page.wait_for_timeout(1500)
    result = fill_experience_and_education(page, profile)

    print("\nEXPERIENCE RESULT:")
    print(json.dumps(result, indent=2))
    save_evidence(page, step_number, "my_experience", "after_fill")

    return bool(result.get("ready_to_continue"))


def handle_application_questions_1(page, profile, step_number):
    result = fill_conflict_questions(page, profile)
    print("\nCONFLICT QUESTION RESULT:")
    print(json.dumps(result, indent=2))
    save_evidence(page, step_number, "application_questions_1", "after_fill")

    if result.get("ready"):
        return True

    return manual_review_then_validate(
        page,
        "APPLICATION QUESTIONS 1 — MANUAL REVIEW",
        [result],
    )


def handle_generic_application_page(page, profile, step_name, step_number):
    result = fill_generic_questions(page, profile)
    print(f"\n{step_name.upper()} RESULT:")
    print(json.dumps(result, indent=2))
    save_evidence(page, step_number, step_name, "after_fill")

    if result.get("ready"):
        return True

    return manual_review_then_validate(
        page,
        f"{step_name.upper()} — MANUAL REVIEW",
        result.get("blockers") or [],
    )


def handle_disclosure_page(page, profile, step_name, step_number):
    # Fill only high-confidence, non-sensitive answers first. Sensitive or legal
    # items remain manual. Optional unanswered demographic fields are allowed.
    result = fill_generic_questions(page, profile)
    save_evidence(page, step_number, step_name, "after_safe_fill")

    if result.get("blockers"):
        return manual_review_then_validate(
            page,
            f"{step_name.upper()} — MANUAL / VOLUNTARY REVIEW",
            result.get("blockers"),
        )

    errors = get_validation_errors(page)
    if errors:
        return manual_review_then_validate(
            page,
            f"{step_name.upper()} — REQUIRED REVIEW",
            errors,
        )

    return True


def main():
    if len(sys.argv) < 4:
        print(
            "\nUsage:\n"
            'python browser/workday_runner.py "JOB_URL" "COMPANY" "ROLE"'
        )
        sys.exit(1)

    url = sys.argv[1]
    company = sys.argv[2]
    role = sys.argv[3]

    profile = CandidateProfile("candidate_profile.yaml")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\nworkday_runner.py VERSION {VERSION}")

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE.resolve()),
            headless=False,
            viewport={"width": 1400, "height": 900},
        )

        page = get_live_page(context) if context.pages else context.new_page()

        print("\nOpening:")
        print(url)
        page.goto(url, wait_until="domcontentloaded", timeout=90000)

        print("\nJOB:")
        print(f"{company} - {role}")
        print(
            "\nNavigate manually into the saved Workday application. "
            "Complete login, CAPTCHA, MFA, and cookie consent yourself."
        )
        print("Stop when the actual application wizard is visible.")
        input("Then press ENTER here...")

        page = get_live_page(context)
        initial = wait_for_application_step(page, timeout_ms=30000)
        print("\nINITIAL WORKDAY STEP:")
        print(json.dumps(initial, indent=2))

        if initial.get("step") == "unknown":
            save_evidence(page, 0, "unknown", "initial")
            print("\nCould not determine the active Workday wizard step safely.")
            print_visible_control_inventory(page)
            input("\nPress ENTER to close...")
            context.close()
            return

        MAX_TRANSITIONS = 12

        for iteration in range(1, MAX_TRANSITIONS + 1):
            page = get_live_page(context)
            route = wait_for_application_step(page, timeout_ms=12000)
            step = route.get("step", "unknown")

            print("\n" + "=" * 78)
            print(f"WORKDAY PASS {iteration}: {step}")
            print("=" * 78)
            print("Evidence:", route.get("evidence"))
            print("URL:", page.url)

            save_evidence(page, iteration, step, "before")

            if step == "review" or find_submit_button(page) is not None:
                print("\n=================================")
                print("FINAL REVIEW PAGE REACHED")
                print("=================================")
                print(
                    "The agent intentionally did NOT click Submit. "
                    "Review the complete application and submit manually."
                )
                save_evidence(page, iteration, "review", "final")
                input("\nPress ENTER to close...")
                context.close()
                return

            if step == "my_information":
                ready = handle_my_information(page, profile, company, iteration)

            elif step == "my_experience":
                ready = handle_experience(page, profile, iteration)

            elif step == "application_questions_1":
                ready = handle_application_questions_1(page, profile, iteration)

            elif step == "application_questions_2":
                ready = handle_generic_application_page(
                    page, profile, step, iteration
                )

            elif step in {"voluntary_disclosures", "self_identify"}:
                ready = handle_disclosure_page(
                    page, profile, step, iteration
                )

            else:
                print("\nUNHANDLED / UNKNOWN WORKDAY STEP")
                print_visible_control_inventory(page)
                input("\nPress ENTER to close...")
                context.close()
                return

            if not ready:
                save_evidence(page, iteration, step, "stopped")
                print(f"\n{step} is not ready to advance safely.")
                print_visible_control_inventory(page)
                input("\nPress ENTER to close...")
                context.close()
                return

            errors = get_validation_errors(page)
            if errors:
                print("\nRequired validation problems remain:")
                for error in errors:
                    print(" -", error)
                save_evidence(page, iteration, step, "validation")
                input("\nFix the fields in Chromium, then press ENTER to close...")
                context.close()
                return

            advanced = click_continue_and_wait(page, step)
            if not advanced:
                save_evidence(page, iteration, step, "stuck")
                input("\nInspect Chromium. Press ENTER to close...")
                context.close()
                return

        print("\nMaximum Workday transition limit reached safely.")
        context.close()


if __name__ == "__main__":
    main()
