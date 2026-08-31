from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw  # noqa: E402

from .window import MainWindow

APP_ID = "io.github.rustychaffin.FocusGuard"


class FocusGuardApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self._window: MainWindow | None = None

    def do_activate(self) -> None:
        if self._window is None:
            self._window = MainWindow(self)
        self._window.present()
