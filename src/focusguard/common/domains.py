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


#: Best-effort, not exhaustive: /etc/hosts has no concept of a wildcard
#: (there's no way to say "*.reddit.com" in it), so true subdomain coverage
#: would mean taking over DNS resolution system-wide -- not worth doing on
#: a machine where Tailscale's MagicDNS already owns that. This is instead
#: a curated list of the subdomain prefixes sites actually use in practice
#: (old.reddit.com, m.facebook.com, mobile.twitter.com, ...), applied to
#: every blocked domain that doesn't already start with one of them.
_COMMON_SUBDOMAIN_PREFIXES = ["www", "m", "mobile", "old", "new", "i", "out", "amp", "lite"]


def hosts_names_for(domain: str) -> list[str]:
    """The hostnames to actually redirect for a blocked ``domain``: the bare
    domain plus a handful of common subdomain prefixes (``www.``, ``m.``,
    ``old.``, ...), so blocking ``x.com`` also catches the likes of
    ``m.x.com`` without the user having to list every variant by hand."""
    if any(domain == p or domain.startswith(f"{p}.") for p in _COMMON_SUBDOMAIN_PREFIXES):
        return [domain]
    return [domain] + [f"{p}.{domain}" for p in _COMMON_SUBDOMAIN_PREFIXES]
