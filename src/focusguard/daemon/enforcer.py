"""Actually stops blocked applications from running.

Mechanism: every poll tick, scan the process table for the current user,
and for any process whose exact executable basename/realpath (or, for
Flatpak apps, app-id argv token) matches a currently-blocked app's
signature, send SIGTERM. If it's still alive after a grace period, escalate
to SIGKILL. This is checked every tick, so a relaunch attempt is caught
again on the next scan (bounded by poll_interval_seconds).

Safety invariants enforced here, independent of whatever the user put in
their config:
  * Never signal a process owned by a different UID (iter_processes already
    filters to our own UID; we re-check immediately before every kill in
    case of PID reuse between scan and kill).
  * Never signal anything in procs.PROTECTED_COMM (compositor, session bus,
    audio stack, FocusGuard's own components).
  * Never match on a substring -- only exact basename/realpath/app-id
    equality against the resolved signature set.
"""
from __future__ import annotations

import logging
import os
import signal
import time
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Set, Tuple

from ..common import procs
from ..common.appinfo import lookup_app

log = logging.getLogger(__name__)


def _build_signature_index(desktop_ids: Iterable[str]) -> Dict[str, str]:
    """signature -> desktop_id, skipping anything that would collide with a
    protected name (defense in depth on top of the fixed denylist check done
    at kill time)."""
    index: Dict[str, str] = {}
    for desktop_id in desktop_ids:
        entry = lookup_app(desktop_id)
        if not entry:
            log.warning("blocked app %r is no longer resolvable, skipping", desktop_id)
            continue
        for sig in entry.signatures:
            if sig in procs.PROTECTED_COMM:
                continue
            index.setdefault(sig, desktop_id)
    return index


def _matches(proc: procs.ProcInfo, sig_index: Dict[str, str]) -> str | None:
    if proc.comm in sig_index:
        return sig_index[proc.comm]
    if proc.exe:
        base = os.path.basename(proc.exe)
        if base in sig_index:
            return sig_index[base]
        if proc.exe in sig_index:
            return sig_index[proc.exe]
    # Flatpak: app-id shows up as a bare argv token.
    for tok in proc.cmdline:
        if tok in sig_index:
            return sig_index[tok]
    return None


@dataclass
class _Pending:
    app_id: str
    comm: str
    sigterm_at: float


class Enforcer:
    def __init__(self, grace_period_seconds: float = 3.0):
        self.grace_period_seconds = grace_period_seconds
        self._pending: Dict[int, _Pending] = {}
        self._my_uid = os.getuid()

    def tick(self, blocked_desktop_ids: List[str]) -> List[Tuple[str, int, str]]:
        """Run one enforcement pass. Returns a list of (action, pid, detail)
        for anything logged this tick, for callers that want to react
        (e.g. notify)."""
        now = time.time()
        events: List[Tuple[str, int, str]] = []
        killed_this_tick: Set[int] = set()

        # 1. Escalate anything past its grace period.
        for pid in list(self._pending):
            pending = self._pending[pid]
            if now - pending.sigterm_at < self.grace_period_seconds:
                continue
            info = procs.read_proc(pid)
            if info is None or info.comm != pending.comm:
                # already gone, or pid was reused for something else
                del self._pending[pid]
                continue
            if info.uid != self._my_uid or info.comm in procs.PROTECTED_COMM:
                del self._pending[pid]
                continue
            try:
                os.kill(pid, signal.SIGKILL)
                log.info(
                    "SIGKILL app_id=%s pid=%s comm=%s (still alive after %.1fs grace)",
                    pending.app_id, pid, info.comm, self.grace_period_seconds,
                )
                events.append(("sigkill", pid, pending.app_id))
            except ProcessLookupError:
                pass
            killed_this_tick.add(pid)
            del self._pending[pid]

        if not blocked_desktop_ids:
            return events

        sig_index = _build_signature_index(blocked_desktop_ids)
        if not sig_index:
            return events

        # 2. Scan for new matches and SIGTERM them.
        for proc_info in procs.iter_processes(self._my_uid):
            if proc_info.pid in self._pending or proc_info.pid in killed_this_tick:
                continue
            if proc_info.comm in procs.PROTECTED_COMM:
                continue
            app_id = _matches(proc_info, sig_index)
            if app_id is None:
                continue
            try:
                os.kill(proc_info.pid, signal.SIGTERM)
                log.info(
                    "SIGTERM app_id=%s pid=%s comm=%s exe=%s",
                    app_id, proc_info.pid, proc_info.comm, proc_info.exe,
                )
                events.append(("sigterm", proc_info.pid, app_id))
                self._pending[proc_info.pid] = _Pending(
                    app_id=app_id, comm=proc_info.comm, sigterm_at=now
                )
            except ProcessLookupError:
                pass

        return events
