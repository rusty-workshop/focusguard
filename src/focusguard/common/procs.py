"""Read-only /proc scanning helpers, used by the enforcer.

Everything here is exact-match only (never substring) and scoped to the
calling user's own UID -- a process belonging to another UID is invisible
to us by construction (we skip it) rather than merely "not blocked".
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

#: Process names that must never be signaled, regardless of what a user
#: selects in the GUI. This protects the compositor, session bus, audio
#: stack, and FocusGuard's own components from ever being killed by a
#: careless or malicious config.
PROTECTED_COMM = {
    "Hyprland", "hyprland", "hyprctl",
    "systemd", "systemd-logind", "systemd-oomd", "(sd-pam)",
    "dbus-daemon", "dbus-broker", "dbus-broker-lau",
    "pipewire", "pipewire-pulse", "wireplumber",
    "polkit-agent-he", "xdg-desktop-por", "xdg-permission-",
    "gnome-keyring-d", "gnome-keyring",
    "NetworkManager", "sshd",
    # FocusGuard's own processes -- see pyproject.toml [project.scripts]
    "focusguardd", "focusguard", "focusguardctl", "focusguard-gui",
}


@dataclass
class ProcInfo:
    pid: int
    uid: int
    comm: str
    exe: Optional[str]
    cmdline: List[str] = field(default_factory=list)


def _read_comm(pid: int) -> str:
    with open(f"/proc/{pid}/comm", "r") as f:
        return f.read().strip()


def _read_cmdline(pid: int) -> List[str]:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            raw = f.read()
    except OSError:
        return []
    parts = raw.split(b"\0")
    return [p.decode(errors="replace") for p in parts if p]


def read_proc(pid: int) -> Optional[ProcInfo]:
    """Snapshot a single pid. Returns None if it's gone or unreadable."""
    try:
        st = os.stat(f"/proc/{pid}")
        comm = _read_comm(pid)
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return None
    try:
        exe = os.readlink(f"/proc/{pid}/exe")
    except OSError:
        exe = None
    return ProcInfo(pid=pid, uid=st.st_uid, comm=comm, exe=exe, cmdline=_read_cmdline(pid))


def iter_processes(uid: int):
    """Yield ProcInfo for every currently-running process owned by ``uid``."""
    try:
        pids = [int(n) for n in os.listdir("/proc") if n.isdigit()]
    except OSError:
        return
    for pid in pids:
        info = read_proc(pid)
        if info is None or info.uid != uid:
            continue
        yield info
