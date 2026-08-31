"""FocusGuard configuration: dataclasses, validation, and atomic JSON I/O.

The config file is treated as untrusted input (a user, or a bad edit, or a
partially-written file could hand us garbage) -- ``load_config`` always
returns *something* usable and raises :class:`ConfigError` with a clear
message on malformed data rather than crashing the daemon or silently
destroying the file. ``save_config`` writes atomically (temp file + rename)
so a crash mid-write can never corrupt the on-disk config.
"""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import dataclass, field, asdict
from typing import Dict, List

from . import paths

log = logging.getLogger(__name__)

_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class ConfigError(ValueError):
    """Raised when configuration data fails validation."""


@dataclass
class Schedule:
    enabled: bool = False
    days: List[int] = field(default_factory=list)  # 0=Monday .. 6=Sunday
    start: str = "08:00"
    end: str = "15:00"

    def validate(self, where: str) -> None:
        if not isinstance(self.enabled, bool):
            raise ConfigError(f"{where}.schedule.enabled must be a boolean")
        if not isinstance(self.days, list) or any(
            not isinstance(d, int) or d < 0 or d > 6 for d in self.days
        ):
            raise ConfigError(f"{where}.schedule.days must be a list of ints 0-6")
        if len(set(self.days)) != len(self.days):
            raise ConfigError(f"{where}.schedule.days must not contain duplicates")
        for label, value in (("start", self.start), ("end", self.end)):
            if not isinstance(value, str) or not _TIME_RE.match(value):
                raise ConfigError(
                    f"{where}.schedule.{label} must be HH:MM (24h), got {value!r}"
                )


@dataclass
class Profile:
    name: str
    blocked_apps: List[str] = field(default_factory=list)
    schedule: Schedule = field(default_factory=Schedule)
    manual_duration_minutes: int = 45

    def validate(self) -> None:
        if not self.name or not isinstance(self.name, str):
            raise ConfigError("profile name must be a non-empty string")
        if not isinstance(self.blocked_apps, list) or any(
            not isinstance(a, str) or not a for a in self.blocked_apps
        ):
            raise ConfigError(f"profile {self.name!r}: blocked_apps must be a list of strings")
        if len(set(self.blocked_apps)) != len(self.blocked_apps):
            raise ConfigError(f"profile {self.name!r}: blocked_apps has duplicates")
        if not isinstance(self.manual_duration_minutes, int) or not (
            1 <= self.manual_duration_minutes <= 24 * 60
        ):
            raise ConfigError(
                f"profile {self.name!r}: manual_duration_minutes must be 1-1440"
            )
        self.schedule.validate(f"profile {self.name!r}")


@dataclass
class Settings:
    poll_interval_seconds: float = 1.0
    grace_period_seconds: float = 3.0
    notifications_enabled: bool = True

    def validate(self) -> None:
        if not (0.2 <= float(self.poll_interval_seconds) <= 30):
            raise ConfigError("settings.poll_interval_seconds must be 0.2-30")
        if not (0 <= float(self.grace_period_seconds) <= 60):
            raise ConfigError("settings.grace_period_seconds must be 0-60")
        if not isinstance(self.notifications_enabled, bool):
            raise ConfigError("settings.notifications_enabled must be a boolean")


@dataclass
class Config:
    profiles: Dict[str, Profile] = field(default_factory=dict)
    settings: Settings = field(default_factory=Settings)

    def validate(self) -> None:
        for key, profile in self.profiles.items():
            if key != profile.name:
                raise ConfigError(f"profile key {key!r} does not match name {profile.name!r}")
            profile.validate()
        self.settings.validate()

    def to_dict(self) -> dict:
        return {
            "profiles": {
                name: {
                    "name": p.name,
                    "blocked_apps": list(p.blocked_apps),
                    "schedule": asdict(p.schedule),
                    "manual_duration_minutes": p.manual_duration_minutes,
                }
                for name, p in self.profiles.items()
            },
            "settings": asdict(self.settings),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        if not isinstance(data, dict):
            raise ConfigError("config root must be a JSON object")
        raw_profiles = data.get("profiles", {})
        if not isinstance(raw_profiles, dict):
            raise ConfigError("config.profiles must be an object")
        profiles = {}
        for name, raw in raw_profiles.items():
            if not isinstance(raw, dict):
                raise ConfigError(f"profile {name!r} must be an object")
            raw_sched = raw.get("schedule", {})
            if not isinstance(raw_sched, dict):
                raise ConfigError(f"profile {name!r}.schedule must be an object")
            try:
                schedule = Schedule(**raw_sched)
                profile = Profile(
                    name=raw.get("name", name),
                    blocked_apps=raw.get("blocked_apps", []),
                    schedule=schedule,
                    manual_duration_minutes=raw.get("manual_duration_minutes", 45),
                )
            except TypeError as exc:
                raise ConfigError(f"profile {name!r} has invalid fields: {exc}") from exc
            profiles[name] = profile
        raw_settings = data.get("settings", {})
        if not isinstance(raw_settings, dict):
            raise ConfigError("config.settings must be an object")
        try:
            settings = Settings(**raw_settings)
        except TypeError as exc:
            raise ConfigError(f"invalid settings fields: {exc}") from exc
        cfg = cls(profiles=profiles, settings=settings)
        cfg.validate()
        return cfg


def default_config() -> Config:
    return Config(profiles={}, settings=Settings())


def load_config(path=None) -> Config:
    """Load config from disk. Returns defaults if the file is missing.

    Raises ConfigError (never touches the file) if it exists but is
    malformed -- callers decide how to react (daemon keeps last-known-good
    in memory and logs; GUI/CLI surface the error to the user).
    """
    p = path or paths.config_file()
    if not p.exists():
        return default_config()
    try:
        with open(p, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigError(f"failed to read {p}: {exc}") from exc
    return Config.from_dict(raw)


def save_config(cfg: Config, path=None) -> None:
    """Validate then atomically write the config (temp file + rename)."""
    cfg.validate()
    p = path or paths.config_file()
    p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp_path = tempfile.mkstemp(prefix=".config-", suffix=".tmp", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg.to_dict(), f, indent=2, sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, 0o600)
        os.replace(tmp_path, p)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
