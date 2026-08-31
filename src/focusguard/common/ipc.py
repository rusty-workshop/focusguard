"""Unix-socket control protocol between the daemon and GUI/CLI.

Wire format: one JSON object per line (UTF-8, newline-terminated) each way.
Requests are ``{"cmd": <name>, ...args}``; the daemon only ever recognizes a
fixed whitelist of command names (see daemon/server.py) and validates every
argument's type/range before acting -- there is no way to make it run
arbitrary code or a shell command through this channel.
"""
from __future__ import annotations

import json
import socket

from . import paths

RECV_BUFFER = 65536
CONNECT_TIMEOUT = 3.0


class IpcError(RuntimeError):
    pass


def send_request(request: dict, timeout: float = CONNECT_TIMEOUT) -> dict:
    """Connect to the daemon's control socket, send one request, and return
    its JSON response. Raises IpcError if the daemon isn't reachable."""
    sock_path = paths.socket_path()
    if not sock_path.exists():
        raise IpcError(
            "FocusGuard daemon is not running (no socket at "
            f"{sock_path}). Start it with: systemctl --user start focusguard"
        )
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.connect(str(sock_path))
            sock.sendall((json.dumps(request) + "\n").encode("utf-8"))
            sock.shutdown(socket.SHUT_WR)
            chunks = []
            while True:
                chunk = sock.recv(RECV_BUFFER)
                if not chunk:
                    break
                chunks.append(chunk)
        except OSError as exc:
            raise IpcError(f"could not talk to FocusGuard daemon: {exc}") from exc
    data = b"".join(chunks).decode("utf-8").strip()
    if not data:
        raise IpcError("empty response from daemon")
    try:
        return json.loads(data)
    except json.JSONDecodeError as exc:
        raise IpcError(f"malformed response from daemon: {exc}") from exc
