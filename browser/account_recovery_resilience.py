from __future__ import annotations

from browser import account_manager as account_manager
from credentials.store import delete_password


_ORIGINAL_HANDLE_ACCOUNT_PAGE = account_manager.handle_account_page
_INSTALLED = False

RESET_SUBMIT_NAMES = (
    "Activate",
    "Activate Password",
    "Activate password",
    "Activate Account",
    "Activate account",
    "Update Password",
    "Update password",
    "Reset Password",
    "Reset password",
    "Set Password",
    "Set password",
    "Change Password",
    "Change password",
    "Save Password",
    "Save password",
    "Save",
    "Continue",
    "Submit",
)

RECOVERY_NAMES = (
    "Forgot Password",
    "Forgot password",
    "Forgot your password",
    "Forgot your password?",
    "Reset Password",
    "Reset password",
    "Password help",
    "Trouble signing in",
)


def _visible_enabled(item) -> bool:
    try:
        return item.is_visible() and item.is_enabled()
    except Exception:
        return False


def _button_or_link(page, names):
    for frame in page.frames:
        for name in names:
            for role in ("button", "link"):
                try:
                    items = frame.get_by_role(role, name=name, exact=False)
                except Exception:
                    continue
                for index in range(items.count()):
                    item = items.nth(index)
                    if _visible_enabled(item):
                        return item
    return None


def _password_form_submit(page):
    """Find the submit control belonging to a visible password form.

    Avature password-activation pages sometimes render an input[type=submit]
    whose visible label is simply "Activate". Other ATS portals use a normal
    submit button without one of the account-manager's named labels.
    """
    named = _button_or_link(page, RESET_SUBMIT_NAMES)
    if named is not None:
        return named

    for frame in page.frames:
        try:
            passwords = frame.locator('input[type="password"]')
        except Exception:
            continue

        for index in range(passwords.count()):
            password = passwords.nth(index)
            try:
                if not password.is_visible():
                    continue
                form = password.locator("xpath=ancestor::form[1]")
                if not form.count():
                    continue
                controls = form.first.locator(
                    'button[type="submit"], input[type="submit"], input[type="button"]'
                )
            except Exception:
                continue

            for control_index in range(controls.count()):
                control = controls.nth(control_index)
                if _visible_enabled(control):
                    return control

    # Last conservative fallback: explicit submit controls anywhere on a page
    # already classified as reset_password by the main account manager.
    for frame in page.frames:
        try:
            controls = frame.locator('button[type="submit"], input[type="submit"]')
        except Exception:
            continue
        for index in range(controls.count()):
            control = controls.nth(index)
            if _visible_enabled(control):
                return control
    return None


def _blocker_contains(result, category: str, text: str) -> bool:
    needle = str(text or "").lower()
    for blocker in getattr(result, "blockers", None) or []:
        if not isinstance(blocker, dict):
            continue
        if str(blocker.get("category") or "") != category:
            continue
        reason = str(blocker.get("reason") or "").lower()
        if needle in reason:
            return True
    return False


def _retry_reset_submit(page, profile, result, allow_create, allow_sign_in):
    if getattr(result, "state", "") != "reset_password":
        return None
    if not _blocker_contains(result, "credential_recovery", "submit control was not found"):
        return None

    submit = _password_form_submit(page)
    if submit is None:
        return None

    try:
        submit.click(timeout=5000)
        page.wait_for_timeout(1200)
    except Exception:
        return None

    return _ORIGINAL_HANDLE_ACCOUNT_PAGE(
        page,
        profile,
        allow_create=allow_create,
        allow_sign_in=allow_sign_in,
    )


def _recover_stale_credential(page, profile, result, allow_create, allow_sign_in):
    if getattr(result, "state", "") != "sign_in":
        return None
    if not _blocker_contains(result, "credential", "stored credential was rejected"):
        return None

    email = str(profile.get("candidate.email", "") or "").strip()
    if not email:
        return None

    recovery = _button_or_link(page, RECOVERY_NAMES)
    if recovery is None:
        return None

    # A password generated before an unsuccessful activation must never trap
    # later runs in an endless invalid-sign-in loop.
    try:
        delete_password(account_manager.site_key(page.url), email)
    except Exception:
        pass

    try:
        recovery.click(timeout=5000)
        page.wait_for_timeout(1000)
    except Exception:
        return None

    return _ORIGINAL_HANDLE_ACCOUNT_PAGE(
        page,
        profile,
        allow_create=allow_create,
        allow_sign_in=allow_sign_in,
    )


def resilient_handle_account_page(
    page,
    profile,
    allow_create: bool = True,
    allow_sign_in: bool = True,
    **kwargs,
):
    """Wrap the core account manager with live-ATS recovery fallbacks.

    The core manager remains authoritative. This layer only handles two observed
    production edge cases: Avature-style password activation buttons and stale
    OS-keyring credentials left by an interrupted password activation.
    """
    result = _ORIGINAL_HANDLE_ACCOUNT_PAGE(
        page,
        profile,
        allow_create=allow_create,
        allow_sign_in=allow_sign_in,
        **kwargs,
    )

    retried = _retry_reset_submit(
        page,
        profile,
        result,
        allow_create,
        allow_sign_in,
    )
    if retried is not None:
        return retried

    recovered = _recover_stale_credential(
        page,
        profile,
        result,
        allow_create,
        allow_sign_in,
    )
    return recovered if recovered is not None else result


def install_account_recovery_resilience() -> None:
    global _INSTALLED
    if _INSTALLED:
        return
    account_manager.handle_account_page = resilient_handle_account_page
    _INSTALLED = True
