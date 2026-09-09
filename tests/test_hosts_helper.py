"""Exercises packaging/focusguard-hosts-helper as a real subprocess (not
imported), since that's how it actually runs -- invoked by sudo, never
imported by the daemon. FOCUSGUARD_HOSTS_PATH redirects it at a throwaway
file so this never touches the real /etc/hosts and needs no root."""
import os
import subprocess
import sys
from pathlib import Path

HELPER = Path(__file__).resolve().parents[1] / "packaging" / "focusguard-hosts-helper"
SRC = Path(__file__).resolve().parents[1] / "src"


def _run(hosts_path: Path, domains: list[str]) -> subprocess.CompletedProcess:
    list_file = hosts_path.with_suffix(".domains.txt")
    list_file.write_text("\n".join(domains) + ("\n" if domains else ""))
    env = dict(os.environ)
    env["FOCUSGUARD_HOSTS_PATH"] = str(hosts_path)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(
        [sys.executable, str(HELPER), str(list_file)],
        capture_output=True, text=True, timeout=10, env=env,
    )


def test_helper_adds_managed_block(tmp_path):
    hosts = tmp_path / "hosts"
    hosts.write_text("127.0.0.1 localhost\n")
    result = _run(hosts, ["reddit.com"])
    assert result.returncode == 0, result.stderr
    content = hosts.read_text()
    assert "0.0.0.0 reddit.com" in content
    assert "127.0.0.1 localhost" in content


def test_helper_removes_block_when_given_no_domains(tmp_path):
    hosts = tmp_path / "hosts"
    hosts.write_text("127.0.0.1 localhost\n")
    _run(hosts, ["reddit.com"])
    result = _run(hosts, [])
    assert result.returncode == 0, result.stderr
    assert "reddit.com" not in hosts.read_text()
    assert "127.0.0.1 localhost" in hosts.read_text()


def test_helper_rejects_malformed_domain_and_leaves_file_untouched(tmp_path):
    hosts = tmp_path / "hosts"
    original = "127.0.0.1 localhost\n"
    hosts.write_text(original)
    result = _run(hosts, ["not a domain; rm -rf /"])
    assert result.returncode != 0
    assert hosts.read_text() == original


def test_helper_wrong_argument_count_exits_nonzero(tmp_path):
    hosts = tmp_path / "hosts"
    hosts.write_text("127.0.0.1 localhost\n")
    env = dict(os.environ)
    env["FOCUSGUARD_HOSTS_PATH"] = str(hosts)
    env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, str(HELPER)], capture_output=True, text=True, timeout=10, env=env,
    )
    assert result.returncode == 2
