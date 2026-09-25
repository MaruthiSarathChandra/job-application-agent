from __future__ import annotations

import base64
import hashlib
import html
import re
import time
from dataclasses import dataclass
from email.utils import parseaddr
from pathlib import Path
from typing import Iterable, List
from urllib.parse import urlparse


SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
OTP_RE = re.compile(
    r"(?i)(?:verification|security|one[- ]?time|otp|code)[^0-9]{0,40}([0-9]{4,8})"
)
FALLBACK_OTP_RE = re.compile(r"(?<!\d)([0-9]{6})(?!\d)")
LINK_RE = re.compile(r'https://[^\s<>"\']+')
VERIFICATION_WORDS = (
    "verification",
    "verify",
    "one-time",
    "one time",
    "security code",
    "confirmation",
    "confirm your email",
    "reset password",
    "password reset",
)


@dataclass
class VerificationAttempt:
    attempted: bool = False
    completed: bool = False
    method: str = ""
    reason: str = ""


def _norm(value) -> str:
    return " ".join(str(value or "").strip().lower().split())


def extract_verification_code(text: str) -> str:
    value = html.unescape(str(text or ""))
    match = OTP_RE.search(value)
    if match:
        return match.group(1)
    match = FALLBACK_OTP_RE.search(value)
    return match.group(1) if match else ""


def extract_https_links(text: str) -> List[str]:
    value = html.unescape(str(text or ""))
    links = []
    seen = set()
    for match in LINK_RE.findall(value):
        link = match.rstrip(".,;)]}'\"")
        if link in seen:
            continue
        seen.add(link)
        links.append(link)
    return links


def _host_matches(candidate: str, expected: str) -> bool:
    candidate = (candidate or "").lower().strip(".")
    expected = (expected or "").lower().strip(".")
    if not candidate or not expected:
        return False
    return candidate == expected or candidate.endswith("." + expected) or expected.endswith("." + candidate)


def trusted_verification_link(link: str, current_url: str, extra_domains: Iterable[str] = ()) -> bool:
    try:
        link_host = urlparse(link).netloc.lower()
        current_host = urlparse(current_url).netloc.lower()
    except Exception:
        return False
    if not link_host or not current_host:
        return False

    if _host_matches(link_host, current_host):
        return True

    known_families = (
        "myworkdayjobs.com",
        "workdayjobs.com",
        "greenhouse.io",
        "lever.co",
        "brassring.com",
        "avature.net",
    )
    for family in known_families:
        if family in current_host and family in link_host:
            return True

    for domain in extra_domains or ():
        if _host_matches(link_host, str(domain)):
            return True
    return False


def _decode_part(data: str) -> str:
    if not data:
        return ""
    try:
        padded = data + "=" * (-len(data) % 4)
        return base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8", errors="ignore")
    except Exception:
        return ""


def _message_text(payload) -> str:
    parts = []

    def walk(node):
        if not isinstance(node, dict):
            return
        body = node.get("body") or {}
        data = body.get("data")
        if data:
            parts.append(_decode_part(data))
        for child in node.get("parts") or []:
            walk(child)

    walk(payload or {})
    return "\n".join(parts)


def _headers(payload) -> dict:
    result = {}
    for item in (payload or {}).get("headers") or []:
        name = str(item.get("name") or "").lower()
        if name:
            result[name] = str(item.get("value") or "")
    return result


def _gmail_service(profile, email: str):
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except Exception as exc:
        raise RuntimeError(
            "Gmail API dependencies are not installed. Run pip install -r requirements.txt."
        ) from exc

    client_file = Path(
        str(
            profile.get(
                "email_verification.gmail.client_secret_file",
                "secrets/gmail_oauth_client.json",
            )
            or "secrets/gmail_oauth_client.json"
        )
    )
    token_dir = Path(
        str(profile.get("email_verification.gmail.token_dir", "data/gmail_tokens") or "data/gmail_tokens")
    )
    if not client_file.exists():
        raise FileNotFoundError(
            f"Gmail OAuth client file not found: {client_file}. "
            "Keep it local; it must never be committed."
        )

    token_dir.mkdir(parents=True, exist_ok=True)
    token_name = hashlib.sha256(email.lower().encode("utf-8")).hexdigest()[:20] + ".json"
    token_file = token_dir / token_name

    creds = None
    if token_file.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)
        except Exception:
            creds = None

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file(str(client_file), SCOPES)
        creds = flow.run_local_server(port=0, prompt="consent")

    token_file.write_text(creds.to_json(), encoding="utf-8")
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    profile_data = service.users().getProfile(userId="me").execute()
    authorized_email = str(profile_data.get("emailAddress") or "").lower()
    if authorized_email != email.lower():
        raise RuntimeError(
            "The Gmail OAuth account does not match candidate.email for this profile. "
            "Authorize the correct mailbox."
        )
    return service


