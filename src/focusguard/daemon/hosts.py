"""Pure string logic for maintaining FocusGuard's managed block inside
/etc/hosts. No file I/O and no root requirement here on purpose -- this
module is fully unit-testable, and it's also imported (read-only, as plain
functions) by ``packaging/focusguard-hosts-helper``, the small root-run
script that actually touches the real file. Keeping the logic here instead
of duplicating it in the helper means there's exactly one implementation of
"what does the managed block look like".
"""
from __future__ import annotations

from ..common.domains import hosts_names_for, validate_domain

MARK_BEGIN = "# FocusGuard managed block -- BEGIN (do not edit by hand)"
MARK_END = "# FocusGuard managed block -- END"

_REDIRECT_TARGET = "0.0.0.0"  # unroutable -> instant connection refused, not a hang


def render_managed_block(domains) -> str:
    """Render the FocusGuard block for a set/list of already-normalized
    domains. Empty input renders to an empty string (no block at all)."""
    domains = sorted(set(domains))
    if not domains:
        return ""
    lines = [MARK_BEGIN]
    for domain in domains:
        validate_domain(domain)
        for host in hosts_names_for(domain):
            lines.append(f"{_REDIRECT_TARGET} {host}")
    lines.append(MARK_END)
    return "\n".join(lines) + "\n"


def merge_into_hosts(original_text: str, domains) -> str:
    """Return ``original_text`` with FocusGuard's managed block replaced (or
    removed, if ``domains`` is empty) -- anything the user or another tool
    put in the file outside the markers is left untouched.

    Raises ValueError if the markers appear more than once, or only one of
    the pair is present (file was hand-edited into an inconsistent state --
    refuse to guess rather than silently making it worse).
    """
    begin_count = original_text.count(MARK_BEGIN)
    end_count = original_text.count(MARK_END)
    if begin_count > 1 or end_count > 1 or begin_count != end_count:
        raise ValueError(
            "hosts file has an inconsistent FocusGuard block "
            f"(BEGIN markers={begin_count}, END markers={end_count}) -- "
            "refusing to touch it; remove the stray marker(s) by hand"
        )

    new_block = render_managed_block(domains)

    if begin_count == 0:
        if not new_block:
            return original_text
        sep = "" if original_text.endswith("\n") or not original_text else "\n"
        return original_text + sep + new_block

    start = original_text.index(MARK_BEGIN)
    end = original_text.index(MARK_END) + len(MARK_END)
    # Also swallow one trailing newline after the old block so removing it
    # (new_block == "") doesn't leave a blank line behind.
    tail_start = end + 1 if original_text[end:end + 1] == "\n" else end
    before, after = original_text[:start], original_text[tail_start:]
    if not new_block:
        return before.rstrip("\n") + ("\n" if before.strip() else "") + after
    return before + new_block + after
