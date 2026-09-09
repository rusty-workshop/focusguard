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
from datetime import date, datetime
from typing import Optional

from ..common import mascot, paths
from ..common.appinfo import lookup_app
from ..common.config import Config, ConfigError, load_config, save_config
from . import scheduler
from .config_lock import apply_commitment_lock
from .enforcer import Enforcer
from .hosts_apply import apply_domain_block
from .notifier import notify
from .state import ManualBlock, PendingConfirm, RuntimeState
from .stats import Stats

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
        self._prev_blocked_domains: set[str] = set()
        self._hosts_block_ok = True  # last apply_domain_block() result, for once-only failure notices
        self._server: Optional[asyncio.base_events.Server] = None
        self._last_nudge: dict[str, float] = {}
        self._stats = Stats.load()
        self._last_stats_flush = 0.0
        self._last_tick_at: Optional[float] = None

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
            self._load_and_lock_config()

    def _load_and_lock_config(self) -> list[str]:
        """Reload config.json, then re-freeze any currently-active,
        commitment-protected profile back to its prior definition -- see
        config_lock.py. Used by both the explicit `reload` command and the
        automatic on-disk-change reload, so a hand-edited config.json can't
        bypass commitment mode any more than the CLI/GUI can."""
        new_cfg = self._load_config_safely()
        locked_cfg, locked = apply_commitment_lock(self.cfg, new_cfg, self.state)
        self.cfg = locked_cfg
        self.enforcer.grace_period_seconds = self.cfg.settings.grace_period_seconds
        if locked:
            log.warning("held back edits to protected+active profile(s): %s", ", ".join(locked))
            if self.cfg.settings.notifications_enabled:
                notify(
                    "FocusGuard: edit held back",
                    f"{', '.join(locked)} is protected while active — changes apply once it stops.",
                )
            # Without this, config.json on disk still holds the weakened
            # values -- a `systemctl --user restart` (no root needed,
            # unlike anything else this app protects against) would then
            # load them fresh with no prior in-memory config to compare
            # against, bypassing the lock entirely. Writing the corrected
            # config back closes that window too.
            try:
                save_config(self.cfg, self.cfg_path)
                self._cfg_mtime = self.cfg_path.stat().st_mtime
            except (ConfigError, OSError) as exc:
                log.error("could not persist the reverted config back to disk: %s", exc)
        return locked

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
        self._apply_website_block(status.blocked_domains)

        try:
            while True:
                await self._tick()
                await asyncio.sleep(self.cfg.settings.poll_interval_seconds)
        finally:
            self._server.close()
            await self._server.wait_closed()
            if sock_path.exists():
                sock_path.unlink()
            # Clear the hosts block on shutdown -- websites should only stay
            # blocked while the daemon is actually running to reconcile them
            # (matches how app-blocking naturally stops with the daemon).
            # Startup re-applies whatever should be active, so a quick
            # restart just means a brief window where sites are reachable.
            self._apply_website_block([])
            self._stats.save(today=date.today())

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

        events = self.enforcer.tick(status.blocked_desktop_ids)
        self._handle_enforcement_events(events, now)
        self._apply_website_block(status.blocked_domains)
        self._accumulate_stats(status, now)

    def _accumulate_stats(self, status, now: float) -> None:
        """Credits whatever profiles were actually active this tick with
        the real elapsed time since the last one (not just the configured
        poll interval, since a slow tick or a missed sleep would otherwise
        silently under/over-count). Flushed to disk periodically rather
        than every tick -- see stats.py for why."""
        if self._last_tick_at is not None and not status.paused:
            elapsed = now - self._last_tick_at
            active = {p.name for p in status.profiles if p.scheduled_active or p.manual_active}
            if active and 0 < elapsed < 300:  # ignore absurd gaps (suspend/resume, clock jumps)
                today = date.fromtimestamp(now).isoformat()
                self._stats.add_seconds(active, elapsed, today)
        self._last_tick_at = now

        if now - self._last_stats_flush > 30:
            self._stats.save(today=date.fromtimestamp(now))
            self._last_stats_flush = now

    def _enforce_now(self) -> None:
        """Run an immediate out-of-band enforcement pass (used right after a
        command mutates state) rather than waiting for the next poll tick."""
        status = scheduler.compute_status(self.cfg, self.state)
        events = self.enforcer.tick(status.blocked_desktop_ids)
        self._handle_enforcement_events(events, time.time())
        self._prev_blocked_ids = set(status.blocked_desktop_ids)
        self._apply_website_block(status.blocked_domains)

    def _apply_website_block(self, blocked_domains) -> None:
        """Push the currently-active domain set into /etc/hosts via the
        privileged helper, but only when the set actually changed -- this
        runs every poll tick, and shelling out to sudo each time would be
        wasteful and would spam a failure notice if the sudoers rule isn't
        set up. Failure is logged and surfaced once (not every tick) via
        notify(); app-blocking keeps working regardless."""
        new_domains = set(blocked_domains)
        if new_domains == self._prev_blocked_domains:
            return
        ok, detail = apply_domain_block(new_domains)
        if ok:
            self._prev_blocked_domains = new_domains
            self._hosts_block_ok = True
            return
        log.error("failed to apply website block: %s", detail)
        if self._hosts_block_ok and self.cfg.settings.notifications_enabled:
            notify(
                "FocusGuard: website blocking unavailable",
                f"{detail} -- app blocking is unaffected",
            )
        self._hosts_block_ok = False
        # Don't update _prev_blocked_domains: keep retrying next tick, and
        # keep reporting the pre-failure set in status so the GUI/CLI aren't
        # silently wrong about what's actually blocked.

    def _handle_enforcement_events(self, events, now: float) -> None:
        """Vigi's nudge: a friendly notification the moment a blocked app is
        actually stopped, throttled per-app so a relaunch loop doesn't spam
        notifications -- enforcement itself is never throttled, only this."""
        if not self.cfg.settings.notifications_enabled:
            return
        for action, _pid, app_id in events:
            if action != "sigterm":
                continue
            last = self._last_nudge.get(app_id, 0.0)
            if now - last < mascot.NUDGE_COOLDOWN_SECONDS:
                continue
            self._last_nudge[app_id] = now
            entry = lookup_app(app_id)
            app_name = entry.name if entry else app_id
            title, body = mascot.nudge_for(app_name)
            notify(title, body, icon=mascot.asset_path())

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
            "blocked_domains": status.blocked_domains,
            "website_blocking_ok": self._hosts_block_ok,
            "profiles": profiles,
        }

    # ------------------------------------------------------ commitment mode
    def _active_profile_names(self, now: float) -> set[str]:
        status = scheduler.compute_status(self.cfg, self.state, now)
        return {p.name for p in status.profiles if p.scheduled_active or p.manual_active}

    def _check_commitment(self, key: str, commitment_seconds: float, now: float) -> Optional[dict]:
        """Gate a Stop/Pause action behind Profile.commitment_seconds, if
        any of the profiles it would affect have it set. First call starts
        the clock and refuses; the SAME action has to be sent again after
        commitment_seconds have elapsed to actually go through -- enforced
        here, in the daemon, so it can't be dodged by using the CLI instead
        of the GUI or vice versa. A pending confirmation left untouched
        expires on its own (see RuntimeState.prune_expired) rather than
        letting a stale click count as confirmation much later."""
        if commitment_seconds <= 0:
            self.state.pending_confirms.pop(key, None)
            return None

        pending = self.state.pending_confirms.get(key)
        if pending is None:
            self.state.pending_confirms[key] = PendingConfirm(
                started_at=now, expires_at=now + commitment_seconds + 60
            )
            self.state.save()
            return {
                "ok": False,
                "confirm_required": True,
                "wait_seconds": commitment_seconds,
                "error": f"Sure? Send this again in {int(commitment_seconds)}s to confirm.",
            }

        elapsed = now - pending.started_at
        if elapsed < commitment_seconds:
            return {
                "ok": False,
                "confirm_required": True,
                "wait_seconds": commitment_seconds - elapsed,
                "error": f"Still waiting -- confirm again in {int(commitment_seconds - elapsed)}s.",
            }

        del self.state.pending_confirms[key]
        self.state.save()
        return None

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
            body = f"Blocking {len(profile.blocked_apps)} app(s)"
            if profile.blocked_domains:
                body += f" and {len(profile.blocked_domains)} website(s)"
            notify(f"FocusGuard: {name} started", body)
        self._enforce_now()
        return self._cmd_status(request)

    def _cmd_stop(self, request: dict) -> dict:
        name = request.get("profile")  # optional: stop just one profile
        now = time.time()

        if name is not None and name not in self.cfg.profiles:
            return {"ok": False, "error": f"unknown profile {name!r}"}
        if name is not None:
            commitment = self.cfg.profiles[name].commitment_seconds
            key = f"stop:{name}"
        else:
            active = self._active_profile_names(now)
            commitment = max((self.cfg.profiles[n].commitment_seconds for n in active), default=0)
            key = "stop:__all__"
        gate = self._check_commitment(key, commitment, now)
        if gate is not None:
            return gate

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

        now = time.time()
        active = self._active_profile_names(now)
        commitment = max((self.cfg.profiles[n].commitment_seconds for n in active), default=0)
        gate = self._check_commitment("pause", commitment, now)
        if gate is not None:
            return gate

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
        locked = self._load_and_lock_config()
        self._enforce_now()
        return {"ok": True, "locked_profiles": locked}

    def _cmd_stats(self, request: dict) -> dict:
        today = date.today()
        return {
            "ok": True,
            "today": self._stats.today_totals(today),
            "this_week": self._stats.week_totals(today),
            "all_time": self._stats.all_time_totals(today),
        }

    _COMMANDS = {
        "status": _cmd_status,
        "start": _cmd_start,
        "stop": _cmd_stop,
        "pause": _cmd_pause,
        "resume": _cmd_resume,
        "toggle": _cmd_toggle,
        "reload": _cmd_reload,
        "stats": _cmd_stats,
    }
