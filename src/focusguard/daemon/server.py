"""Daemon core: asyncio Unix-socket control server + the enforcement loop.

The socket is created inside $XDG_RUNTIME_DIR/focusguard (mode 0700 dir) and
explicitly chmod'd 0600; every connection's peer credentials are checked
against our own UID via SO_PEERCRED before the request is even parsed.
Commands are a fixed whitelist -- anything else is rejected -- and every
argument is type/range validated. Nothing here ever spawns a shell or
interpolates config data into a command line.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import struct
import time
from datetime import datetime
from typing import Optional

from ..common import paths
from ..common.config import Config, ConfigError, load_config
from . import scheduler
from .enforcer import Enforcer
from .notifier import notify
from .state import ManualBlock, RuntimeState

log = logging.getLogger(__name__)


def _peer_uid(writer: asyncio.StreamWriter) -> Optional[int]:
    sock: socket.socket = writer.get_extra_info("socket")
    if sock is None:
        return None
    try:
        creds = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        pid, uid, gid = struct.unpack("3i", creds)
        return uid
    except OSError:
        return None


class Daemon:
    def __init__(self):
        self.cfg_path = paths.config_file()
        self._cfg_mtime: float = 0.0
        self.cfg: Config = self._load_config_safely()
        self.state = RuntimeState.load()
        self.enforcer = Enforcer(self.cfg.settings.grace_period_seconds)
        self._my_uid = os.getuid()
        self._prev_blocked_ids: set[str] = set()
        self._server: Optional[asyncio.base_events.Server] = None

    # ---------------------------------------------------------------- config
    def _load_config_safely(self) -> Config:
        try:
            cfg = load_config(self.cfg_path)
            if self.cfg_path.exists():
                self._cfg_mtime = self.cfg_path.stat().st_mtime
            return cfg
        except ConfigError as exc:
            log.error("config at %s is invalid, keeping previous config: %s", self.cfg_path, exc)
            return getattr(self, "cfg", None) or Config()

    def _maybe_reload_config(self) -> None:
        try:
            mtime = self.cfg_path.stat().st_mtime if self.cfg_path.exists() else 0.0
        except OSError:
            return
        if mtime != self._cfg_mtime:
            log.info("config file changed on disk, reloading")
            self.cfg = self._load_config_safely()
            self.enforcer.grace_period_seconds = self.cfg.settings.grace_period_seconds

    # ------------------------------------------------------------- lifecycle
    async def run(self) -> None:
        sock_path = paths.socket_path()
        if sock_path.exists():
            sock_path.unlink()
        self._server = await asyncio.start_unix_server(self._handle_client, path=str(sock_path))
        os.chmod(sock_path, 0o600)
        log.info("listening on %s", sock_path)

        status = scheduler.compute_status(self.cfg, self.state)
        self._prev_blocked_ids = set(status.blocked_desktop_ids)
        if status.blocked_desktop_ids:
            log.info("startup: %d app(s) already due to be blocked", len(status.blocked_desktop_ids))

        try:
            while True:
                await self._tick()
                await asyncio.sleep(self.cfg.settings.poll_interval_seconds)
        finally:
            self._server.close()
            await self._server.wait_closed()
            if sock_path.exists():
                sock_path.unlink()

    async def _tick(self) -> None:
        self._maybe_reload_config()
        now = time.time()
        self.state.prune_expired(now)
        status = scheduler.compute_status(self.cfg, self.state, now)
        newly_blocked = set(status.blocked_desktop_ids)

        if newly_blocked != self._prev_blocked_ids:
            started = newly_blocked - self._prev_blocked_ids
            ended = self._prev_blocked_ids - newly_blocked
            if started and self.cfg.settings.notifications_enabled:
                notify("FocusGuard: block started", f"{len(started)} app(s) now blocked")
            if ended and self.cfg.settings.notifications_enabled and not status.paused:
                notify("FocusGuard: block ended", f"{len(ended)} app(s) no longer blocked")
            self._prev_blocked_ids = newly_blocked

        self.enforcer.tick(status.blocked_desktop_ids)

    def _enforce_now(self) -> None:
        """Run an immediate out-of-band enforcement pass (used right after a
        command mutates state) rather than waiting for the next poll tick."""
        status = scheduler.compute_status(self.cfg, self.state)
        self.enforcer.tick(status.blocked_desktop_ids)
        self._prev_blocked_ids = set(status.blocked_desktop_ids)

    # ------------------------------------------------------------------ IPC
    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer_uid = _peer_uid(writer)
        if peer_uid is not None and peer_uid != self._my_uid:
            log.warning("rejected IPC connection from uid=%s", peer_uid)
            writer.close()
            return
        try:
            line = await asyncio.wait_for(reader.readline(), timeout=5.0)
        except asyncio.TimeoutError:
            writer.close()
            return
        response = self._dispatch(line)
        try:
            writer.write((json.dumps(response) + "\n").encode("utf-8"))
            await writer.drain()
        except (ConnectionResetError, BrokenPipeError):
            pass
        finally:
            writer.close()

    def _dispatch(self, raw: bytes) -> dict:
        try:
            request = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {"ok": False, "error": "malformed request"}
        if not isinstance(request, dict):
            return {"ok": False, "error": "request must be a JSON object"}
        cmd = request.get("cmd")
        handler = self._COMMANDS.get(cmd)
        if handler is None:
            return {"ok": False, "error": f"unknown command {cmd!r}"}
        try:
            return handler(self, request)
        except Exception as exc:  # noqa: BLE001 -- IPC boundary must never crash the daemon
            log.exception("error handling command %r", cmd)
            return {"ok": False, "error": str(exc)}

    # -- command handlers --------------------------------------------------
    def _cmd_status(self, request: dict) -> dict:
        status = scheduler.compute_status(self.cfg, self.state)
        profiles = []
        for p in status.profiles:
            if status.paused:
                state_name = "PAUSED"
            elif p.scheduled_active or p.manual_active:
                state_name = "ACTIVE"
            elif p.schedule_enabled:
                state_name = "SCHEDULED"
            else:
                state_name = "INACTIVE"
            profiles.append(
                {
                    "name": p.name,
                    "state": state_name,
                    "manual_active": p.manual_active,
                    "manual_ends_at": p.manual_ends_at,
                    "scheduled_active": p.scheduled_active,
                }
            )
        return {
            "ok": True,
            "now": status.now,
            "paused": status.paused,
            "paused_until": status.paused_until,
            "blocked_apps": status.blocked_desktop_ids,
            "profiles": profiles,
        }

    def _cmd_start(self, request: dict) -> dict:
        name = request.get("profile")
        if not isinstance(name, str) or name not in self.cfg.profiles:
            return {"ok": False, "error": f"unknown profile {name!r}"}
        profile = self.cfg.profiles[name]
        now = time.time()
        self.state.manual_blocks = [m for m in self.state.manual_blocks if m.profile != name]
        ends_at = now + profile.manual_duration_minutes * 60
        self.state.manual_blocks.append(ManualBlock(profile=name, started_at=now, ends_at=ends_at))
        self.state.save()
        if self.cfg.settings.notifications_enabled:
            notify(f"FocusGuard: {name} started", f"Blocking {len(profile.blocked_apps)} app(s)")
        self._enforce_now()
        return self._cmd_status(request)

    def _cmd_stop(self, request: dict) -> dict:
        name = request.get("profile")  # optional: stop just one profile
        now = time.time()
        dt = datetime.fromtimestamp(now)
        stopped = []
        for pname, profile in self.cfg.profiles.items():
            if name is not None and pname != name:
                continue
            had_manual = any(m.profile == pname for m in self.state.manual_blocks)
            self.state.manual_blocks = [m for m in self.state.manual_blocks if m.profile != pname]
            was_scheduled = scheduler.schedule_matches(profile.schedule, dt)
            if was_scheduled:
                until = scheduler.schedule_window_end(profile.schedule, dt)
                self.state.schedule_suppressed[pname] = until
            if had_manual or was_scheduled:
                stopped.append(pname)
        self.state.save()
        if stopped and self.cfg.settings.notifications_enabled:
            notify("FocusGuard: stopped", ", ".join(stopped))
        self._enforce_now()
        return self._cmd_status(request)

    def _cmd_pause(self, request: dict) -> dict:
        minutes = request.get("minutes")
        if not isinstance(minutes, (int, float)) or not (0 < minutes <= 24 * 60):
            return {"ok": False, "error": "minutes must be a number between 0 and 1440"}
        self.state.paused_until = time.time() + minutes * 60
        self.state.save()
        if self.cfg.settings.notifications_enabled:
            notify("FocusGuard: paused", f"Enforcement paused for {minutes:g} minute(s)")
        self._prev_blocked_ids = set()  # nothing enforced while paused
        return self._cmd_status(request)

    def _cmd_resume(self, request: dict) -> dict:
        self.state.paused_until = None
        self.state.save()
        self._enforce_now()
        return self._cmd_status(request)

    def _cmd_toggle(self, request: dict) -> dict:
        name = request.get("profile")
        if not isinstance(name, str) or name not in self.cfg.profiles:
            return {"ok": False, "error": f"unknown profile {name!r}"}
        is_manual = any(m.profile == name for m in self.state.manual_blocks)
        if is_manual:
            return self._cmd_stop({"profile": name})
        return self._cmd_start({"profile": name})

    def _cmd_reload(self, request: dict) -> dict:
        self.cfg = self._load_config_safely()
        self.enforcer.grace_period_seconds = self.cfg.settings.grace_period_seconds
        self._enforce_now()
        return {"ok": True}

    _COMMANDS = {
        "status": _cmd_status,
        "start": _cmd_start,
        "stop": _cmd_stop,
        "pause": _cmd_pause,
        "resume": _cmd_resume,
        "toggle": _cmd_toggle,
        "reload": _cmd_reload,
    }
