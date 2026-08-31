"""Logging config shared by the daemon, GUI, and CLI.

Under systemd, stdout/stderr are already captured by journald with proper
levels via `systemd-cat`-style prefixing, so we just log to stderr -- view
with `journalctl --user -u focusguard -f`. Running interactively (not under
systemd) the same stderr stream is simply visible in the terminal.
"""
from __future__ import annotations

import logging
import os


def setup(name: str) -> None:
    level_name = os.environ.get("FOCUSGUARD_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format=f"%(asctime)s {name} %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
