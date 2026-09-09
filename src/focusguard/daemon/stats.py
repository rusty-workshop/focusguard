"""Focus-time history: how many seconds each profile has actually spent
blocking, per day. Purely additive bookkeeping -- never read to decide
enforcement, so a corrupt or missing stats file can never affect blocking
itself, only the numbers `focusguardctl stats` reports.

Kept separate from RuntimeState (state.py): that file is small and
rewritten wholesale on every change since it's read back on every daemon
restart to resume in-progress blocks correctly. This one only ever grows
one profile-day at a time and is flushed periodically rather than on every
poll tick, since a poll tick can be as often as every 0.2s and a stats
write doesn't need anywhere near that resolution.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, Iterable

from ..common import paths

#: Daily records older than this are dropped on save -- keeps the file
#: small indefinitely without needing a separate cleanup step.
_RETENTION_DAYS = 90


@dataclass
class Stats:
    #: "YYYY-MM-DD" -> profile name -> seconds blocked that day.
    daily: Dict[str, Dict[str, float]] = field(default_factory=dict)

    def add_seconds(self, profile_names: Iterable[str], seconds: float, today: str) -> None:
        if seconds <= 0:
            return
        day = self.daily.setdefault(today, {})
        for name in profile_names:
            day[name] = day.get(name, 0.0) + seconds

    def _totals_over(self, days: int, today: date) -> Dict[str, float]:
        cutoff = today - timedelta(days=days - 1)
        totals: Dict[str, float] = {}
        for day_str, per_profile in self.daily.items():
            try:
                day = date.fromisoformat(day_str)
            except ValueError:
                continue
            if day < cutoff or day > today:
                continue
            for name, seconds in per_profile.items():
                totals[name] = totals.get(name, 0.0) + seconds
        return totals

    def today_totals(self, today: date) -> Dict[str, float]:
        return dict(self.daily.get(today.isoformat(), {}))

    def week_totals(self, today: date) -> Dict[str, float]:
        return self._totals_over(7, today)

    def all_time_totals(self, today: date) -> Dict[str, float]:
        return self._totals_over(_RETENTION_DAYS, today)

    def _prune(self, today: date) -> None:
        cutoff = today - timedelta(days=_RETENTION_DAYS)
        self.daily = {
            day_str: per_profile
            for day_str, per_profile in self.daily.items()
            if _safe_date(day_str) is not None and _safe_date(day_str) >= cutoff
        }

    def to_dict(self) -> dict:
        return {"daily": self.daily}

    @classmethod
    def from_dict(cls, d: dict) -> "Stats":
        raw = d.get("daily", {})
        if not isinstance(raw, dict):
            return cls()
        return cls(daily={k: dict(v) for k, v in raw.items() if isinstance(v, dict)})

    def save(self, today: date, path=None) -> None:
        self._prune(today)
        p = path or paths.config_dir() / "stats.json"
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp = tempfile.mkstemp(prefix=".stats-", suffix=".tmp", dir=str(p.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2, sort_keys=True)
            os.chmod(tmp, 0o600)
            os.replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @classmethod
    def load(cls, path=None) -> "Stats":
        p = path or paths.config_dir() / "stats.json"
        if not p.exists():
            return cls()
        try:
            with open(p, "r", encoding="utf-8") as f:
                return cls.from_dict(json.load(f))
        except (OSError, json.JSONDecodeError):
            return cls()


def _safe_date(s: str):
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None
