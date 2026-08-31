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
    "Nope — {app} is off-limits for now.",
    "Future you says thanks for skipping {app}.",
    "{app} again? I see you. Let's refocus.",
    "Blocked {app} so you don't have to rely on willpower alone.",
    "One step closer, as long as you stay away from {app}.",
    "{app} can wait a little longer. You're doing great.",
    "Caught you! {app} is paused until this session ends.",
    "Sneaky. But {app} stays closed for now.",
    "That's a no from me — {app} is on the blocklist right now.",
    "{app} isn't going anywhere. Neither should your focus.",
    "Not today, {app}. Back to what matters.",
    "I'm keeping {app} out of reach for a bit longer.",
    "Whoa there — {app} is a distraction for later, not now.",
    "Held the line against {app}. Proud of you.",
    "{app} will keep. Your focus won't, if you let it slip.",
    "Quietly closing the door on {app} for you.",
    "Still watching — {app} doesn't get past me right now.",
]

#: Shown once per app per cooldown window, not on every poll tick.
NUDGE_COOLDOWN_SECONDS = 20.0

STATUS_MESSAGES = {
    "ACTIVE": [
        "I'm on watch — stay on track!",
        "Standing guard. You focus, I'll handle the rest.",
        "On duty. Let's get this done.",
        "Eyes open, distractions out.",
    ],
    "PAUSED": [
        "Taking a short breather. Back soon.",
        "Stretching my legs for a bit.",
        "On a quick break — I'll be back on watch shortly.",
    ],
    "INACTIVE": [
        "All clear. Nothing to guard right now.",
        "Off duty. Start a profile whenever you're ready.",
        "Standing by — nothing blocked at the moment.",
    ],
}


#: Idle small talk, shown in the GUI every so often instead of the plain
#: status line, purely for personality -- none of this carries information
#: the title/detail labels don't already show, so it's safe to be silly.
IDLE_CHATTER = [
    "Did you know I blink? Try to catch it.",
    "Just floating here, thinking shield thoughts.",
    "Focus is a marathon, not a sprint.",
    "I'm not just a pretty shield, you know.",
    "Still here. Still watching. Still floating.",
    "Small steps count. Keep going.",
    "I'd high-five you if I had hands that reached that far.",
    "Somewhere, an app is very disappointed in me.",
    "Guarding is my whole personality.",
    "You're doing better than you think.",
    "I practiced my glare for this.",
    "No apps were harmed. Several were inconvenienced.",
    "Ten out of ten focus. Would guard again.",
    "I float because standing still is boring.",
    "This is me, being vigilant. It looks a lot like blinking.",
]


def idle_chatter() -> str:
    return random.choice(IDLE_CHATTER)


def nudge_for(app_name: str) -> tuple[str, str]:
    """Return (title, body) for a just-blocked app notification."""
    template = random.choice(NUDGE_MESSAGES)
    return f"{NAME} says:", template.format(app=app_name)


def status_message(state: str) -> str:
    """A random line for the given state. Callers that poll frequently (the
    GUI status card) should cache the result and only re-roll when the
    state itself changes, or this will flicker distractingly."""
    return random.choice(STATUS_MESSAGES.get(state, STATUS_MESSAGES["INACTIVE"]))


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
