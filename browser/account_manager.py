from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List
from urllib.parse import urlparse

from credentials.store import get_or_create_password, get_password


@dataclass
class AccountResult:
    state: str
    ready: bool = False
    verification_required: bool = False
    message: str = ""
    blockers: List[Dict] = field(default_factory=list)
    metadata: Dict = field(default_factory=dict)


def _norm(value) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _visible(locator) -> bool:
    try:
        return locator.is_visible()
    except Exception:
        return False


def _visible_text(page) -> str:
    parts = []
    for frame in page.frames:
        try:
            body = frame.locator("body")
            if body.count() and body.first.is_visible():
                parts.append(body.first.inner_text(timeout=1000))
        except Exception:
            continue
    return "\n".join(parts)


def _first_visible(page, selectors):
    for frame in page.frames:
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


def _button(page, names):
    for frame in page.frames:
        for name in names:
            try:
                items = frame.get_by_role("button", name=name, exact=False)
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


def site_key(url: str) -> str:
    parsed = urlparse(url or "")
    host = parsed.netloc.lower() or "unknown"
    path = [part for part in parsed.path.split("/") if part]

    if "myworkdayjobs.com" in host and path:
        return f"{host}/{path[0]}"
    return host


def detect_account_state(page) -> str:
    text = _norm(_visible_text(page))

    verification_markers = (
        "verification code",
        "one-time code",
        "one time code",
        "enter code",
        "verify your email",
        "email verification",
        "multi-factor",
        "multifactor",
        "captcha",
        "security code",
    )
    if any(marker in text for marker in verification_markers):
        return "verification_required"

    password = _first_visible(page, ['input[type="password"]'])
    confirm = _first_visible(
        page,
        [
            'input[name*="confirm" i][type="password"]',
            'input[id*="confirm" i][type="password"]',
            'input[aria-label*="confirm" i][type="password"]',
        ],
    )

    create = _button(page, ["Create Account", "Create account", "Register", "Sign Up", "Sign up"])
    sign_in = _button(page, ["Sign In", "Sign in", "Log In", "Log in", "Login"])

    if password is not None and (confirm is not None or create is not None):
        return "create_account"
    if password is not None and sign_in is not None:
        return "sign_in"

    if any(
        marker in text
        for marker in (
            "my information",
            "my experience",
            "application questions",
            "submit application",
            "resume/cv",
        )
    ):
        return "authenticated"

    return "unknown"


def _fill_email(page, email: str) -> bool:
    element = _first_visible(
        page,
        [
            'input[type="email"]',
            'input[name*="email" i]',
            'input[id*="email" i]',
            'input[autocomplete="email"]',
            'input[autocomplete="username"]',
        ],
    )
    if element is None:
        return False
    try:
        current = element.input_value(timeout=500).strip()
    except Exception:
        current = ""
    if current:
        return True
    try:
        element.fill(email)
        return True
    except Exception:
        return False


def _password_fields(page):
    fields = []
    for frame in page.frames:
        try:
            items = frame.locator('input[type="password"]')
        except Exception:
            continue
        for index in range(items.count()):
            item = items.nth(index)
            if _visible(item):
                fields.append(item)
    return fields


def _required_unhandled_checkboxes(page):
    blockers = []
    for frame in page.frames:
        try:
            boxes = frame.locator('input[type="checkbox"]')
        except Exception:
            continue
        for index in range(boxes.count()):
            box = boxes.nth(index)
            if not _visible(box):
                continue
            try:
                required = (
                    box.get_attribute("required") is not None
                    or _norm(box.get_attribute("aria-required")) == "true"
                )
                checked = box.is_checked()
            except Exception:
                continue
            if required and not checked:
                try:
                    label = box.get_attribute("aria-label") or box.get_attribute("name") or "required checkbox"
                except Exception:
                    label = "required checkbox"
                blockers.append({
                    "category": "account_terms_or_checkbox",
                    "label": label,
                    "reason": "Required checkbox must be reviewed by the user.",
                })
    return blockers


