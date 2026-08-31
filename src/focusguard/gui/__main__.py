"""Entrypoint for the `focusguard` GUI."""
from __future__ import annotations

import sys

from ..common.logging_setup import setup as setup_logging


def main() -> None:
    setup_logging("focusguard")
    from .app import FocusGuardApp

    app = FocusGuardApp()
    sys.exit(app.run(sys.argv))


if __name__ == "__main__":
    main()
