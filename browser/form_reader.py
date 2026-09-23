import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


VERSION = "2.1-workday"
OUTPUT = Path("data/last_form.json")


def clean(value):
    if value is None:
        return None

    value = " ".join(str(value).split())

    return value if value else None


def get_label(frame, element):
    # aria-label
    try:
        value = element.get_attribute("aria-label")
        if value:
            return clean(value)
    except Exception:
        pass

    # aria-labelledby
    try:
        ids = element.get_attribute("aria-labelledby")

        if ids:
            texts = []

            for label_id in ids.split():
                target = frame.locator(f"#{label_id}")

                if target.count():
                    try:
                        text = clean(target.first.inner_text(timeout=1000))

                        if text:
                            texts.append(text)
                    except Exception:
                        pass

            if texts:
                return " ".join(texts)

    except Exception:
        pass

    # normal <label for="">
    try:
        element_id = element.get_attribute("id")

        if element_id:
            labels = frame.locator(
                f'label[for="{element_id}"]'
            )

            if labels.count():
                text = clean(
                    labels.first.inner_text(timeout=1000)
                )

                if text:
                    return text

    except Exception:
        pass

    # placeholder
    try:
        placeholder = element.get_attribute("placeholder")

        if placeholder:
            return clean(placeholder)

    except Exception:
        pass

    # nearest readable container
    try:
        text = element.evaluate(
            """
            el => {
                let node = el;

                for (let i = 0; i < 5 && node; i++) {
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

        if text:
            return clean(text)

    except Exception:
        pass

    # name fallback
    try:
        name = element.get_attribute("name")

        if name:
            return clean(name)

    except Exception:
        pass

    return "UNKNOWN_FIELD"


def read_frame(frame, frame_index):

    selectors = [
        'input:not([type="hidden"])',
        "textarea",
        "select",

        '[role="textbox"]',
        '[role="combobox"]',
        '[role="checkbox"]',
        '[role="radio"]',

        'button[aria-haspopup]',
        '[aria-haspopup="listbox"]',
        '[aria-haspopup="menu"]',

        'button[data-automation-id]',
    ]

    fields = []

    seen = set()

    for selector in selectors:

        try:
            locator = frame.locator(selector)
            count = locator.count()

        except Exception:
            continue

        for i in range(count):

            element = locator.nth(i)

            try:
                if not element.is_visible():
                    continue

                tag = element.evaluate(
                    "el => el.tagName.toLowerCase()"
                )

                element_id = element.get_attribute("id")
                name = element.get_attribute("name")
                role = element.get_attribute("role")
                input_type = element.get_attribute("type")

                identity = (
                    frame_index,
                    element_id,
                    name,
                    role,
                    input_type,
                    tag,
                )

                if identity in seen:
                    continue

                seen.add(identity)

                field = {
                    "frame": frame_index,
                    "selector_source": selector,
                    "tag": tag,
                    "type": input_type or role or tag,
                    "role": role,
                    "id": element_id,
                    "name": name,
                    "label": get_label(
                        frame,
                        element
                    ),

                    "aria_haspopup":
                        element.get_attribute("aria-haspopup"),

                    "aria_expanded":
                        element.get_attribute("aria-expanded"),

                    "data_automation_id":
                        element.get_attribute("data-automation-id"),

                    "required": (
                        element.get_attribute("required")
                        is not None
                        or
                        element.get_attribute("aria-required")
                        == "true"
                    ),
                }

                # current value
                try:
                    if tag in {
                        "input",
                        "textarea",
                        "select",
                    }:
                        field["value"] = element.input_value()
                    else:
                        field["value"] = (
                            element.get_attribute(
                                "aria-valuetext"
                            )
                            or
                            element.get_attribute(
                                "aria-checked"
                            )
                        )
                except Exception:
                    field["value"] = None

                # dropdown options
                if tag == "select":
                    options = []

                    option_elements = element.locator(
                        "option"
                    )

                    for j in range(
                        option_elements.count()
                    ):
                        option = option_elements.nth(j)

                        options.append(
                            {
                                "text": clean(
                                    option.inner_text()
                                ),
                                "value":
                                    option.get_attribute(
                                        "value"
                                    ),
                            }
                        )

                    field["options"] = options

                fields.append(field)

            except Exception as exc:
                fields.append(
                    {
                        "frame": frame_index,
                        "selector_source": selector,
                        "error": str(exc),
                    }
                )

    return fields


def get_live_page(context):
    pages = [
        page
        for page in context.pages
        if not page.is_closed()
    ]

    if not pages:
        raise RuntimeError(
            "No browser tab is currently open."
        )

    return pages[-1]


def main():

    print(f"\nFORM READER VERSION: {VERSION}")

    if len(sys.argv) < 2:
        print(
            '\nUsage:\n'
            'python browser/form_reader.py '
            '"JOB_URL"'
        )
        sys.exit(1)

    url = sys.argv[1]

    OUTPUT.parent.mkdir(
        parents=True,
        exist_ok=True
    )

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=False
        )

        context = browser.new_context(
            viewport={
                "width": 1440,
                "height": 950,
            }
        )

        page = context.new_page()

        print("\nOpening:")
        print(url)

        page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=90000,
        )

        print(
            "\nUse the Chromium window manually."
        )

        print(
            "1. Click Apply"
            "\n2. Sign in if needed"
            "\n3. Continue until you see real application fields"
            "\n4. Do NOT close Chromium"
        )

        input(
            "\nWhen fields such as Name / Address / Phone "
            "are visible, come back here and press ENTER..."
        )

        page = get_live_page(context)

        print("\nACTIVE PAGE")
        print(page.url)

        print("\nTITLE")
        print(page.title())

        page.wait_for_timeout(3000)

        print(
            f"\nPages open: {len(context.pages)}"
        )

        print(
            f"Frames on active page: {len(page.frames)}"
        )

        all_fields = []

        for index, frame in enumerate(page.frames):

            try:
                print(
                    f"\nScanning frame {index}: "
                    f"{frame.url[:150]}"
                )

                fields = read_frame(
                    frame,
                    index
                )

                print(
                    f"  -> {len(fields)} controls"
                )

                all_fields.extend(fields)

            except Exception as exc:
                print(
                    f"  -> frame error: {exc}"
                )

        result = {
            "reader_version": VERSION,
            "url": page.url,
            "title": page.title(),
            "frames": len(page.frames),
            "field_count": len(all_fields),
            "fields": all_fields,
        }

        print("\n" + "=" * 80)
        print("FORM FIELDS FOUND")
        print("=" * 80)

        print(
            json.dumps(
                all_fields,
                indent=2,
                ensure_ascii=False,
            )
        )

        with OUTPUT.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                result,
                file,
                indent=2,
                ensure_ascii=False,
            )

        print(
            f"\nTotal fields: {len(all_fields)}"
        )

        print(
            f"Saved: {OUTPUT}"
        )

        input(
            "\nPress ENTER to close Chromium..."
        )


if __name__ == "__main__":
    main()