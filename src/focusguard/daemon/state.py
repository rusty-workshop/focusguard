"""Runtime (non-config) state: which blocks are manually/adhoc active right
now, and whether enforcement is paused. Persisted to state.json so a daemon
restart during an active manual block can recover it.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..common import paths

log = logging.getLogger(__name__)


@dataclass
class ManualBlock:
    profile: str
    started_at: float
    ends_at: Optional[float]  # None = runs until explicitly stopped

    def is_expired(self, now: float) -> bool:
        return self.ends_at is not None and now >= self.ends_at

    def to_dict(self) -> dict:
        return {"profile": self.profile, "started_at": self.started_at, "ends_at": self.ends_at}

    @classmethod
    def from_dict(cls, d: dict) -> "ManualBlock":
        return cls(profile=d["profile"], started_at=d["started_at"], ends_at=d.get("ends_at"))


@dataclass
class RuntimeState:
    manual_blocks: List[ManualBlock] = field(default_factory=list)
    paused_until: Optional[float] = None
    #: profile name -> epoch until which its *schedule* is ignored, set by an
    #: explicit "Stop Mode" while that profile's schedule was active. Expires
    #: on its own once the window would have ended anyway, so the next
    #: scheduled occurrence (tomorrow, etc.) is unaffected.
    schedule_suppressed: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "manual_blocks": [m.to_dict() for m in self.manual_blocks],
            "paused_until": self.paused_until,
            "schedule_suppressed": self.schedule_suppressed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "RuntimeState":
        blocks = [ManualBlock.from_dict(m) for m in d.get("manual_blocks", [])]
        return cls(
            manual_blocks=blocks,
            paused_until=d.get("paused_until"),
            schedule_suppressed=dict(d.get("schedule_suppressed", {})),
        )

    def prune_expired(self, now: float) -> None:
        self.manual_blocks = [m for m in self.manual_blocks if not m.is_expired(now)]
        if self.paused_until is not None and now >= self.paused_until:
            self.paused_until = None
        self.schedule_suppressed = {
            name: until for name, until in self.schedule_suppressed.items() if now < until
        }

    def save(self, path=None) -> None:
        p = path or paths.state_file()
        p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, tmp = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=str(p.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2)
            os.chmod(tmp, 0o600)
            os.replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    @classmethod
    def load(cls, path=None) -> "RuntimeState":
        p = path or paths.state_file()
        if not p.exists():
            return cls()
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = json.load(f)
            state = cls.from_dict(data)
        except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
            log.warning("could not load persisted state (%s), starting fresh", exc)
            return cls()
        state.prune_expired(time.time())
        return state
