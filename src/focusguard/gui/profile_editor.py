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
from ..common.blocklists import STARTER_BLOCKLISTS
from ..common.domains import InvalidDomainError, normalize_domain
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
        super().__init__(transient_for=parent, modal=True, default_width=540, default_height=620)
        self._on_save = on_save
        self._on_delete = on_delete
        self._original_name = profile.name if profile else None
        self._blocked_apps = list(profile.blocked_apps) if profile else []
        self._blocked_domains = list(profile.blocked_domains) if profile else []

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

        sites_group = Adw.PreferencesGroup(
            title="Blocked websites",
            description="Redirected in /etc/hosts, so this works in every browser",
        )
        self._add_site_row = Adw.EntryRow(title="Add a website (e.g. reddit.com)")
        self._add_site_row.connect("entry-activated", self._on_add_domain)
        add_site_btn = Gtk.Button(icon_name="list-add-symbolic", valign=Gtk.Align.CENTER)
        add_site_btn.add_css_class("flat")
        add_site_btn.connect("clicked", self._on_add_domain)
        self._add_site_row.add_suffix(add_site_btn)
        starter_btn = Gtk.MenuButton(
            icon_name="view-list-symbolic", valign=Gtk.Align.CENTER,
            tooltip_text="Add a starter list of common distracting sites",
        )
        starter_btn.add_css_class("flat")
        starter_btn.set_popover(self._build_starter_popover())
        self._add_site_row.add_suffix(starter_btn)
        sites_group.add(self._add_site_row)

        self._sites_list_group = Adw.PreferencesGroup()
        page.add(sites_group)
        page.add(self._sites_list_group)
        self._domain_rows: dict[str, Adw.ActionRow] = {}
        self._rebuild_domain_rows()

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

        behavior_group = Adw.PreferencesGroup(
            title="Behavior", description="How this profile acts when you start or try to leave it early"
        )
        self._duration_row = Adw.SpinRow.new_with_range(1, 24 * 60, 1)
        self._duration_row.set_title("Manual duration (minutes)")
        self._duration_row.set_subtitle('Used when you start this profile from the app or CLI ("start now")')
        self._duration_row.set_value(profile.manual_duration_minutes if profile else 45)
        behavior_group.add(self._duration_row)

        self._commitment_row = Adw.SpinRow.new_with_range(0, 3600, 5)
        self._commitment_row.set_title("Commitment delay (seconds)")
        self._commitment_row.set_subtitle(
            "Stop/Pause require confirming again after this delay -- makes bailing early take real intent. 0 = off"
        )
        self._commitment_row.set_value(profile.commitment_seconds if profile else 0)
        behavior_group.add(self._commitment_row)
        page.add(behavior_group)

        if profile and on_delete:
            danger_group = Adw.PreferencesGroup(title="Danger zone")
            delete_btn = Gtk.Button(label="Delete profile")
            delete_btn.add_css_class("destructive-action")
            delete_btn.set_halign(Gtk.Align.START)
            delete_btn.connect("clicked", self._on_delete_clicked)
            danger_group.add(delete_btn)
            page.add(danger_group)

        # Adw.PreferencesPage already scrolls (and clamps its own width)
        # internally -- wrapping it in another Gtk.ScrolledWindow nested two
        # scrollers that fought each other, and the outer one didn't know
        # the page's intended width, so it let content overflow sideways
        # into a horizontal scrollbar instead of wrapping to fit.
        toolbar_view.set_content(page)
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

    def _build_starter_popover(self) -> Gtk.Popover:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=8,
                       margin_bottom=8, margin_start=8, margin_end=8)
        header = Gtk.Label(label="Add a starter list", xalign=0)
        header.add_css_class("heading")
        box.append(header)

        checks: list[tuple[Gtk.CheckButton, str]] = []
        for category in STARTER_BLOCKLISTS:
            check = Gtk.CheckButton(label=category)
            box.append(check)
            checks.append((check, category))

        popover = Gtk.Popover()
        add_btn = Gtk.Button(label="Add selected", margin_top=4)
        add_btn.add_css_class("suggested-action")

        def on_add(*_args) -> None:
            for check, category in checks:
                if not check.get_active():
                    continue
                for domain in STARTER_BLOCKLISTS[category]:
                    if domain not in self._blocked_domains:
                        self._blocked_domains.append(domain)
                check.set_active(False)
            self._blocked_domains.sort()
            self._rebuild_domain_rows()
            popover.popdown()

        add_btn.connect("clicked", on_add)
        box.append(add_btn)
        popover.set_child(box)
        return popover

    def _rebuild_domain_rows(self) -> None:
        for row in list(self._domain_rows.values()):
            self._sites_list_group.remove(row)
        self._domain_rows = {}
        for domain in self._blocked_domains:
            row = Adw.ActionRow(title=domain)
            remove_btn = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
            remove_btn.add_css_class("flat")
            remove_btn.connect("clicked", self._on_remove_domain, domain)
            row.add_suffix(remove_btn)
            self._sites_list_group.add(row)
            self._domain_rows[domain] = row

    def _on_add_domain(self, *_args) -> None:
        raw = self._add_site_row.get_text().strip()
        self._add_site_row.remove_css_class("error")
        if not raw:
            return
        try:
            domain = normalize_domain(raw)
        except InvalidDomainError:
            self._add_site_row.add_css_class("error")
            return
        self._add_site_row.set_text("")
        if domain in self._blocked_domains:
            return
        self._blocked_domains.append(domain)
        self._blocked_domains.sort()
        self._rebuild_domain_rows()

    def _on_remove_domain(self, _btn, domain: str) -> None:
        self._blocked_domains.remove(domain)
        self._rebuild_domain_rows()

    def _open_picker(self, *_args) -> None:
        def done(selected_ids):
            self._blocked_apps = selected_ids
            self._update_apps_row()

        picker = AppPickerWindow(self, set(self._blocked_apps), done)
        picker.present()

    def _on_delete_clicked(self, *_args) -> None:
        if not (self._on_delete and self._original_name):
            return
        name = self._original_name
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=f"Delete “{name}”?",
            body="This removes the profile and its schedule permanently. This can't be undone.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")

        def on_response(_dialog, response: str) -> None:
            if response == "delete":
                self.close()
                self._on_delete(name)

        dialog.connect("response", on_response)
        dialog.present()

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
            blocked_domains=list(self._blocked_domains),
            schedule=schedule,
            manual_duration_minutes=int(self._duration_row.get_value()),
            commitment_seconds=int(self._commitment_row.get_value()),
        )
        self.close()
        self._on_save(profile)
