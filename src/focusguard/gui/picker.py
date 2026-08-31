"""The application picker: search, icons, checkboxes, Select All/Clear All."""
from __future__ import annotations

from typing import List, Set

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gio, GObject, Gtk, Adw  # noqa: E402

from ..common.appinfo import AppEntry, list_installed_apps


class AppRow(GObject.Object):
    __gtype_name__ = "FocusGuardAppRow"

    def __init__(self, entry: AppEntry, selected: bool):
        super().__init__()
        self.entry = entry
        self._selected = selected

    @GObject.Property(type=bool, default=False)
    def selected(self) -> bool:
        return self._selected

    @selected.setter
    def selected(self, value: bool) -> None:
        self._selected = value


class AppPickerWindow(Adw.Window):
    """Modal dialog: pick which installed apps a profile should block."""

    def __init__(self, parent: Gtk.Window, initially_selected: Set[str], on_done):
        super().__init__(transient_for=parent, modal=True, default_width=480, default_height=560)
        self.set_title("Choose apps to block")
        self._on_done = on_done

        self._store = Gio.ListStore(item_type=AppRow)
        for entry in list_installed_apps():
            self._store.append(AppRow(entry, entry.id in initially_selected))

        self._filter = Gtk.CustomFilter.new(self._filter_func)
        self._filtered = Gtk.FilterListModel(model=self._store, filter=self._filter)
        selection = Gtk.NoSelection(model=self._filtered)

        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._on_setup)
        factory.connect("bind", self._on_bind)

        self._list_view = Gtk.ListView(model=selection, factory=factory)
        self._list_view.add_css_class("boxed-list")

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(self._list_view)

        search_entry = Gtk.SearchEntry(placeholder_text="Search installed applications")
        search_entry.connect("search-changed", self._on_search_changed)

        select_all_btn = Gtk.Button(label="Select All")
        select_all_btn.connect("clicked", lambda *_: self._set_all(True))
        clear_all_btn = Gtk.Button(label="Clear All")
        clear_all_btn.connect("clicked", lambda *_: self._set_all(False))

        button_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_row.append(select_all_btn)
        button_row.append(clear_all_btn)

        self._count_label = Gtk.Label(xalign=0)
        self._count_label.add_css_class("dim-label")
        self._update_count()

        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda *_: self.close())
        done_btn = Gtk.Button(label="Done")
        done_btn.add_css_class("suggested-action")
        done_btn.connect("clicked", self._on_done_clicked)

        footer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6, margin_top=6)
        footer.append(self._count_label)
        spacer = Gtk.Box(hexpand=True)
        footer.append(spacer)
        footer.append(cancel_btn)
        footer.append(done_btn)

        header = Adw.HeaderBar()
        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)

        content = Gtk.Box(
            orientation=Gtk.Orientation.VERTICAL, spacing=8,
            margin_top=8, margin_bottom=8, margin_start=12, margin_end=12,
        )
        content.append(search_entry)
        content.append(button_row)
        content.append(scroller)
        content.append(footer)
        toolbar_view.set_content(content)
        self.set_content(toolbar_view)

    def _filter_func(self, row: AppRow) -> bool:
        query = self._search_text.strip().casefold() if hasattr(self, "_search_text") else ""
        if not query:
            return True
        return query in row.entry.name.casefold() or query in row.entry.id.casefold()

    def _on_search_changed(self, entry: Gtk.SearchEntry) -> None:
        self._search_text = entry.get_text()
        self._filter.changed(Gtk.FilterChange.DIFFERENT)

    def _on_setup(self, factory, list_item: Gtk.ListItem) -> None:
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10, margin_top=6, margin_bottom=6, margin_start=6, margin_end=6)
        check = Gtk.CheckButton()
        icon = Gtk.Image(pixel_size=32)
        label = Gtk.Label(xalign=0, hexpand=True)
        box.append(check)
        box.append(icon)
        box.append(label)
        list_item.set_child(box)
        list_item._check = check
        list_item._icon = icon
        list_item._label = label

    def _on_bind(self, factory, list_item: Gtk.ListItem) -> None:
        row: AppRow = list_item.get_item()
        list_item._label.set_text(row.entry.name)
        if row.entry.icon is not None:
            list_item._icon.set_from_gicon(row.entry.icon)
        else:
            list_item._icon.set_from_icon_name("application-x-executable-symbolic")
        list_item._check.set_active(row.selected)

        def on_toggled(check, r=row):
            r.selected = check.get_active()
            self._update_count()

        # Avoid stacking handlers across rebinds of a recycled ListItem.
        handler_id = getattr(list_item, "_handler_id", None)
        if handler_id is not None:
            list_item._check.disconnect(handler_id)
        list_item._handler_id = list_item._check.connect("toggled", on_toggled)

    def _set_all(self, value: bool) -> None:
        for i in range(self._store.get_n_items()):
            self._store.get_item(i).selected = value
        self._list_view.set_model(None)
        self._list_view.set_model(Gtk.NoSelection(model=self._filtered))
        self._update_count()

    def _update_count(self) -> None:
        n = sum(1 for i in range(self._store.get_n_items()) if self._store.get_item(i).selected)
        self._count_label.set_text(f"{n} selected")

    def _on_done_clicked(self, *_args) -> None:
        selected_ids: List[str] = [
            self._store.get_item(i).entry.id
            for i in range(self._store.get_n_items())
            if self._store.get_item(i).selected
        ]
        self.close()
        self._on_done(selected_ids)
