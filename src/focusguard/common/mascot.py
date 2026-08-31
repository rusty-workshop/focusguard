"""Vigi, FocusGuard's mascot: a name and a bank of gentle, non-nagging
messages shown when a blocked app is stopped, and used to give the GUI's
status card some personality.

Kept deliberately short and warm rather than scoldy -- the point of a
mascot nudge is to make getting blocked feel like a small, friendly
redirect, not a punishment.
"""
from __future__ import annotations

import importlib.resources
import logging
import random
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

NAME = "Vigi"

#: {app} is replaced with the friendly application name.
NUDGE_MESSAGES = [
    "Not right now — {app} can wait. You've got this.",
    "I caught {app} trying to sneak in. Back to it!",
    "{app} is taking a break with you. Stay focused!",
    "Nice try, {app}. Not during focus time.",
    "Gently redirecting you away from {app}.",
    "{app} will still be there later. Keep going!",
    "I've got {app} covered. You focus on the real thing.",
]

#: Shown once per app per cooldown window, not on every poll tick.
NUDGE_COOLDOWN_SECONDS = 20.0

STATUS_MESSAGES = {
    "ACTIVE": "I'm on watch — stay on track!",
    "PAUSED": "Taking a short breather. Back soon.",
    "INACTIVE": "All clear. Nothing to guard right now.",
}


def nudge_for(app_name: str) -> tuple[str, str]:
    """Return (title, body) for a just-blocked app notification."""
    template = random.choice(NUDGE_MESSAGES)
    return f"{NAME} says:", template.format(app=app_name)


def status_message(state: str) -> str:
    return STATUS_MESSAGES.get(state, STATUS_MESSAGES["INACTIVE"])


_asset_path_cache: Optional[Path] = None


def asset_path() -> Optional[Path]:
    """Filesystem path to Vigi's portrait (bundled as package data), or
    None if it can't be found -- callers must treat this as optional and
    degrade gracefully (no icon on a notification, no image in the GUI)."""
    global _asset_path_cache
    if _asset_path_cache is not None:
        return _asset_path_cache
    try:
        path = importlib.resources.files("focusguard.gui") / "assets" / "vigi.svg"
        if path.is_file():
            _asset_path_cache = Path(str(path))
            return _asset_path_cache
    except (ModuleNotFoundError, FileNotFoundError, TypeError) as exc:
        log.debug("could not resolve Vigi asset path: %s", exc)
    return None
