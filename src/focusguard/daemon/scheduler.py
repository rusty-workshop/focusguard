"""Turns config + runtime state + wall-clock time into "what's blocked now".

Handles: multiple simultaneously-active profiles (union of their blocked
apps), schedules that cross midnight, and a pause window that suspends
enforcement without discarding the underlying active blocks (they resume
automatically once the pause expires).
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

from ..common.config import Config, Schedule
from .state import RuntimeState


def schedule_matches(schedule: Schedule, now: datetime) -> bool:
    """True if ``schedule`` puts a profile in its blocking window at ``now``."""
    if not schedule.enabled or not schedule.days:
        return False
    sh, sm = (int(x) for x in schedule.start.split(":"))
    eh, em = (int(x) for x in schedule.end.split(":"))
    start_min = sh * 60 + sm
    end_min = eh * 60 + em
    cur_min = now.hour * 60 + now.minute
    weekday = now.weekday()  # Monday=0 .. Sunday=6

    if start_min == end_min:
        return False  # zero-length window never activates
    if start_min < end_min:
        return weekday in schedule.days and start_min <= cur_min < end_min

    # Crosses midnight, e.g. 22:00 -> 06:00: active from `start` on a
    # scheduled day through `end` the following morning.
    if weekday in schedule.days and cur_min >= start_min:
        return True
    prev_weekday = (weekday - 1) % 7
    if prev_weekday in schedule.days and cur_min < end_min:
        return True
    return False


def schedule_window_end(schedule: Schedule, now: datetime) -> float:
    """Epoch timestamp when the window ``schedule`` is currently in (per
    ``schedule_matches(schedule, now) == True``) ends. Used to suppress a
    schedule for the remainder of *this* occurrence only, on explicit Stop."""
    sh, sm = (int(x) for x in schedule.start.split(":"))
    eh, em = (int(x) for x in schedule.end.split(":"))
    start_min = sh * 60 + sm
    end_min = eh * 60 + em
    cur_min = now.hour * 60 + now.minute

    if start_min < end_min:
        end_dt = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    else:
        if cur_min >= start_min:
            end_dt = (now + timedelta(days=1)).replace(hour=eh, minute=em, second=0, microsecond=0)
        else:
            end_dt = now.replace(hour=eh, minute=em, second=0, microsecond=0)
    return end_dt.timestamp()


@dataclass
class ProfileStatus:
    name: str
    scheduled_active: bool
    manual_active: bool
    manual_ends_at: Optional[float]
    schedule_enabled: bool


@dataclass
class DaemonStatus:
    now: float
    paused: bool
    paused_until: Optional[float]
    profiles: List[ProfileStatus]
    blocked_desktop_ids: List[str]


def compute_status(cfg: Config, state: RuntimeState, now: Optional[float] = None) -> DaemonStatus:
    now = now if now is not None else time.time()
    state.prune_expired(now)
    dt = datetime.fromtimestamp(now)

    manual_by_profile = {m.profile: m for m in state.manual_blocks}
    paused = state.paused_until is not None and now < state.paused_until

    statuses: List[ProfileStatus] = []
    blocked_ids: set[str] = set()
    for name, profile in cfg.profiles.items():
        scheduled = schedule_matches(profile.schedule, dt)
        suppressed_until = state.schedule_suppressed.get(name)
        if scheduled and suppressed_until is not None and now < suppressed_until:
            scheduled = False
        manual = manual_by_profile.get(name)
        manual_active = manual is not None
        statuses.append(
            ProfileStatus(
                name=name,
                scheduled_active=scheduled,
                manual_active=manual_active,
                manual_ends_at=manual.ends_at if manual else None,
                schedule_enabled=profile.schedule.enabled,
            )
        )
        if not paused and (scheduled or manual_active):
            blocked_ids.update(profile.blocked_apps)

    return DaemonStatus(
        now=now,
        paused=paused,
        paused_until=state.paused_until,
        profiles=statuses,
        blocked_desktop_ids=sorted(blocked_ids),
    )
