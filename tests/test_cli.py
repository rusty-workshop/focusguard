from unittest.mock import patch

import pytest

from focusguard import cli
from focusguard.common.ipc import IpcError


def _main(argv):
    with pytest.raises(SystemExit) as exc_info:
        cli.main(argv)
    return exc_info.value.code


def test_status_json_output(capsys):
    with patch.object(cli, "send_request", return_value={"ok": True, "blocked_apps": [], "paused": False, "profiles": []}):
        code = _main(["status", "--json"])
    assert code == 0
    assert '"ok": true' in capsys.readouterr().out


def test_status_human_output(capsys):
    with patch.object(
        cli, "send_request",
        return_value={"ok": True, "blocked_apps": ["a.desktop"], "paused": False, "profiles": [{"name": "School", "state": "ACTIVE"}]},
    ):
        code = _main(["status"])
    assert code == 0
    out = capsys.readouterr().out
    assert "ACTIVE" in out
    assert "School" in out


def test_daemon_unreachable_exits_nonzero(capsys):
    with patch.object(cli, "send_request", side_effect=IpcError("no socket")):
        code = _main(["status"])
    assert code == 1
    assert "no socket" in capsys.readouterr().err


def test_error_response_exits_nonzero(capsys):
    with patch.object(cli, "send_request", return_value={"ok": False, "error": "unknown profile"}):
        code = _main(["start", "Nonexistent"])
    assert code == 1
    assert "unknown profile" in capsys.readouterr().err


def test_start_sends_profile_argument():
    with patch.object(cli, "send_request", return_value={"ok": True, "blocked_apps": [], "paused": False, "profiles": []}) as mock_send:
        _main(["start", "School"])
    assert mock_send.call_args[0][0] == {"cmd": "start", "profile": "School"}


def test_pause_sends_minutes_argument():
    with patch.object(cli, "send_request", return_value={"ok": True, "blocked_apps": [], "paused": True, "profiles": []}) as mock_send:
        _main(["pause", "5"])
    assert mock_send.call_args[0][0] == {"cmd": "pause", "minutes": 5.0}


def test_stop_without_profile_sends_no_profile_key():
    with patch.object(cli, "send_request", return_value={"ok": True, "blocked_apps": [], "paused": False, "profiles": []}) as mock_send:
        _main(["stop"])
    assert mock_send.call_args[0][0] == {"cmd": "stop"}


def test_json_flag_must_come_after_subcommand():
    with pytest.raises(SystemExit) as exc_info:
        cli.build_parser().parse_args(["--json", "status"])
    assert exc_info.value.code == 2
