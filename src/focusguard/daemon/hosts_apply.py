"""Daemon-side glue for website blocking: figures out where the root-run
hosts helper lives, hands it the current domain set via `sudo -n`, and
reports back rather than raising -- a missing/misconfigured sudo rule must
never crash the daemon or take app-blocking down with it.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, Tuple

from ..common import paths

log = logging.getLogger(__name__)

_INSTALLED_HELPER = Path("/usr/lib/focusguard/hosts-helper")
# Falls back to the checked-out copy so `focusguardd` can be run straight out
# of a dev checkout (no `makepkg -si` needed) during development/testing.
_DEV_HELPER = Path(__file__).resolve().parents[3] / "packaging" / "focusguard-hosts-helper"


def _helper_path() -> Path | None:
    if _INSTALLED_HELPER.exists():
        return _INSTALLED_HELPER
    if _DEV_HELPER.exists():
        return _DEV_HELPER
    return None


def apply_domain_block(domains: Iterable[str]) -> Tuple[bool, str]:
    """Apply ``domains`` (already-normalized) as the full desired set of
    blocked websites. Returns (ok, detail) -- detail is empty on success, a
    human-readable reason on failure."""
    helper = _helper_path()
    if helper is None:
        return False, "hosts helper not installed (expected /usr/lib/focusguard/hosts-helper)"
    if shutil.which("sudo") is None:
        return False, "sudo not found"

    rdir = paths.runtime_dir()
    fd, tmp_path = tempfile.mkstemp(prefix=".domains-", suffix=".txt", dir=str(rdir))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for domain in sorted(set(domains)):
                f.write(domain + "\n")
        result = subprocess.run(
            ["sudo", "-n", str(helper), tmp_path],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)

    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or f"exit code {result.returncode}"
        return False, detail
    return True, ""
