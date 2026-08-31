"""Entrypoint for the `focusguardd` background service."""
from __future__ import annotations

import asyncio
import logging
import signal

from ..common.logging_setup import setup as setup_logging
from .server import Daemon

log = logging.getLogger(__name__)


async def _amain() -> None:
    daemon = Daemon()
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_signal(sig_num: int) -> None:
        log.info("received signal %s, shutting down", signal.Signals(sig_num).name)
        stop_event.set()

    for sig_num in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig_num, _handle_signal, sig_num)

    run_task = asyncio.ensure_future(daemon.run())
    stop_task = asyncio.ensure_future(stop_event.wait())
    done, pending = await asyncio.wait({run_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
    for task in pending:
        task.cancel()
    for task in done:
        exc = task.exception() if not task.cancelled() else None
        if exc:
            raise exc


def main() -> None:
    setup_logging("focusguardd")
    log.info("FocusGuard daemon starting")
    try:
        asyncio.run(_amain())
    except KeyboardInterrupt:
        pass
    log.info("FocusGuard daemon stopped")


if __name__ == "__main__":
    main()
