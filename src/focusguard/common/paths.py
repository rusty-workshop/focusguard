"""XDG-appropriate filesystem locations for FocusGuard."""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "focusguard"


def _xdg(env_var: str, default: str) -> Path:
    base = os.environ.get(env_var)
    return Path(base) if base else Path.home() / default


def config_dir() -> Path:
    p = _xdg("XDG_CONFIG_HOME", ".config") / APP_NAME
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    return p


def config_file() -> Path:
    return config_dir() / "config.json"


def state_file() -> Path:
    return config_dir() / "state.json"


def state_dir() -> Path:
    """Location for logs when not run under systemd (journald is preferred)."""
    p = _xdg("XDG_STATE_HOME", ".local/state") / APP_NAME
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    return p


def runtime_dir() -> Path:
    base = os.environ.get("XDG_RUNTIME_DIR")
    root = Path(base) if base else config_dir() / "run"
    p = root / APP_NAME
    p.mkdir(parents=True, exist_ok=True, mode=0o700)
    return p


def socket_path() -> Path:
    return runtime_dir() / "ctl.sock"
