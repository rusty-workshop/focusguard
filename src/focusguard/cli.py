"""`focusguardctl` -- command-line control for FocusGuard, meant to be bound
to a Hyprland keybind or used from scripts.

    focusguardctl status
    focusguardctl start <profile>
    focusguardctl stop [profile]
    focusguardctl pause <minutes>
    focusguardctl resume
    focusguardctl toggle <profile>
    focusguardctl reload
    focusguardctl doctor
    focusguardctl vigi

Add --json *after* any command for machine-readable output (exit code is 0
on success, 1 on error either way, so it's safe to use in `&&` chains
without --json too).
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys

from .common import mascot, paths
from .common.config import ConfigError, load_config
from .common.ipc import IpcError, send_request


def _print_status(data: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data))
        return
    if data.get("paused"):
        print("PAUSED (resumes automatically)")
    elif not data.get("blocked_apps"):
        print("INACTIVE (nothing currently blocked)")
    else:
        print(f"ACTIVE - blocking {len(data['blocked_apps'])} app(s)")
    for p in data.get("profiles", []):
        print(f"  {p['name']:<20} {p['state']}")


# ---------------------------------------------------------------- doctor
def _systemctl_check(prop: str, unit: str = "focusguard.service") -> tuple[bool, str]:
    try:
        result = subprocess.run(
            ["systemctl", "--user", prop, unit],
            capture_output=True, text=True, timeout=3, check=False,
        )
        return result.returncode == 0, (result.stdout or result.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def _run_doctor_checks() -> list[tuple[str, bool, str]]:
    """Runs every check unconditionally (rather than stopping at the first
    failure) so a single `doctor` run surfaces everything wrong at once."""
    checks: list[tuple[str, bool, str]] = []

    try:
        cfg = load_config()
        checks.append(("config.json parses", True, f"{len(cfg.profiles)} profile(s)"))
    except ConfigError as exc:
        checks.append(("config.json parses", False, str(exc)))

    sock = paths.socket_path()
    checks.append(("daemon socket exists", sock.exists(), str(sock)))

    if sock.exists():
        mode = sock.stat().st_mode & 0o777
        checks.append(("socket permissions are 0600", mode == 0o600, oct(mode)))

    try:
        response = send_request({"cmd": "status"})
        checks.append(("daemon responds over IPC", response.get("ok", False), ""))
    except IpcError as exc:
        checks.append(("daemon responds over IPC", False, str(exc)))

    active_ok, active_detail = _systemctl_check("is-active")
    checks.append(("systemd service is active", active_ok, active_detail))
    enabled_ok, enabled_detail = _systemctl_check("is-enabled")
    checks.append(("systemd service is enabled (autostart)", enabled_ok, enabled_detail))

    rdir = paths.runtime_dir()
    rmode = rdir.stat().st_mode & 0o777
    checks.append(("runtime dir permissions are 0700", rmode == 0o700, oct(rmode)))

    notify_path = shutil.which("notify-send")
    checks.append((
        "notify-send available (optional)",
        notify_path is not None,
        notify_path or "not found -- notifications will be silently skipped",
    ))

    vigi_path = mascot.asset_path()
    checks.append(("Vigi's portrait asset is installed", vigi_path is not None, str(vigi_path or "")))

    return checks


def _cmd_doctor(as_json: bool) -> int:
    checks = _run_doctor_checks()
    # notify-send is optional -- don't fail the overall result on it alone.
    required_ok = all(ok for name, ok, _ in checks if "optional" not in name)

    if as_json:
        print(json.dumps({
            "ok": required_ok,
            "checks": [{"name": n, "ok": o, "detail": d} for n, o, d in checks],
        }))
    else:
        for name, ok, detail in checks:
            mark = "✓" if ok else "✗"
            line = f"{mark} {name}"
            if detail:
                line += f"  ({detail})"
            print(line)
        print()
        print("All required checks passed." if required_ok else "Some checks failed -- see above.")
    return 0 if required_ok else 1


# ------------------------------------------------------------------- vigi
_VIGI_ART = r"""
     .-------.
    /  o   o  \
   |     ‿     |
    \_________/
       Vigi
"""


def _cmd_vigi() -> int:
    print(_VIGI_ART)
    print(f"  {mascot.click_reaction()}")
    return 0


def _run(args: argparse.Namespace) -> int:
    if args.command == "doctor":
        return _cmd_doctor(args.json)
    if args.command == "vigi":
        return _cmd_vigi()

    request: dict = {"cmd": args.command}
    if getattr(args, "profile", None) is not None:
        request["profile"] = args.profile
    if getattr(args, "minutes", None) is not None:
        request["minutes"] = args.minutes

    try:
        response = send_request(request)
    except IpcError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if not response.get("ok", False):
        print(f"error: {response.get('error', 'unknown error')}", file=sys.stderr)
        return 1

    if args.command in ("status", "start", "stop", "pause", "resume", "toggle"):
        _print_status(response, args.json)
    elif args.json:
        print(json.dumps(response))
    return 0


def build_parser() -> argparse.ArgumentParser:
    # --json must come *after* the subcommand (`focusguardctl status --json`)
    # -- argparse subparsers reset a parent-level flag to its own default
    # when the same option is also declared at the top level, so it's only
    # declared once, per-subcommand, via this shared parent.
    json_parent = argparse.ArgumentParser(add_help=False)
    json_parent.add_argument("--json", action="store_true", help="print machine-readable JSON")

    parser = argparse.ArgumentParser(prog="focusguardctl", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="show current blocking state", parents=[json_parent])

    p_start = sub.add_parser("start", help="manually start a profile now", parents=[json_parent])
    p_start.add_argument("profile")

    p_stop = sub.add_parser(
        "stop", help="stop the active block (all profiles, or just one)", parents=[json_parent]
    )
    p_stop.add_argument("profile", nargs="?", default=None)

    p_pause = sub.add_parser("pause", help="pause all enforcement for N minutes", parents=[json_parent])
    p_pause.add_argument("minutes", type=float)

    sub.add_parser("resume", help="cancel an active pause immediately", parents=[json_parent])

    p_toggle = sub.add_parser(
        "toggle", help="start profile if inactive, stop it if active", parents=[json_parent]
    )
    p_toggle.add_argument("profile")

    sub.add_parser("reload", help="force the daemon to reload config.json from disk", parents=[json_parent])

    sub.add_parser(
        "doctor", help="check daemon/socket/systemd/config health", parents=[json_parent]
    )

    sub.add_parser("vigi", help="say hi to Vigi")

    return parser


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    sys.exit(_run(args))


if __name__ == "__main__":
    main()
