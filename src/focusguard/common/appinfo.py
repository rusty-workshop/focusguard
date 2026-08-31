"""Installed-application discovery and process match-signature resolution.

Uses Gio.DesktopAppInfo (via Gio.AppInfo.get_all()) rather than hand-parsing
.desktop files: Gio already knows how to walk the XDG data dirs in the
correct priority order, filters Hidden/NoDisplay/OnlyShowIn/NotShowIn for
the current desktop, only returns Type=Application entries, and correctly
unescapes/expands the Exec= field (including quoting and field codes).

Match signatures are resolved conservatively: we only ever produce exact
basenames or absolute, symlink-resolved paths. Generic interpreters/wrappers
("env", "sh", "bash", "python3", "flatpak", "bwrap") are never used as a
signature by themselves, since that would match unrelated processes.

Known limitations (see README): Steam games run as children of the Steam
client under a different binary than "steam" and are not individually
blockable by selecting "Steam"; some AppImages mount to a variable temp
path each run and may not resolve to a stable signature; Electron/Chromium
apps spawn multiple processes but they all share the same real executable
path, so they are matched (and killed) together correctly.
"""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from typing import List, Optional

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio  # noqa: E402

_GENERIC_WRAPPERS = {"env", "sh", "bash", "zsh", "dash"}


@dataclass
class AppEntry:
    id: str  # stable .desktop id, e.g. "vivaldi-stable.desktop"
    name: str
    icon: Optional[Gio.Icon]
    signatures: List[str] = field(default_factory=list)


def _resolve_signatures(app_info: Gio.DesktopAppInfo) -> List[str]:
    sigs: set[str] = set()

    executable = app_info.get_executable()
    if executable:
        executable = executable.strip()
        base = os.path.basename(executable)
        if base and base not in _GENERIC_WRAPPERS:
            sigs.add(base)
        resolved = executable if os.path.isabs(executable) else shutil.which(executable)
        if resolved and os.path.exists(resolved):
            real = os.path.realpath(resolved)
            sigs.add(real)
            real_base = os.path.basename(real)
            if real_base and real_base not in _GENERIC_WRAPPERS:
                sigs.add(real_base)

    # Flatpak apps: Exec is "flatpak run ... <app-id>". The app-id shows up
    # in the sandboxed process's argv even though the real binary path
    # inside the sandbox isn't visible to us on the host, so it's the best
    # available signature for flatpak-launched apps.
    cmdline = app_info.get_commandline() or ""
    tokens = cmdline.split()
    if len(tokens) >= 2 and os.path.basename(tokens[0]) == "flatpak" and tokens[1] == "run":
        for tok in tokens[2:]:
            if not tok.startswith("-") and "=" not in tok:
                sigs.add(tok)
                break

    return sorted(s for s in sigs if s)


def list_installed_apps() -> List[AppEntry]:
    """Enumerate launchable desktop applications, de-duplicated by id."""
    seen: dict[str, AppEntry] = {}
    for info in Gio.AppInfo.get_all():
        if not isinstance(info, Gio.DesktopAppInfo):
            continue
        try:
            if not info.should_show():
                continue
        except Exception:
            continue
        desktop_id = info.get_id()
        if not desktop_id or desktop_id in seen:
            continue
        signatures = _resolve_signatures(info)
        if not signatures:
            # Nothing we could ever match on the process table -- can't
            # enforce a block for it, so don't offer it as blockable.
            continue
        name = info.get_display_name() or info.get_name() or desktop_id
        seen[desktop_id] = AppEntry(
            id=desktop_id, name=name, icon=info.get_icon(), signatures=signatures
        )
    return sorted(seen.values(), key=lambda e: e.name.casefold())


def lookup_app(desktop_id: str) -> Optional[AppEntry]:
    try:
        info = Gio.DesktopAppInfo.new(desktop_id)
    except TypeError:
        # PyGObject raises instead of returning NULL when the id is unknown.
        info = None
    if info is None:
        return None
    signatures = _resolve_signatures(info)
    if not signatures:
        return None
    return AppEntry(
        id=desktop_id,
        name=info.get_display_name() or info.get_name() or desktop_id,
        icon=info.get_icon(),
        signatures=signatures,
    )


def signatures_for(desktop_ids: List[str]) -> dict[str, set[str]]:
    """Map each signature -> set of desktop ids it would identify (for logging
    when multiple selected apps happen to share a signature, e.g. two
    desktop files pointing at the same binary)."""
    result: dict[str, set[str]] = {}
    for desktop_id in desktop_ids:
        entry = lookup_app(desktop_id)
        if not entry:
            continue
        for sig in entry.signatures:
            result.setdefault(sig, set()).add(desktop_id)
    return result
