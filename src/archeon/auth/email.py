"""Email normalization and signup policy shared by local and cloud auth."""

from __future__ import annotations

import re


_EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

# Small deterministic baseline. The database hook applies the same list so the
# rule cannot be bypassed by calling Supabase Auth outside the desktop UI.
DISPOSABLE_EMAIL_DOMAINS = frozenset(
    {
        "10minutemail.com",
        "dispostable.com",
        "dropmail.me",
        "emailondeck.com",
        "fakeinbox.com",
        "guerrillamail.com",
        "maildrop.cc",
        "mailinator.com",
        "moakt.com",
        "sharklasers.com",
        "temp-mail.org",
        "tempmail.com",
        "throwawaymail.com",
        "yopmail.com",
    }
)


def normalize_email(
    email: str, *, reject_disposable: bool = False, canonical_aliases: bool = True
) -> str:
    """Validate an address and optionally return its stable mailbox identity.

    Alias canonicalization belongs on signup/change-email uniqueness checks. It
    is optional for login/recovery so legacy accounts can use their stored form.
    """

    value = email.strip().casefold()
    if len(value) > 254 or not _EMAIL_RE.fullmatch(value):
        raise ValueError("invalid_email")
    local, domain = value.rsplit("@", 1)
    try:
        domain = domain.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise ValueError("invalid_email") from error
    if reject_disposable and any(
        domain == blocked or domain.endswith(f".{blocked}")
        for blocked in DISPOSABLE_EMAIL_DOMAINS
    ):
        raise ValueError("disposable_email_not_allowed")
    if canonical_aliases and domain in {"gmail.com", "googlemail.com"}:
        domain = "gmail.com"
        local = local.split("+", 1)[0].replace(".", "")
    if not local or len(local) > 64:
        raise ValueError("invalid_email")
    return f"{local}@{domain}"
