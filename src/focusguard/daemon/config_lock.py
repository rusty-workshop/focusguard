"""Closes the obvious escape hatch around commitment mode: without this,
Profile.commitment_seconds is trivial to bypass by hand-editing
config.json (or having the GUI write a "weakened" version) and reloading
while the profile is actively blocking -- the whole point of commitment
mode is resisting exactly that kind of in-the-moment impulse, so the
config itself has to be protected the same way Stop/Pause already are.

Deliberately NOT covered, and not realistically coverable: restarting the
daemon (`systemctl --user restart`) right after a hand-edit, since a fresh
process has no prior in-memory config to protect against. This doesn't
lower the bar, though -- `systemctl --user stop` alone already bypasses
*all* enforcement instantly, no edit or wait required, and always has.
Commitment mode raises the cost of the reflexive "just click stop" moment;
it was never a defense against someone willing to go fight their own
systemd units.
"""
from __future__ import annotations

import time
from typing import List, Optional, Tuple

from ..common.config import Config
from . import scheduler
from .state import RuntimeState


def apply_commitment_lock(
    old_cfg: Config, new_cfg: Config, state: RuntimeState, now: Optional[float] = None
) -> Tuple[Config, List[str]]:
    """For every profile that's currently active (scheduled or manual, per
    `old_cfg` + `state` -- the state of the world *before* this reload) and
    has `commitment_seconds > 0`, freeze it back to its `old_cfg`
    definition inside `new_cfg` -- including re-adding it if the incoming
    config deleted it entirely. Every other profile and every setting in
    `new_cfg` passes through untouched: only a profile that is BOTH
    protected AND currently blocking is held back, and only until it's no
    longer active.

    Returns `(new_cfg, locked_names)` -- `new_cfg` is mutated in place and
    also returned for convenience.
    """
    now = now if now is not None else time.time()
    status = scheduler.compute_status(old_cfg, state, now)
    locked: List[str] = []
    for p in status.profiles:
        if not (p.scheduled_active or p.manual_active):
            continue
        old_profile = old_cfg.profiles.get(p.name)
        if old_profile is None or old_profile.commitment_seconds <= 0:
            continue
        new_cfg.profiles[p.name] = old_profile
        locked.append(p.name)
    return new_cfg, locked
