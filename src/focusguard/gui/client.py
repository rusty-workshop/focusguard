"""Non-blocking wrapper around common.ipc for use from the GTK main loop.

GTK's main loop and a blocking Unix-socket round trip don't mix well, so
every call runs the actual socket I/O in a short-lived background thread and
hands the result back to the caller via GLib.idle_add, which safely
marshals it onto the main thread.
"""
from __future__ import annotations

import threading
from typing import Callable

from gi.repository import GLib

from ..common.ipc import IpcError, send_request


def call_async(request: dict, callback: Callable[[dict | None, str | None], None]) -> None:
    """Fire ``request`` at the daemon in a background thread. ``callback``
    is invoked on the main loop as callback(response_or_None, error_or_None).
    """

    def worker() -> None:
        try:
            response = send_request(request)
            error = None if response.get("ok", False) else response.get("error", "unknown error")
        except IpcError as exc:
            response = None
            error = str(exc)
        GLib.idle_add(callback, response, error)

    threading.Thread(target=worker, daemon=True).start()
