"""Main FocusGuard window: live status + profile management.

The GUI never enforces anything itself -- it only edits config.json and
sends control commands to focusguardd over the IPC socket, then polls
`status` every couple seconds to reflect ground truth back to the user.
"""
from __future__ import annotations

import logging
import math
import random
import time
from datetime import datetime

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("Gdk", "4.0")
from gi.repository import Adw, Gdk, GLib, Gtk  # noqa: E402

from ..common import mascot
from ..common.appinfo import lookup_app
from ..common.config import Config, ConfigError, Profile, load_config, save_config
from . import client
from .profile_editor import ProfileEditorWindow

log = logging.getLogger(__name__)

STATUS_POLL_INTERVAL_MS = 2000

# How long the window has to sit open with no state change before Vigi
# starts making idle small talk in the speech bubble, and how often after
# that. Randomized a bit per-cycle so it doesn't feel like a metronome.
_IDLE_CHATTER_FIRST_DELAY_SECONDS = 25
_IDLE_CHATTER_MIN_INTERVAL_SECONDS = 20
_IDLE_CHATTER_MAX_INTERVAL_SECONDS = 40

# Vigi's idle animation: a combined bob + sway + tilt, recomputed every
# frame and applied as a single CSS `transform` on the picture widget
# (GTK 4.12+ supports the same transform syntax as web CSS). Because
# `transform` is paint-only and never affects layout, this can't reflow
# siblings the way animating margin/size did before.
_VIGI_BOB_AMPLITUDE_PX = 4.0
_VIGI_BOB_PERIOD_SECONDS = 2.6
_VIGI_SWAY_AMPLITUDE_PX = 2.0
_VIGI_SWAY_PERIOD_SECONDS = 4.1
_VIGI_TILT_AMPLITUDE_DEG = 2.5
_VIGI_TILT_PERIOD_SECONDS = 3.3
_VIGI_SIZE = (56, 70)
_VIGI_FLOAT_PADDING = 6  # extra vertical room in the Overlay so the bob never clips

# One-off "burst" animations layered on top of the idle motion: a little
# bounce when the block state changes, a playful spin when Vigi is clicked.
_VIGI_BURSTS = {
    "pop": {"duration": 0.5},
    "spin": {"duration": 0.7},
}

#: Vigi's own brand blue (matches docs/vigi.svg's gradient) -- used directly
#: rather than a GTK theme-named color, since @accent_color/@accent_bg_color
#: turned out not to reliably tint GtkLabel text/background at this specificity.
_VIGI_BLUE = (107, 138, 253)

_VIGI_CSS = (
    """
.vigi-bubble {
  background-color: rgba(%d, %d, %d, 0.16);
  border: 1px solid rgba(%d, %d, %d, 0.55);
  /* Sharper top-left corner reads as a speech-bubble notch pointing up
     toward Vigi, who sits above-and-left of this box. */
  border-radius: 4px 14px 14px 14px;
  padding: 6px 10px;
}
#vigi-picture {
  transform-origin: center;
}
"""
    % (_VIGI_BLUE + _VIGI_BLUE)
).encode("ascii")
_vigi_css_installed = False


