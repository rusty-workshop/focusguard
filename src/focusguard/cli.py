"""`focusguardctl` -- command-line control for FocusGuard, meant to be bound
to a Hyprland keybind or used from scripts.

    focusguardctl status
    focusguardctl start <profile>
    focusguardctl stop [profile]
    focusguardctl pause <minutes>
    focusguardctl resume
    focusguardctl toggle <profile>
    focusguardctl reload

Add --json *after* any command for machine-readable output (exit code is 0
on success, 1 on error either way, so it's safe to use in `&&` chains
without --json too).
"""
from __future__ import annotations

import argparse
import json
import sys

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


def _run(args: argparse.Namespace) -> int:
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

    return parser


def main(argv=None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    sys.exit(_run(args))


if __name__ == "__main__":
    main()
