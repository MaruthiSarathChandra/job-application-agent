import secrets
import string
from typing import Optional

import keyring


SERVICE_PREFIX = "job-application-agent"


def _service(site: str) -> str:
    clean = (site or "unknown").strip().lower()
    return f"{SERVICE_PREFIX}:{clean}"


def generate_password(length: int = 20) -> str:
    if length < 16:
        length = 16

    alphabet = string.ascii_letters + string.digits + "!@#$%^&*_-+"

    # Ensure a reasonable mix for common ATS password policies.
    required = [
        secrets.choice(string.ascii_lowercase),
        secrets.choice(string.ascii_uppercase),
        secrets.choice(string.digits),
        secrets.choice("!@#$%^&*_-+"),
    ]
    required.extend(secrets.choice(alphabet) for _ in range(length - len(required)))
    secrets.SystemRandom().shuffle(required)
    return "".join(required)


def get_password(site: str, email: str) -> Optional[str]:
    return keyring.get_password(_service(site), email)


def store_password(site: str, email: str, password: str) -> None:
    keyring.set_password(_service(site), email, password)


def get_or_create_password(site: str, email: str) -> str:
    existing = get_password(site, email)
    if existing:
        return existing

    password = generate_password()
    store_password(site, email, password)
    return password


def delete_password(site: str, email: str) -> None:
    try:
        keyring.delete_password(_service(site), email)
    except keyring.errors.PasswordDeleteError:
        pass
