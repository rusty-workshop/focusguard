from unittest.mock import MagicMock, patch

from focusguard.daemon import hosts_apply


def test_no_helper_installed_fails_gracefully():
    with patch.object(hosts_apply, "_helper_path", return_value=None):
        ok, detail = hosts_apply.apply_domain_block(["reddit.com"])
    assert ok is False
    assert "not installed" in detail


def test_sudo_missing_fails_gracefully(tmp_path):
    with patch.object(hosts_apply, "_helper_path", return_value=tmp_path / "hosts-helper"):
        with patch.object(hosts_apply.shutil, "which", return_value=None):
            ok, detail = hosts_apply.apply_domain_block(["reddit.com"])
    assert ok is False
    assert "sudo" in detail


def test_successful_run_writes_domains_and_returns_ok(tmp_path):
    captured_argv = {}

    def fake_run(argv, **kwargs):
        captured_argv["argv"] = argv
        list_path = argv[-1]
        captured_argv["contents"] = open(list_path).read()
        return MagicMock(returncode=0, stdout="", stderr="")

    with patch.object(hosts_apply, "_helper_path", return_value=tmp_path / "hosts-helper"):
        with patch.object(hosts_apply.shutil, "which", return_value="/usr/bin/sudo"):
            with patch.object(hosts_apply.subprocess, "run", side_effect=fake_run):
                ok, detail = hosts_apply.apply_domain_block(["reddit.com", "reddit.com", "youtube.com"])

    assert ok is True
    assert detail == ""
    assert captured_argv["argv"][:2] == ["sudo", "-n"]
    assert sorted(captured_argv["contents"].split()) == ["reddit.com", "youtube.com"]


def test_helper_failure_surfaces_stderr(tmp_path):
    with patch.object(hosts_apply, "_helper_path", return_value=tmp_path / "hosts-helper"):
        with patch.object(hosts_apply.shutil, "which", return_value="/usr/bin/sudo"):
            with patch.object(
                hosts_apply.subprocess, "run",
                return_value=MagicMock(returncode=1, stdout="", stderr="sudo: a password is required"),
            ):
                ok, detail = hosts_apply.apply_domain_block(["reddit.com"])
    assert ok is False
    assert "password" in detail
