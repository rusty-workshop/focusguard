"""Entrypoint for the `focusguard` GUI."""
from __future__ import annotations

import sys

from ..common.logging_setup import setup as setup_logging


def main() -> None:
    setup_logging("focusguard")
    from .app import FocusGuardApp

    app = FocusGuardApp()
    # FocusGuard's GUI has no document model and doesn't accept file/URI
    # arguments -- only argv[0] (the program name) is passed to GApplication
    # so it never tries to interpret stray positional args (e.g. a typo'd
    # `focusguard ctl vigi` instead of `focusguardctl vigi`) as files to
    # open, which otherwise logs a cryptic "can not open files" critical.
    sys.exit(app.run(sys.argv[:1]))


if __name__ == "__main__":
    main()
