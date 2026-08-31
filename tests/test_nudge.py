"""Tests for the Vigi nudge notification: fired once per blocked app per
cooldown window, never gated by (and never gating) actual enforcement."""
from unittest.mock import patch

from focusguard.common.appinfo import AppEntry
from focusguard.common.config import Config, Settings
from focusguard.daemon import server as server_mod
from focusguard.daemon.server import Daemon


def _bare_daemon(notifications_enabled=True) -> Daemon:
    # Bypass __init__ (which touches real config/state files) and wire up
    # just the attributes _handle_enforcement_events needs.
    d = object.__new__(Daemon)
    d.cfg = Config(settings=Settings(notifications_enabled=notifications_enabled))
    d._last_nudge = {}
    return d


def test_nudge_fires_once_per_sigterm_event():
    d = _bare_daemon()
    with patch.object(server_mod, "notify") as mock_notify, \
         patch.object(server_mod, "lookup_app", return_value=AppEntry("discord.desktop", "Discord", None, [])):
        d._handle_enforcement_events([("sigterm", 123, "discord.desktop")], now=1000.0)
    mock_notify.assert_called_once()
    title, body = mock_notify.call_args[0]
    assert "Discord" in body


def test_nudge_ignores_sigkill_events():
    d = _bare_daemon()
    with patch.object(server_mod, "notify") as mock_notify, \
         patch.object(server_mod, "lookup_app", return_value=AppEntry("discord.desktop", "Discord", None, [])):
        d._handle_enforcement_events([("sigkill", 123, "discord.desktop")], now=1000.0)
    mock_notify.assert_not_called()


def test_nudge_is_cooled_down_per_app():
    d = _bare_daemon()
    with patch.object(server_mod, "notify") as mock_notify, \
         patch.object(server_mod, "lookup_app", return_value=AppEntry("discord.desktop", "Discord", None, [])):
        d._handle_enforcement_events([("sigterm", 1, "discord.desktop")], now=1000.0)
        d._handle_enforcement_events([("sigterm", 2, "discord.desktop")], now=1005.0)  # too soon
    assert mock_notify.call_count == 1


def test_nudge_cooldown_is_per_app_not_global():
    d = _bare_daemon()
    def fake_lookup(app_id):
        return AppEntry(app_id, app_id.split(".")[0].capitalize(), None, [])

    with patch.object(server_mod, "notify") as mock_notify, \
         patch.object(server_mod, "lookup_app", side_effect=fake_lookup):
        d._handle_enforcement_events([("sigterm", 1, "discord.desktop")], now=1000.0)
        d._handle_enforcement_events([("sigterm", 2, "steam.desktop")], now=1001.0)
    assert mock_notify.call_count == 2


def test_nudge_resumes_after_cooldown_expires():
    d = _bare_daemon()
    with patch.object(server_mod, "notify") as mock_notify, \
         patch.object(server_mod, "lookup_app", return_value=AppEntry("discord.desktop", "Discord", None, [])):
        d._handle_enforcement_events([("sigterm", 1, "discord.desktop")], now=1000.0)
        d._handle_enforcement_events([("sigterm", 2, "discord.desktop")], now=1000.0 + 1000)  # well past cooldown
    assert mock_notify.call_count == 2


def test_no_notification_when_notifications_disabled():
    d = _bare_daemon(notifications_enabled=False)
    with patch.object(server_mod, "notify") as mock_notify, \
         patch.object(server_mod, "lookup_app", return_value=AppEntry("discord.desktop", "Discord", None, [])):
        d._handle_enforcement_events([("sigterm", 1, "discord.desktop")], now=1000.0)
    mock_notify.assert_not_called()


def test_falls_back_to_desktop_id_when_app_not_resolvable():
    d = _bare_daemon()
    with patch.object(server_mod, "notify") as mock_notify, \
         patch.object(server_mod, "lookup_app", return_value=None):
        d._handle_enforcement_events([("sigterm", 1, "mystery.desktop")], now=1000.0)
    title, body = mock_notify.call_args[0]
    assert "mystery.desktop" in body
