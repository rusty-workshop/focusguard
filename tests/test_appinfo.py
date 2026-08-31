"""Tests for .desktop signature resolution and discovery filtering.

Two GLib quirks drive how these tests are built:

1. Gio.DesktopAppInfo refuses to construct an entry at all (returns NULL /
   raises TypeError from the Python binding) unless the literal first Exec
   token actually resolves to an existing, executable file -- not just a
   should_show()/TryExec filter applied afterwards. So every fixture here
   points Exec at a small real script written into the test's own tmp dir.
2. GLib resolves $XDG_DATA_HOME/$XDG_DATA_DIRS once per process and caches
   it, so these tests spawn a short-lived subprocess per case with
   XDG_DATA_HOME pointed at a temp dir *before* Python starts. That's the
   same discovery path (Gio.AppInfo.get_all() / Gio.DesktopAppInfo.new())
   list_installed_apps()/lookup_app() use in production, just hermetic.
"""
import json
import os
import stat
import subprocess
import sys
import textwrap

import pytest

gi = pytest.importorskip("gi")

SRC_DIR = os.path.join(os.path.dirname(__file__), "..", "src")


def _make_fake_binary(tmp_path, name) -> str:
    path = tmp_path / name
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return str(path)


def _run(tmp_path, desktop_filename, desktop_content, script):
    apps_dir = tmp_path / "applications"
    apps_dir.mkdir(parents=True, exist_ok=True)
    (apps_dir / desktop_filename).write_text(textwrap.dedent(desktop_content))

    env = dict(os.environ)
    env["XDG_DATA_HOME"] = str(tmp_path)
    env["PYTHONPATH"] = SRC_DIR + os.pathsep + env.get("PYTHONPATH", "")

    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env, capture_output=True, text=True, timeout=15,
    )
    assert result.returncode == 0, f"stdout={result.stdout!r} stderr={result.stderr!r}"
    return json.loads(result.stdout)


_LOOKUP_SCRIPT = textwrap.dedent("""
    import json, sys
    from focusguard.common import appinfo
    entry = appinfo.lookup_app(sys.argv[1] if len(sys.argv) > 1 else %r)
    print(json.dumps(sorted(entry.signatures) if entry else None))
""")

_LIST_IDS_SCRIPT = textwrap.dedent("""
    import json
    from focusguard.common import appinfo
    print(json.dumps([e.id for e in appinfo.list_installed_apps()]))
""")


def test_simple_app_resolves_basename_signature(tmp_path):
    binary = _make_fake_binary(tmp_path, "vivaldi-test-binary")
    sigs = _run(tmp_path, "vivaldi-test.desktop", f"""\
        [Desktop Entry]
        Type=Application
        Name=Vivaldi Test
        Exec={binary} %U
        Icon=vivaldi
        """, _LOOKUP_SCRIPT % "vivaldi-test.desktop")
    assert sigs is not None
    assert "vivaldi-test-binary" in sigs


def test_wrapper_script_does_not_produce_generic_signature(tmp_path):
    # "env" is a real, always-present binary -- exactly the wrapper case we
    # must not treat as a standalone signature (it would match nearly every
    # other process on the system).
    sigs = _run(tmp_path, "wrapped-test.desktop", """\
        [Desktop Entry]
        Type=Application
        Name=Wrapped Test
        Exec=env SOME_VAR=1 /usr/bin/env-wrapped-binary-that-does-not-exist
        """, _LOOKUP_SCRIPT % "wrapped-test.desktop")
    assert sigs is not None
    for generic in ("env", "sh", "bash"):
        assert generic not in sigs


def test_flatpak_exec_extracts_app_id_not_the_run_subcommand(tmp_path):
    flatpak_bin = _make_fake_binary(tmp_path, "flatpak")
    sigs = _run(tmp_path, "com.example.Flat.desktop", f"""\
        [Desktop Entry]
        Type=Application
        Name=Flat Example
        Exec={flatpak_bin} run --branch=stable --arch=x86_64 com.example.Flat
        """, _LOOKUP_SCRIPT % "com.example.Flat.desktop")
    assert sigs is not None
    assert "com.example.Flat" in sigs
    assert "run" not in sigs  # must not mistake the flatpak subcommand for the app id


def test_hidden_app_is_not_listed(tmp_path):
    binary = _make_fake_binary(tmp_path, "hidden-test-binary")
    ids = _run(tmp_path, "hidden-test.desktop", f"""\
        [Desktop Entry]
        Type=Application
        Name=Hidden Test
        Exec={binary}
        NoDisplay=true
        """, _LIST_IDS_SCRIPT)
    assert "hidden-test.desktop" not in ids


def test_visible_app_is_listed_with_name_and_signature(tmp_path):
    binary = _make_fake_binary(tmp_path, "visible-test-binary")
    sigs = _run(tmp_path, "visible-test.desktop", f"""\
        [Desktop Entry]
        Type=Application
        Name=Visible Test
        Exec={binary}
        """, textwrap.dedent("""
            import json
            from focusguard.common import appinfo
            apps = {e.id: e.signatures for e in appinfo.list_installed_apps()}
            print(json.dumps(apps.get("visible-test.desktop")))
        """))
    assert sigs is not None
    assert "visible-test-binary" in sigs


def test_link_type_entry_is_not_listed(tmp_path):
    ids = _run(tmp_path, "link-test.desktop", """\
        [Desktop Entry]
        Type=Link
        Name=Some Website
        URL=https://example.com
        """, _LIST_IDS_SCRIPT)
    assert "link-test.desktop" not in ids


def test_nonexistent_exec_target_is_not_a_valid_app_at_all(tmp_path):
    # GLib itself refuses to construct a DesktopAppInfo when the literal
    # program to run doesn't exist -- confirming such entries can never
    # reach list_installed_apps()/lookup_app() as ghosts with no signature.
    ids = _run(tmp_path, "broken-test.desktop", """\
        [Desktop Entry]
        Type=Application
        Name=Broken Test
        Exec=/nonexistent/path/to/nothing
        """, _LIST_IDS_SCRIPT)
    assert "broken-test.desktop" not in ids


def test_nonexistent_desktop_id_returns_none():
    from focusguard.common import appinfo

    assert appinfo.lookup_app("this-does-not-exist-anywhere.desktop") is None