def _ensure_vigi_css() -> None:
    global _vigi_css_installed
    if _vigi_css_installed:
        return
    provider = Gtk.CssProvider()
    provider.load_from_data(_VIGI_CSS)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
    )
    _vigi_css_installed = True


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        super().__init__(application=app, default_width=460, default_height=640, title="FocusGuard")

        _ensure_vigi_css()
        self._cfg: Config = self._load_config()

        header = Adw.HeaderBar()
        add_btn = Gtk.Button(icon_name="list-add-symbolic", tooltip_text="New profile")
        add_btn.connect("clicked", self._on_add_profile)
        header.pack_end(add_btn)

        toolbar_view = Adw.ToolbarView()
        toolbar_view.add_top_bar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16, margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)

        # --- status card -----------------------------------------------
        status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        status_box.add_css_class("card")
        status_box.set_margin_top(4)
        inner = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin_top=16, margin_bottom=16, margin_start=16, margin_end=16)

        header_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        vigi_path = mascot.asset_path()
        if vigi_path is not None:
            vigi_w, vigi_h = _VIGI_SIZE
            self._vigi_picture = Gtk.Picture.new_for_filename(str(vigi_path))
            self._vigi_picture.set_content_fit(Gtk.ContentFit.CONTAIN)
            self._vigi_picture.set_size_request(vigi_w, vigi_h)
            self._vigi_picture.set_can_shrink(True)
            self._vigi_picture.set_halign(Gtk.Align.CENTER)
            self._vigi_picture.set_valign(Gtk.Align.START)
            self._vigi_picture.set_margin_top(_VIGI_FLOAT_PADDING)
            self._vigi_picture.set_name("vigi-picture")  # CSS #vigi-picture target
            self._vigi_picture.set_cursor_from_name("pointer")
            self._vigi_picture.set_tooltip_text("Hi! Give me a click.")

            self._vigi_transform_provider = Gtk.CssProvider()
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(),
                self._vigi_transform_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
            self._vigi_burst: dict | None = None

            click = Gtk.GestureClick()
            click.connect("released", self._on_vigi_clicked)
            self._vigi_picture.add_controller(click)

            # A fixed-size, invisible spacer establishes the layout footprint;
            # Vigi rides on top of it as an *overlay* child. GtkOverlay's own
            # measurement only ever depends on this main child, so nudging
            # the picture's margin every frame (the float) never changes the
            # overlay's reported size -- unlike GtkFixed, whose size tracks
            # each child's bounding box and previously made the whole header
            # row (and the buttons below it) visibly bob along with Vigi.
            spacer = Gtk.Box()
            spacer.set_size_request(vigi_w, vigi_h + 2 * _VIGI_FLOAT_PADDING)
            self._vigi_overlay = Gtk.Overlay()
            self._vigi_overlay.set_child(spacer)
            self._vigi_overlay.add_overlay(self._vigi_picture)
            self._vigi_overlay.add_tick_callback(self._on_vigi_tick)
            header_row.append(self._vigi_overlay)
        else:
            self._vigi_picture = None
            self._vigi_overlay = None
            self._vigi_burst = None
            self._vigi_transform_provider = None

        title_col = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4, hexpand=True)
        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._status_dot = Gtk.Label(label="●")
        self._status_title = Gtk.Label(label="Loading...", xalign=0)
        self._status_title.add_css_class("title-2")
        title_row.append(self._status_dot)
        title_row.append(self._status_title)
        title_col.append(title_row)

        self._status_detail = Gtk.Label(label="", xalign=0, wrap=True)
        self._status_detail.add_css_class("dim-label")
        title_col.append(self._status_detail)

        # Vigi's speech bubble: a small bold name-tag + an italic, quoted
        # line, inside a notched, tinted box -- reads unambiguously as
        # "character speaking" rather than a second status label.
        self._vigi_bubble = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self._vigi_bubble.add_css_class("vigi-bubble")
        name_color = "#%02x%02x%02x" % _VIGI_BLUE
        vigi_name_label = Gtk.Label(valign=Gtk.Align.START)
        vigi_name_label.set_markup(
            f'<b><span color="{name_color}">{GLib.markup_escape_text(mascot.NAME)}</span></b>'
        )
        vigi_name_label.add_css_class("caption")
        self._vigi_bubble.append(vigi_name_label)
        self._vigi_message_label = Gtk.Label(xalign=0, wrap=True, hexpand=True)
        self._vigi_message_label.add_css_class("caption")
        self._vigi_bubble.append(self._vigi_message_label)
        title_col.append(self._vigi_bubble)

        header_row.append(title_col)
        inner.append(header_row)

        action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, margin_top=8)
        self._pause_btn = Gtk.Button(label="Pause 5 min")
        self._pause_btn.connect("clicked", self._on_pause)
        self._stop_btn = Gtk.Button(label="Stop Mode")
        self._stop_btn.add_css_class("destructive-action")
        self._stop_btn.connect("clicked", self._on_stop)
        self._resume_btn = Gtk.Button(label="Resume now")
        self._resume_btn.connect("clicked", self._on_resume)
        action_row.append(self._pause_btn)
        action_row.append(self._stop_btn)
        action_row.append(self._resume_btn)
        inner.append(action_row)

        status_box.append(inner)
        root.append(status_box)

        # --- profiles list ------------------------------------------------
        profiles_label = Gtk.Label(label="Profiles", xalign=0)
        profiles_label.add_css_class("heading")
        root.append(profiles_label)

        self._profiles_group = Adw.PreferencesGroup()
        root.append(self._profiles_group)

        scroller = Gtk.ScrolledWindow(vexpand=True)
        scroller.set_child(root)
        toolbar_view.set_content(scroller)
        self.set_content(toolbar_view)

        self._last_status: dict | None = None
        self._last_vigi_state_key: str | None = None
        self.refresh_status()
        GLib.timeout_add(STATUS_POLL_INTERVAL_MS, self._on_poll_tick)
        self._rebuild_profile_rows()

        GLib.timeout_add_seconds(_IDLE_CHATTER_FIRST_DELAY_SECONDS, self._on_vigi_chatter)

    # ------------------------------------------------------------- config
    def _load_config(self) -> Config:
        try:
            return load_config()
        except ConfigError as exc:
            log.error("failed to load config: %s", exc)
            return Config()

    def _save_config(self) -> None:
        try:
            save_config(self._cfg)
        except ConfigError as exc:
            self._show_error(f"Could not save configuration: {exc}")
            return
        client.call_async({"cmd": "reload"}, lambda resp, err: None)

    def _show_error(self, message: str) -> None:
        dialog = Adw.MessageDialog(
            transient_for=self, heading="FocusGuard", body=message
        )
        dialog.add_response("ok", "OK")
        dialog.present()

    # ------------------------------------------------------------- mascot
    def _set_vigi_says(self, message: str) -> None:
        escaped = GLib.markup_escape_text(message)
        self._vigi_message_label.set_markup(f"<i>“{escaped}”</i>")

    def _trigger_vigi_burst(self, kind: str) -> None:
        if self._vigi_picture is not None:
            self._vigi_burst = {"kind": kind, "start": time.monotonic()}

    def _on_vigi_clicked(self, gesture: Gtk.GestureClick, n_press: int, x: float, y: float) -> None:
        self._trigger_vigi_burst("spin")
        self._set_vigi_says(mascot.click_reaction())

    def _on_vigi_tick(self, widget: Gtk.Overlay, frame_clock: Gdk.FrameClock) -> bool:
        t = time.monotonic()
        bob = _VIGI_BOB_AMPLITUDE_PX * math.sin(2 * math.pi * t / _VIGI_BOB_PERIOD_SECONDS)
        sway = _VIGI_SWAY_AMPLITUDE_PX * math.sin(2 * math.pi * t / _VIGI_SWAY_PERIOD_SECONDS + 1.3)
        tilt = _VIGI_TILT_AMPLITUDE_DEG * math.sin(2 * math.pi * t / _VIGI_TILT_PERIOD_SECONDS + 0.7)

        extra_y = extra_rot = 0.0
        extra_scale = 1.0
        if self._vigi_burst is not None:
            elapsed = t - self._vigi_burst["start"]
            spec = _VIGI_BURSTS[self._vigi_burst["kind"]]
            if elapsed >= spec["duration"]:
                self._vigi_burst = None
            else:
                p = elapsed / spec["duration"]
                if self._vigi_burst["kind"] == "pop":
                    # a single quick bounce in scale, peaking mid-way through
                    extra_scale = 1 + 0.22 * math.sin(p * math.pi)
                elif self._vigi_burst["kind"] == "spin":
                    eased = 1 - (1 - p) ** 3  # ease-out cubic
                    extra_rot = 360 * eased
                    extra_y = -14 * math.sin(p * math.pi)  # a little hop mid-spin

        css = (
            "#vigi-picture { transform: "
            f"translate({sway:.2f}px, {bob + extra_y:.2f}px) "
            f"rotate({tilt + extra_rot:.2f}deg) "
            f"scale({extra_scale:.3f}); }}"
        ).encode("ascii")
        self._vigi_transform_provider.load_from_data(css)
        return GLib.SOURCE_CONTINUE

    def _on_vigi_chatter(self) -> bool:
        """Swap the speech bubble to idle small talk if the window's been
        sitting open a while. Doesn't touch title/detail (the actual status
        info), so it's safe even if it lands mid-something-important; the
        next real state change overwrites it immediately anyway."""
        if not self.is_visible():
            return GLib.SOURCE_REMOVE
        self._set_vigi_says(mascot.idle_chatter())
        next_delay = random.randint(_IDLE_CHATTER_MIN_INTERVAL_SECONDS, _IDLE_CHATTER_MAX_INTERVAL_SECONDS)
        GLib.timeout_add_seconds(next_delay, self._on_vigi_chatter)
        return GLib.SOURCE_REMOVE  # this firing was one-shot; the line above continues the cycle

    # -------------------------------------------------------------- status
    def _on_poll_tick(self) -> bool:
        self.refresh_status()
        return True  # keep the GLib timeout running

    def refresh_status(self) -> None:
        client.call_async({"cmd": "status"}, self._apply_status)

    def _apply_status(self, response: dict | None, error: str | None) -> bool:
        if error or response is None:
            self._status_title.set_text("Daemon unreachable")
            self._status_detail.set_text(error or "unknown error")
            self._status_dot.set_markup('<span color="#888888">●</span>')
            self._set_vigi_says("I can't reach the daemon — is it running?")
            self._pause_btn.set_sensitive(False)
            self._stop_btn.set_sensitive(False)
            self._resume_btn.set_sensitive(False)
            return False

        self._last_status = response
        blocked = response.get("blocked_apps", [])
        paused = response.get("paused", False)

        if paused:
            until = response.get("paused_until")
            when = datetime.fromtimestamp(until).strftime("%H:%M") if until else "?"
            self._status_dot.set_markup('<span color="#f5a623">●</span>')
            self._status_title.set_text("PAUSED")
            self._status_detail.set_text(f"Enforcement paused until {when}")
            state_key = "PAUSED"
        elif blocked:
            self._status_dot.set_markup('<span color="#e01b24">●</span>')
            self._status_title.set_text(f"ACTIVE — blocking {len(blocked)} app(s)")
            names = []
            for app_id in blocked[:6]:
                entry = lookup_app(app_id)
                names.append(entry.name if entry else app_id)
            more = f" +{len(blocked) - 6} more" if len(blocked) > 6 else ""
            self._status_detail.set_text(", ".join(names) + more)
            state_key = "ACTIVE"
        else:
            self._status_dot.set_markup('<span color="#2ec27e">●</span>')
            self._status_title.set_text("INACTIVE")
            self._status_detail.set_text("Nothing is currently blocked")
            state_key = "INACTIVE"

        # Only re-roll Vigi's line when the state actually changes -- this
        # is polled every couple seconds, and re-rolling on every poll would
        # make the bubble flicker between random variants distractingly.
        if state_key != self._last_vigi_state_key:
            if self._last_vigi_state_key is not None:  # skip the bounce on first load
                self._trigger_vigi_burst("pop")
            self._last_vigi_state_key = state_key
            self._set_vigi_says(mascot.status_message(state_key))

        self._pause_btn.set_sensitive(not paused)
        self._resume_btn.set_sensitive(paused)
        self._stop_btn.set_sensitive(bool(blocked) and not paused)

        self._rebuild_profile_rows()
        return False  # one-shot idle callback

    # ------------------------------------------------------------ actions
    def _on_pause(self, *_args) -> None:
        client.call_async({"cmd": "pause", "minutes": 5}, lambda r, e: self.refresh_status())

    def _on_resume(self, *_args) -> None:
        client.call_async({"cmd": "resume"}, lambda r, e: self.refresh_status())

    def _on_stop(self, *_args) -> None:
        client.call_async({"cmd": "stop"}, lambda r, e: self.refresh_status())

    # ------------------------------------------------------------ profiles
    def _rebuild_profile_rows(self) -> None:
        child = self._profiles_group.get_first_child()
        # Adw.PreferencesGroup manages its own internal list box; remove via API.
        for row in list(getattr(self, "_profile_rows", [])):
            self._profiles_group.remove(row)
        self._profile_rows = []

        status_by_name = {}
        if self._last_status:
            status_by_name = {p["name"]: p for p in self._last_status.get("profiles", [])}

        for name, profile in self._cfg.profiles.items():
            row = Adw.ActionRow(title=name)
            state = status_by_name.get(name, {}).get("state", "INACTIVE")
            row.set_subtitle(f"{state} · {len(profile.blocked_apps)} app(s) blocked")

            start_btn = Gtk.Button(label="Stop" if state == "ACTIVE" else "Start now")
            start_btn.connect("clicked", self._on_start_stop_profile, name, state == "ACTIVE")
            row.add_suffix(start_btn)

            edit_btn = Gtk.Button(icon_name="document-edit-symbolic", valign=Gtk.Align.CENTER)
            edit_btn.connect("clicked", self._on_edit_profile, name)
            row.add_suffix(edit_btn)

            self._profiles_group.add(row)
            self._profile_rows.append(row)

        if not self._cfg.profiles:
            empty_row = Adw.ActionRow(title="No profiles yet", subtitle="Click + to create one, e.g. “School”")
            self._profiles_group.add(empty_row)
            self._profile_rows.append(empty_row)

    def _on_start_stop_profile(self, _btn, name: str, currently_active: bool) -> None:
        cmd = "stop" if currently_active else "start"
        client.call_async({"cmd": cmd, "profile": name}, lambda r, e: self.refresh_status())

    def _on_add_profile(self, *_args) -> None:
        def on_save(profile: Profile) -> None:
            self._cfg.profiles[profile.name] = profile
            self._save_config()
            self._rebuild_profile_rows()

        editor = ProfileEditorWindow(self, None, on_save)
        editor.present()

    def _on_edit_profile(self, _btn, name: str) -> None:
        profile = self._cfg.profiles.get(name)
        if profile is None:
            return

        def on_save(new_profile: Profile) -> None:
            if new_profile.name != name:
                del self._cfg.profiles[name]
            self._cfg.profiles[new_profile.name] = new_profile
            self._save_config()
            self._rebuild_profile_rows()

        def on_delete(profile_name: str) -> None:
            self._cfg.profiles.pop(profile_name, None)
            self._save_config()
            self._rebuild_profile_rows()

        editor = ProfileEditorWindow(self, profile, on_save, on_delete)
        editor.present()
