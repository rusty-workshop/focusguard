import json
import time

from focusguard.common.config import Config, Profile
from focusguard.daemon.server import Daemon
from focusguard.daemon.state import ManualBlock, RuntimeState


def _make_daemon(monkeypatch, tmp_path, profiles):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    d = Daemon()
    d.cfg = Config(profiles=profiles)
    d.cfg.settings.notifications_enabled = False
    d.state = RuntimeState()
    d.cfg_path.parent.mkdir(parents=True, exist_ok=True)
    return d


def _write_config(d: Daemon, cfg: Config) -> None:
    d.cfg_path.write_text(json.dumps(cfg.to_dict()))


def test_reload_command_reverts_a_weakened_active_protected_profile(monkeypatch, tmp_path):
    d = _make_daemon(monkeypatch, tmp_path, {
        "School": Profile(name="School", blocked_apps=["x.desktop"], commitment_seconds=30),
    })
    now = time.time()
    d.state.manual_blocks.append(ManualBlock(profile="School", started_at=now, ends_at=now + 3600))

    weakened = Config(profiles={
        "School": Profile(name="School", blocked_apps=["x.desktop"], commitment_seconds=0),
    })
    _write_config(d, weakened)

    resp = d._cmd_reload({})
    assert resp["ok"] is True
    assert resp["locked_profiles"] == ["School"]
    assert d.cfg.profiles["School"].commitment_seconds == 30


def test_reload_command_accepts_edits_when_profile_not_active(monkeypatch, tmp_path):
    d = _make_daemon(monkeypatch, tmp_path, {
        "School": Profile(name="School", blocked_apps=["x.desktop"], commitment_seconds=30),
    })
    # not started -- no manual block, no schedule
    edited = Config(profiles={
        "School": Profile(name="School", blocked_apps=["x.desktop"], commitment_seconds=0),
    })
    _write_config(d, edited)

    resp = d._cmd_reload({})
    assert resp["ok"] is True
    assert resp["locked_profiles"] == []
    assert d.cfg.profiles["School"].commitment_seconds == 0


def test_reload_persists_the_reverted_config_back_to_disk(monkeypatch, tmp_path):
    # Otherwise a `systemctl --user restart` (no root needed) right after a
    # hand-edit would load the weakened value fresh, with no prior in-memory
    # config to compare against -- bypassing the lock entirely.
    d = _make_daemon(monkeypatch, tmp_path, {
        "School": Profile(name="School", blocked_apps=["x.desktop"], commitment_seconds=30),
    })
    now = time.time()
    d.state.manual_blocks.append(ManualBlock(profile="School", started_at=now, ends_at=now + 3600))

    weakened = Config(profiles={
        "School": Profile(name="School", blocked_apps=["x.desktop"], commitment_seconds=0),
    })
    _write_config(d, weakened)

    d._cmd_reload({})

    from focusguard.common.config import load_config
    on_disk = load_config(d.cfg_path)
    assert on_disk.profiles["School"].commitment_seconds == 30


def test_automatic_reload_on_file_change_also_reverts(monkeypatch, tmp_path):
    d = _make_daemon(monkeypatch, tmp_path, {
        "School": Profile(name="School", blocked_apps=["x.desktop"], commitment_seconds=30),
    })
    now = time.time()
    d.state.manual_blocks.append(ManualBlock(profile="School", started_at=now, ends_at=now + 3600))
    d._cfg_mtime = 0.0  # force _maybe_reload_config to notice a "change"

    weakened = Config(profiles={
        "School": Profile(name="School", blocked_apps=["x.desktop"], commitment_seconds=0),
    })
    _write_config(d, weakened)

    d._maybe_reload_config()
    assert d.cfg.profiles["School"].commitment_seconds == 30