def _candidate_messages(service, current_url: str, timeout_seconds: int):
    started = time.time()
    current_host = urlparse(current_url or "").netloc.lower()
    host_tokens = [token for token in re.split(r"[.-]", current_host) if len(token) >= 4]

    while time.time() - started < timeout_seconds:
        response = service.users().messages().list(
            userId="me",
            q="newer_than:15m",
            maxResults=20,
        ).execute()
        for item in response.get("messages") or []:
            message = service.users().messages().get(
                userId="me",
                id=item["id"],
                format="full",
            ).execute()
            payload = message.get("payload") or {}
            headers = _headers(payload)
            subject = headers.get("subject", "")
            sender = parseaddr(headers.get("from", ""))[1]
            body = _message_text(payload)
            combined = f"{subject}\n{sender}\n{body}"
            normalized = _norm(combined)
            if not any(word in normalized for word in VERIFICATION_WORDS):
                continue
            if host_tokens and not any(token in normalized for token in host_tokens):
                # ATS email can be sent by a vendor domain, so host matching is
                # a preference rather than a hard rejection.
                pass
            yield combined
        time.sleep(3)


def _first_visible(page, selectors):
    for frame in page.frames:
        for selector in selectors:
            try:
                items = frame.locator(selector)
            except Exception:
                continue
            for index in range(items.count()):
                item = items.nth(index)
                try:
                    if item.is_visible():
                        return item
                except Exception:
                    continue
    return None


def _verification_control(page):
    selectors = (
        'input[autocomplete="one-time-code"]',
        'input[name*="otp" i]',
        'input[id*="otp" i]',
        'input[name*="code" i]',
        'input[id*="code" i]',
        'input[aria-label*="code" i]',
    )
    return _first_visible(page, selectors)


def _click_verify(page) -> bool:
    for frame in page.frames:
        for name in ("Verify", "Confirm", "Continue", "Next", "Submit Code", "Submit code"):
            for role in ("button", "link"):
                try:
                    items = frame.get_by_role(role, name=name, exact=False)
                except Exception:
                    continue
                for index in range(items.count()):
                    item = items.nth(index)
                    try:
                        if item.is_visible() and item.is_enabled():
                            item.click(timeout=5000)
                            page.wait_for_timeout(1000)
                            return True
                    except Exception:
                        continue
    return False


def try_complete_email_verification(page, profile, email: str) -> VerificationAttempt:
    mode = _norm(profile.get("email_verification.mode", "manual"))
    if mode != "gmail_api":
        return VerificationAttempt(attempted=False, completed=False, reason="manual_mode")

    # CAPTCHA and non-email MFA are intentionally never bypassed.
    try:
        text = _norm(page.locator("body").inner_text(timeout=700))
    except Exception:
        text = ""
    if "captcha" in text or "authenticator app" in text or "text message" in text or "sms" in text:
        return VerificationAttempt(attempted=False, completed=False, reason="non_email_verification")

    try:
        service = _gmail_service(profile, email)
    except Exception as exc:
        return VerificationAttempt(attempted=True, completed=False, reason=str(exc))

    timeout_seconds = int(profile.get("email_verification.gmail.poll_seconds", 60) or 60)
    trusted_domains = profile.get("email_verification.gmail.trusted_link_domains", []) or []
    code_control = _verification_control(page)

    for message_text in _candidate_messages(service, page.url, timeout_seconds):
        if code_control is not None:
            code = extract_verification_code(message_text)
            if code:
                try:
                    code_control.fill(code)
                    if _click_verify(page):
                        return VerificationAttempt(attempted=True, completed=True, method="gmail_code")
                except Exception:
                    pass

        for link in extract_https_links(message_text):
            if not trusted_verification_link(link, page.url, trusted_domains):
                continue
            try:
                # Keep verification in the active application page so the account
                # state machine continues from the verified/reset-password page
                # instead of being stranded on the old tab.
                page.goto(link, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(1200)
                return VerificationAttempt(attempted=True, completed=True, method="gmail_link")
            except Exception:
                continue

    return VerificationAttempt(attempted=True, completed=False, reason="no_matching_email_verification_found")
