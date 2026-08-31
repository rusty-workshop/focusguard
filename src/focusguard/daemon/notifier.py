"""Best-effort desktop notifications. Never raises -- a notification failure
must never interrupt or crash enforcement."""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

_available: bool | None = None


def _notify_send_available() -> bool:
    global _available
    if _available is None:
        _available = shutil.which("notify-send") is not None
        if not _available:
            log.info("notify-send not found on PATH; notifications disabled")
    return _available


def notify(summary: str, body: str = "", urgency: str = "normal", icon: Optional[Path] = None) -> None:
    if not _notify_send_available():
        return
    cmd = ["notify-send", "-a", "FocusGuard", "-u", urgency]
    if icon is not None:
        cmd += ["-i", str(icon)]
    cmd += ["--", summary, body]
    try:
        subprocess.run(
            cmd,
            timeout=2,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        log.warning("failed to send desktop notification", exc_info=True)
