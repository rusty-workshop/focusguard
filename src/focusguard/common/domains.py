"""Validation/normalization for website-blocking domains.

Kept dependency-free (stdlib only) because :mod:`focusguard.daemon.hosts`
pulls this in and that module is imported by the root-run hosts helper --
nothing here may assume GTK, asyncio, or any of the rest of the app is
available.
"""
from __future__ import annotations

import re

# One or more labels of letters/digits/hyphens, dot-separated, no leading/
# trailing hyphen per label. Deliberately conservative: this string ends up
# on a line in /etc/hosts, so anything that doesn't match is rejected rather
# than "sanitized".
_DOMAIN_RE = re.compile(
    r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$"
)


class InvalidDomainError(ValueError):
    """Raised when a string is not an acceptable domain to block."""


def normalize_domain(raw: str) -> str:
    """Lowercase, strip a scheme/path/port/trailing dot the user might have
    pasted in (e.g. from a URL bar), leaving a bare domain like
    ``example.com``. Raises :class:`InvalidDomainError` if what's left isn't
    a plausible domain."""
    value = raw.strip().lower()
    if "://" in value:
        value = value.split("://", 1)[1]
    value = value.split("/", 1)[0]
    value = value.split("@", 1)[-1]  # tolerate a pasted user@host
    value = value.split(":", 1)[0]  # strip a port
    value = value.rstrip(".")
    if not _DOMAIN_RE.match(value):
        raise InvalidDomainError(f"{raw!r} is not a valid domain")
    return value


def validate_domain(value: str) -> None:
    """Like :func:`normalize_domain` but only validates -- for checking a
    value that's supposed to already be normalized (e.g. loaded from
    config)."""
    if not isinstance(value, str) or not _DOMAIN_RE.match(value):
        raise InvalidDomainError(f"{value!r} is not a valid domain")


def hosts_names_for(domain: str) -> list[str]:
    """The hostnames to actually redirect for a blocked ``domain``: the bare
    domain plus its ``www.`` variant, so blocking ``x.com`` also catches the
    extremely common ``www.x.com`` without the user having to list both."""
    if domain.startswith("www."):
        return [domain]
    return [domain, f"www.{domain}"]
