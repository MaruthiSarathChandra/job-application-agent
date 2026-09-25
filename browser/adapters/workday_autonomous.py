from __future__ import annotations

from browser.account_manager import (
    detect_account_state,
    handle_account_page,
    site_key,
)
from browser.workday_entry import advance_workday_entry, visible_entry_actions
from browser.workday_router import wait_for_application_step
from credentials.store import get_password

from .base import AdapterResult, ApplicationContext
from .workday import WorkdayAdapter


MAX_ENTRY_TRANSITIONS = 10


def _visible_action(page, names):
    for frame in page.frames:
        for name in names:
            for role in ("button", "link"):
                try:
                    items = frame.get_by_role(role, name=name, exact=False)
                except Exception:
                    continue
                for index in range(items.count()):
                    item = items.nth(index)
                    try:
                        if item.is_visible() and item.is_enabled():
                            return item, name
                    except Exception:
                        continue
    return None, ""


def _click(item) -> bool:
    if item is None:
        return False
    try:
        item.scroll_into_view_if_needed(timeout=1500)
    except Exception:
        pass
    try:
        item.click(timeout=5000)
        return True
    except Exception:
        try:
            item.click(force=True, timeout=3500)
            return True
        except Exception:
            return False


def _advance_account_gateway(page, profile) -> str:
    """
    Workday can show a button-only Sign In / Create Account gateway before any
    email/password inputs exist. account_manager intentionally waits for real
    form controls, so this function advances that one safe navigation layer.
    """
    email = str(profile.get("candidate.email", "") or "").strip()
    stored = get_password(site_key(page.url), email) if email else None

    if stored:
        order = (
            ("sign_in", ("Sign In", "Sign in", "Log In", "Log in")),
            ("create_account", ("Create Account", "Create account", "Register")),
        )
    else:
        order = (
            ("create_account", ("Create Account", "Create account", "Register")),
            ("sign_in", ("Sign In", "Sign in", "Log In", "Log in")),
        )

    for action, names in order:
        item, _name = _visible_action(page, names)
        if item is None:
            continue
        if _click(item):
            try:
                page.wait_for_timeout(900)
            except Exception:
                pass
            return action
    return ""


class AutonomousWorkdayAdapter(WorkdayAdapter):
    """
    Workday adapter with an unattended pre-wizard state machine.

    A direct /job/... URL may lead through several tenant-specific layers:
      application method -> sign-in/create-account gateway -> account flow ->
      application wizard.

    The base WorkdayAdapter starts at the wizard. This wrapper owns the layers
    before it so an unattended run does not require the user to manually click
    Apply Manually/Create Account just to expose My Information.
    """

    def run(self, page, profile, context: ApplicationContext) -> AdapterResult:
        resume_current = bool(context.metadata.get("resume_current_page"))

        if not resume_current:
            page.goto(
                self._apply_url(context.job.url),
                wait_until="domcontentloaded",
                timeout=90000,
            )
            page.wait_for_timeout(1100)

        last_account_state = "unknown"
        last_action = ""

        for _transition in range(MAX_ENTRY_TRANSITIONS):
            route = wait_for_application_step(page, timeout_ms=2500)
            if route.get("step") != "unknown":
                # Prevent the base adapter from navigating back to /apply. It can
                # now own the normal Workday wizard from this exact live page.
                context.metadata["resume_current_page"] = True
                return super().run(page, profile, context)

            entry = advance_workday_entry(page, context.resume_path)
            if entry.clicked:
                last_action = f"entry:{entry.action}"
                print(f"WORKDAY_ENTRY          {entry.action}")
                continue

            state = detect_account_state(page)
            last_account_state = state
            if state != "unknown":
                account = handle_account_page(page, profile)
                last_account_state = account.state

                if account.verification_required:
                    return AdapterResult(
                        status="verification_required",
                        review_required=True,
                        message=account.message,
                        blockers=[{
                            "category": "verification",
                            "reason": (
                                "Unattended verification could not be completed by the configured verifier."
                            ),
                        }],
                        metadata={
                            "account_state": account.state,
                            **(account.metadata or {}),
                        },
                    )

                if account.blockers:
                    return AdapterResult(
                        status="account_review",
                        review_required=True,
                        message=account.message,
                        blockers=account.blockers,
                        metadata={
                            "account_state": account.state,
                            **(account.metadata or {}),
                        },
                    )

                if account.ready:
                    last_action = f"account:{account.state}"
                    try:
                        page.wait_for_timeout(800)
                    except Exception:
                        pass
                    continue

            gateway = _advance_account_gateway(page, profile)
            if gateway:
                last_action = f"gateway:{gateway}"
                print(f"WORKDAY_GATEWAY        {gateway}")
                continue

            # Give lazy Workday shells one final chance to paint controls before
            # declaring a real routing gap.
            try:
                page.wait_for_timeout(1200)
            except Exception:
                pass
            route = wait_for_application_step(page, timeout_ms=2500)
            if route.get("step") != "unknown":
                context.metadata["resume_current_page"] = True
                return super().run(page, profile, context)
            break

        return AdapterResult(
            status="review",
            review_required=True,
            submitted=False,
            message="Workday pre-application flow could not reach the application wizard unattended.",
            blockers=[{
                "category": "routing",
                "reason": "Pre-wizard entry/account state did not advance to an identifiable Workday step.",
                "account_state": last_account_state,
                "last_action": last_action,
                "visible_actions": visible_entry_actions(page),
                "url": getattr(page, "url", ""),
            }],
            metadata={
                "account_state": last_account_state,
                "workday_entry_last_action": last_action,
            },
        )
