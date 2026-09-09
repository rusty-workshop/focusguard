import time
from datetime import date

from focusguard.common.config import Config, Profile
from focusguard.daemon.server import Daemon
from focusguard.daemon.state import ManualBlock, RuntimeState
from focusguard.daemon.stats import Stats


def _make_daemon(monkeypatch, tmp_path, profiles):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path / "run"))
    d = Daemon()
    d.cfg = Config(profiles=profiles)
    d.cfg.settings.notifications_enabled = False
    d.state = RuntimeState()
    d._stats = Stats()
    return d


def test_accumulate_stats_credits_active_profile_with_elapsed_time(monkeypatch, tmp_path):
    d = _make_daemon(monkeypatch, tmp_path, {"Study": Profile(name="Study", blocked_apps=["x.desktop"])})
    now = time.time()
    d.state.manual_blocks.append(ManualBlock(profile="Study", started_at=now, ends_at=now + 3600))
    from focusguard.daemon import scheduler

    status = scheduler.compute_status(d.cfg, d.state, now)
    d._last_tick_at = now - 5  # pretend 5s passed since the last tick
    d._accumulate_stats(status, now)

    today = date.fromtimestamp(now)
    assert d._stats.today_totals(today) == {"Study": 5}


def test_accumulate_stats_credits_nothing_while_paused(monkeypatch, tmp_path):
    d = _make_daemon(monkeypatch, tmp_path, {"Study": Profile(name="Study", blocked_apps=["x.desktop"])})
    now = time.time()
    d.state.manual_blocks.append(ManualBlock(profile="Study", started_at=now, ends_at=now + 3600))
    d.state.paused_until = now + 60
    from focusguard.daemon import scheduler

    status = scheduler.compute_status(d.cfg, d.state, now)
    d._last_tick_at = now - 5
    d._accumulate_stats(status, now)

    assert d._stats.today_totals(date.fromtimestamp(now)) == {}


def test_accumulate_stats_ignores_first_tick_with_no_prior_timestamp(monkeypatch, tmp_path):
    d = _make_daemon(monkeypatch, tmp_path, {"Study": Profile(name="Study", blocked_apps=["x.desktop"])})
    now = time.time()
    d.state.manual_blocks.append(ManualBlock(profile="Study", started_at=now, ends_at=now + 3600))
    from focusguard.daemon import scheduler

    status = scheduler.compute_status(d.cfg, d.state, now)
    assert d._last_tick_at is None
    d._accumulate_stats(status, now)  # first call ever -- nothing to credit yet
    assert d._stats.today_totals(date.fromtimestamp(now)) == {}
    assert d._last_tick_at == now


def test_cmd_stats_reports_today_week_and_all_time(monkeypatch, tmp_path):
    d = _make_daemon(monkeypatch, tmp_path, {"Study": Profile(name="Study")})
    today = date.today()
    d._stats.add_seconds(["Study"], 120, today.isoformat())

    resp = d._cmd_stats({})
    assert resp["ok"] is True
    assert resp["today"] == {"Study": 120}
    assert resp["this_week"] == {"Study": 120}
    assert resp["all_time"] == {"Study": 120}
