"""Create/edit dialog for a single profile: name, blocked apps, schedule,
manual duration. Kept to one screen, no nested dialogs beyond the picker."""
from __future__ import annotations

from typing import Callable, Optional

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw  # noqa: E402

from ..common.config import Profile, Schedule
from ..common.appinfo import lookup_app
from .picker import AppPickerWindow

_DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


class ProfileEditorWindow(Adw.Window):
    def __init__(
        self,
        parent: Gtk.Window,
        profile: Optional[Profile],
        on_save: Callable[[Profile], None],
        on_delete: Optional[Callable[[str], None]] = None,
    ):
        super().__init__(transient_for=parent, modal=True, default_width=440, default_height=520)
        self._on_save = on_save
        self._on_delete = on_delete
        self._original_name = profile.name if profile else None
        self._blocked_apps = list(profile.blocked_apps) if profile else []

        self.set_title("Edit profile" if profile else "New profile")

        header = Adw.HeaderBar()
        cancel_btn = Gtk.Button(label="Cancel")
        cancel_btn.connect("clicked", lambda *_: self.close())
        header.pack_start(cancel_btn)
        save_btn = Gtk.Button(label="Save")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save_clicked)
        header.pack_end(save_btn)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)

        page = Adw.PreferencesPage()

        general_group = Adw.PreferencesGroup(title="Profile")
        self._name_row = Adw.EntryRow(title="Name")
        if profile:
            self._name_row.set_text(profile.name)
        general_group.add(self._name_row)
        page.add(general_group)

        apps_group = Adw.PreferencesGroup(title="Blocked applications")
        self._apps_row = Adw.ActionRow(title="Apps", activatable=True)
        self._apps_row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        self._apps_row.connect("activated", self._open_picker)
        self._update_apps_row()
        apps_group.add(self._apps_row)
        page.add(apps_group)

        schedule_group = Adw.PreferencesGroup(
            title="Schedule", description="Automatically block during these times"
        )
        schedule = profile.schedule if profile else Schedule()
        self._enabled_row = Adw.SwitchRow(title="Enable schedule")
        self._enabled_row.set_active(schedule.enabled)
        schedule_group.add(self._enabled_row)

        day_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4, halign=Gtk.Align.CENTER, margin_top=6, margin_bottom=6)
        self._day_buttons: list[Gtk.ToggleButton] = []
        for i, label in enumerate(_DAY_LABELS):
            btn = Gtk.ToggleButton(label=label)
            btn.set_active(i in schedule.days)
            day_box.append(btn)
            self._day_buttons.append(btn)
        day_row = Adw.ActionRow(title="Days")
        day_row.set_child(day_box)
        schedule_group.add(day_row)

        start_h, start_m = (int(x) for x in schedule.start.split(":"))
        end_h, end_m = (int(x) for x in schedule.end.split(":"))
        self._start_row, self._start_h, self._start_m = self._time_row("Start time", start_h, start_m)
        self._end_row, self._end_h, self._end_m = self._time_row("End time", end_h, end_m)
        schedule_group.add(self._start_row)
        schedule_group.add(self._end_row)
        page.add(schedule_group)

        manual_group = Adw.PreferencesGroup(
            title="Manual duration", description='Used when you start this profile from the app or CLI ("start now")'
        )
        self._duration_row = Adw.SpinRow.new_with_range(1, 24 * 60, 1)
        self._duration_row.set_title("Minutes")
        self._duration_row.set_value(profile.manual_duration_minutes if profile else 45)
        manual_group.add(self._duration_row)
        page.add(manual_group)

        if profile and on_delete:
            danger_group = Adw.PreferencesGroup()
            delete_btn = Gtk.Button(label="Delete profile")
            delete_btn.add_css_class("destructive-action")
            delete_btn.set_halign(Gtk.Align.START)
            delete_btn.connect("clicked", self._on_delete_clicked)
            danger_group.add(delete_btn)
            page.add(danger_group)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(page)
        toolbar_view.set_content(scroller)
        self.set_content(toolbar_view)

    def _time_row(self, title: str, hour: int, minute: int):
        row = Adw.ActionRow(title=title)
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        h_spin = Gtk.SpinButton.new_with_range(0, 23, 1)
        h_spin.set_value(hour)
        h_spin.set_numeric(True)
        colon = Gtk.Label(label=":")
        m_spin = Gtk.SpinButton.new_with_range(0, 59, 1)
        m_spin.set_value(minute)
        m_spin.set_numeric(True)
        box.append(h_spin)
        box.append(colon)
        box.append(m_spin)
        row.add_suffix(box)
        return row, h_spin, m_spin

    def _update_apps_row(self) -> None:
        n = len(self._blocked_apps)
        if n == 0:
            self._apps_row.set_subtitle("None selected")
        else:
            names = []
            for app_id in self._blocked_apps[:3]:
                entry = lookup_app(app_id)
                names.append(entry.name if entry else app_id)
            more = f" +{n - 3} more" if n > 3 else ""
            self._apps_row.set_subtitle(", ".join(names) + more)

    def _open_picker(self, *_args) -> None:
        def done(selected_ids):
            self._blocked_apps = selected_ids
            self._update_apps_row()

        picker = AppPickerWindow(self, set(self._blocked_apps), done)
        picker.present()

    def _on_delete_clicked(self, *_args) -> None:
        self.close()
        if self._on_delete and self._original_name:
            self._on_delete(self._original_name)

    def _on_save_clicked(self, *_args) -> None:
        name = self._name_row.get_text().strip()
        if not name:
            self._name_row.add_css_class("error")
            return
        days = [i for i, btn in enumerate(self._day_buttons) if btn.get_active()]
        schedule = Schedule(
            enabled=self._enabled_row.get_active(),
            days=days,
            start=f"{int(self._start_h.get_value()):02d}:{int(self._start_m.get_value()):02d}",
            end=f"{int(self._end_h.get_value()):02d}:{int(self._end_m.get_value()):02d}",
        )
        profile = Profile(
            name=name,
            blocked_apps=list(self._blocked_apps),
            schedule=schedule,
            manual_duration_minutes=int(self._duration_row.get_value()),
        )
        self.close()
        self._on_save(profile)