def handle_account_page(
    page,
    profile,
    allow_create: bool = True,
    allow_sign_in: bool = True,
) -> AccountResult:
    state = detect_account_state(page)
    email = str(profile.get("candidate.email", "") or "").strip()
    key = site_key(page.url)

    if state == "authenticated":
        return AccountResult(state=state, ready=True, message="Application page is already authenticated.")

    if state == "verification_required":
        return AccountResult(
            state=state,
            verification_required=True,
            message=(
                "CAPTCHA/MFA/email verification requires user action. "
                "Complete it in the browser, then resume the agent."
            ),
        )

    if not email:
        return AccountResult(
            state=state,
            blockers=[{"category": "email", "reason": "candidate.email is missing"}],
            message="Candidate email is required for ATS account handling.",
        )

    if state == "sign_in":
        if not allow_sign_in:
            return AccountResult(state=state, message="Automatic sign-in is disabled.")

        password = get_password(key, email)
        if not password:
            return AccountResult(
                state=state,
                blockers=[{
                    "category": "credential",
                    "reason": "No password is stored in the OS keyring for this ATS tenant.",
                }],
                message="Existing account detected but no stored credential is available.",
            )

        email_ok = _fill_email(page, email)
        passwords = _password_fields(page)
        if not email_ok or not passwords:
            return AccountResult(state=state, message="Could not locate sign-in controls safely.")

        try:
            passwords[0].fill(password)
        except Exception:
            return AccountResult(state=state, message="Could not fill the stored password.")

        button = _button(page, ["Sign In", "Sign in", "Log In", "Log in", "Login"])
        if button is None:
            return AccountResult(state=state, message="Sign-in button was not found.")

        try:
            button.click(timeout=5000)
            page.wait_for_timeout(900)
        except Exception as exc:
            return AccountResult(state=state, message=f"Sign-in click failed: {exc}")

        next_state = detect_account_state(page)
        return AccountResult(
            state=next_state,
            ready=next_state == "authenticated",
            verification_required=next_state == "verification_required",
            message="Sign-in submitted using the OS-keyring credential.",
        )

    if state == "create_account":
        if not allow_create:
            return AccountResult(state=state, message="Automatic account creation is disabled.")

        blockers = _required_unhandled_checkboxes(page)
        if blockers:
            return AccountResult(
                state=state,
                blockers=blockers,
                message="Account creation has a required checkbox/terms field that must be reviewed.",
            )

        email_ok = _fill_email(page, email)
        passwords = _password_fields(page)
        if not email_ok or not passwords:
            return AccountResult(state=state, message="Could not locate account creation fields safely.")

        password = get_or_create_password(key, email)
        try:
            passwords[0].fill(password)
            if len(passwords) > 1:
                passwords[1].fill(password)
        except Exception:
            return AccountResult(state=state, message="Could not fill generated account password.")

        button = _button(page, ["Create Account", "Create account", "Register", "Sign Up", "Sign up"])
        if button is None:
            return AccountResult(
                state=state,
                ready=False,
                message="Account fields are filled, but the create-account button was not found.",
                metadata={"credential_source": "os_keyring"},
            )

        try:
            button.click(timeout=5000)
            page.wait_for_timeout(900)
        except Exception as exc:
            return AccountResult(
                state=state,
                message=f"Create-account click failed: {exc}",
                metadata={"credential_source": "os_keyring"},
            )

        next_state = detect_account_state(page)
        return AccountResult(
            state=next_state,
            ready=next_state == "authenticated",
            verification_required=next_state == "verification_required",
            message=(
                "Account creation submitted. Password is stored only in the OS keyring; "
                "the agent does not log it."
            ),
            metadata={"credential_source": "os_keyring"},
        )

    return AccountResult(
        state="unknown",
        ready=False,
        message="No supported sign-in/create-account/application state was detected.",
    )
