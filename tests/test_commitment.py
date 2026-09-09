"""Profile.commitment_seconds: Stop/Pause against a protected profile must
be requested twice, commitment_seconds apart, before it actually goes
through. Enforced in the daemon (not the GUI) so it can't be dodged by
using the CLI instead of clicking through the GUI's own countdown.
"""
import time

import pytest

from focusguard.common.config import Config, Profile, Schedule
from focusguard.daemon.server import Daemon
from focusguard.daemon.state import ManualBlock, RuntimeState


def _make_daemon(monkeypatch, tmp_path, profiles):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    d = Daemon()
    d.cfg = Config(profiles=profiles)
    d.cfg.settings.notifications_enabled = False  # keep tests quiet
    d.state = RuntimeState()
    return d


def _active_profile(name="Study", commitment_seconds=0):
    return Profile(name=name, blocked_apps=["x.desktop"], commitment_seconds=commitment_seconds)


def test_stop_with_no_commitment_is_immediate(monkeypatch, tmp_path):
    d = _make_daemon(monkeypatch, tmp_path, {"Study": _active_profile(commitment_seconds=0)})
    now = time.time()
    d.state.manual_blocks.append(ManualBlock(profile="Study", started_at=now, ends_at=now + 60))

    resp = d._cmd_stop({"profile": "Study"})
    assert resp["ok"] is True
    assert not any(m.profile == "Study" for m in d.state.manual_blocks)


def test_stop_with_commitment_requires_second_call_after_delay(monkeypatch, tmp_path):
    d = _make_daemon(monkeypatch, tmp_path, {"Study": _active_profile(commitment_seconds=30)})
    now = time.time()
    d.state.manual_blocks.append(ManualBlock(profile="Study", started_at=now, ends_at=now + 3600))

    monkeypatch.setattr(time, "time", lambda: now)
    first = d._cmd_stop({"profile": "Study"})
    assert first["ok"] is False
    assert first["confirm_required"] is True
    assert first["wait_seconds"] == pytest.approx(30)
    # the block must still be fully active -- nothing happened yet
    assert any(m.profile == "Study" for m in d.state.manual_blocks)

    # asking again immediately (impatient retry) still refuses
    second = d._cmd_stop({"profile": "Study"})
    assert second["ok"] is False
    assert second["confirm_required"] is True
    assert second["wait_seconds"] == pytest.approx(30)

    # after the commitment window elapses, the same request goes through
    monkeypatch.setattr(time, "time", lambda: now + 31)
    third = d._cmd_stop({"profile": "Study"})
    assert third["ok"] is True
    assert not any(m.profile == "Study" for m in d.state.manual_blocks)


def test_stop_all_uses_the_strictest_commitment_among_active_profiles(monkeypatch, tmp_path):
    d = _make_daemon(
        monkeypatch, tmp_path,
        {
            "Study": _active_profile("Study", commitment_seconds=10),
            "Gaming": _active_profile("Gaming", commitment_seconds=60),
        },
    )
    now = time.time()
    d.state.manual_blocks.append(ManualBlock(profile="Study", started_at=now, ends_at=now + 3600))
    d.state.manual_blocks.append(ManualBlock(profile="Gaming", started_at=now, ends_at=now + 3600))

    monkeypatch.setattr(time, "time", lambda: now)
    resp = d._cmd_stop({})  # no profile = stop everything active
    assert resp["ok"] is False
    assert resp["wait_seconds"] == pytest.approx(60)  # the stricter of the two

    monkeypatch.setattr(time, "time", lambda: now + 15)  # past Study's 10s, not Gaming's 60s
    still_waiting = d._cmd_stop({})
    assert still_waiting["ok"] is False

    monkeypatch.setattr(time, "time", lambda: now + 61)
    resp2 = d._cmd_stop({})
    assert resp2["ok"] is True
    assert d.state.manual_blocks == []


def test_pause_is_gated_by_currently_active_profiles_commitment(monkeypatch, tmp_path):
    d = _make_daemon(monkeypatch, tmp_path, {"Study": _active_profile(commitment_seconds=20)})
    now = time.time()
    d.state.manual_blocks.append(ManualBlock(profile="Study", started_at=now, ends_at=now + 3600))

    monkeypatch.setattr(time, "time", lambda: now)
    first = d._cmd_pause({"minutes": 5})
    assert first["ok"] is False
    assert first["confirm_required"] is True
    assert d.state.paused_until is None

    monkeypatch.setattr(time, "time", lambda: now + 21)
    second = d._cmd_pause({"minutes": 5})
    assert second["ok"] is True
    assert d.state.paused_until is not None


def test_pause_with_no_active_commitment_profile_is_immediate(monkeypatch, tmp_path):
    # A commitment_seconds profile that ISN'T currently active shouldn't
    # gate pausing something else entirely.
    d = _make_daemon(
        monkeypatch, tmp_path,
        {
            "Locked": _active_profile("Locked", commitment_seconds=999),  # not active
            "Free": _active_profile("Free", commitment_seconds=0),
        },
    )
    now = time.time()
    d.state.manual_blocks.append(ManualBlock(profile="Free", started_at=now, ends_at=now + 3600))
    resp = d._cmd_pause({"minutes": 5})
    assert resp["ok"] is True


def test_pending_confirmation_expires_if_never_repeated(monkeypatch, tmp_path):
    d = _make_daemon(monkeypatch, tmp_path, {"Study": _active_profile(commitment_seconds=10)})
    now = time.time()
    d.state.manual_blocks.append(ManualBlock(profile="Study", started_at=now, ends_at=now + 3600))

    monkeypatch.setattr(time, "time", lambda: now)
    d._cmd_stop({"profile": "Study"})
    assert "stop:Study" in d.state.pending_confirms

    # long after the confirmation window closed, prune_expired should drop it
    d.state.prune_expired(now + 10_000)
    assert "stop:Study" not in d.state.pending_confirms


def test_starting_a_profile_is_never_gated_by_commitment(monkeypatch, tmp_path):
    # Friction only applies to getting OUT early -- starting a block, even
    # one with commitment_seconds set, must never require confirmation.
    d = _make_daemon(monkeypatch, tmp_path, {"Study": _active_profile(commitment_seconds=999)})
    resp = d._cmd_start({"profile": "Study"})
    assert resp["ok"] is True
    assert any(m.profile == "Study" for m in d.state.manual_blocks)
