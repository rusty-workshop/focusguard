# FocusGuard

A GUI app blocker / focus mode for Arch Linux + Hyprland. Pick installed
applications in a GTK4/libadwaita window, schedule them (e.g. "block
Discord, Steam, Spotify, and Vivaldi on weekdays 8am-3pm") or block them on
demand for a set duration, and a small background daemon actually enforces
it — killing matches on sight, including relaunch attempts — until you
explicitly pause or stop it.

## Why not an existing tool?

- **Timekpr-nExT** manages *session* time budgets (login/logout enforcement)
  — it has no concept of blocking individual apps while you're logged in.
- **Malcontent** (GNOME parental controls) is built around Flatpak's
  permission store, accountsservice, and polkit, aimed at a GNOME session —
  a poor fit for a minimal Hyprland setup with no GNOME session services.
- **cgroups alone** can throttle or freeze a process group but can't stop a
  new process from being *exec'd* without root + a BPF LSM/seccomp filter,
  which conflicts with "no root, no risky system changes."

So FocusGuard implements the same technique this class of tool has always
used on Linux without root: a fast poll-and-kill loop over `/proc` for your
own processes, matched against exact executable signatures resolved from
each app's `.desktop` file via `Gio.DesktopAppInfo`.

## Architecture

```
GTK4/libadwaita GUI  ──(Unix socket, JSON lines)──▶  focusguardd (daemon)
        │                                                   │
        ▼                                                   ▼
~/.config/focusguard/config.json  ◀── shared file ──▶  scheduler + enforcer
                                                             │
                                                     /proc scan + SIGTERM/SIGKILL
```

- The GUI (`focusguard`) never kills anything itself. It only edits
  `config.json` and sends commands to the daemon over a Unix socket.
- The daemon (`focusguardd`) is the only thing that touches processes. It
  runs as a systemd `--user` service and works with no GUI open.
- `focusguardctl` is a thin CLI over the same socket — bind it to a
  Hyprland keybind, or script it.

## How enforcement actually works

Every `poll_interval_seconds` (default 1s), the daemon:

1. Recomputes which apps should currently be blocked (union of every
   profile whose schedule is active or that was started manually, minus
   anything paused).
2. Scans `/proc` for your own processes and compares each one's `comm`,
   resolved executable path, and (for Flatpak) its app-id argv token
   against the blocked apps' *exact* signatures — never a substring match.
3. Sends `SIGTERM`; if the process is still alive after
   `grace_period_seconds` (default 3s), escalates to `SIGKILL`.

Because this runs on every tick, a relaunch attempt is caught again on the
next scan. A brief flash before the process dies is expected and is how
this entire class of Linux app-blocker works without root.

A small fixed safety list (`focusguard.common.procs.PROTECTED_COMM`) is
subtracted from *every* block, regardless of what you configure: Hyprland,
systemd, D-Bus, PipeWire/WirePlumber, NetworkManager, and FocusGuard's own
processes can never be signaled.

### Known limitations

- **Steam games**: selecting "Steam" blocks the Steam client itself, not
  each game binary it launches (those are separate processes under a
  different name). Killing Steam does not reliably kill an already-running
  game.
- **AppImages**: some mount themselves at a temp path that changes between
  runs, which can defeat basename/path matching. Most that install to a
  stable path work fine.
- **Very fast relaunchers**: a script that respawns faster than the poll
  interval could theoretically win a race for a fraction of a second on
  each cycle. Lower `poll_interval_seconds` if this matters to you.
- **Electron/Chromium apps** (Discord, Vivaldi, etc.) spawn several
  processes, but they all share the same real executable, so matching one
  signature correctly catches all of them.

## Installing (Arch Linux)

### Dependencies

```bash
sudo pacman -S python python-gobject gtk4 libadwaita
```

`libnotify` (for `notify-send`) and a running `systemd --user` instance are
recommended but optional — see "Notifications" below.

### Option A: PKGBUILD (recommended)

```bash
cd focusguard
makepkg -si
```

This installs `focusguard`, `focusguardd`, `focusguardctl`, the systemd
user unit, the desktop entry, and the icon under `/usr`.

### Option B: pip (user install)

```bash
cd focusguard
python -m venv --system-site-packages ~/.local/share/focusguard-venv  # or skip and use pip --user
pip install --user .
```

If you use `pip install --user .`, edit
`packaging/focusguard.service`'s `ExecStart=` to the absolute path printed
by `which focusguardd` before installing the service (see below) — a bare
command name in a systemd unit is only resolved from the system path
(`/usr/bin` etc.), not `~/.local/bin`.

Then install the systemd unit and desktop file yourself:

```bash
mkdir -p ~/.config/systemd/user ~/.local/share/applications ~/.local/share/icons/hicolor/scalable/apps
cp packaging/focusguard.service ~/.config/systemd/user/
cp packaging/focusguard.desktop ~/.local/share/applications/
cp packaging/focusguard.svg ~/.local/share/icons/hicolor/scalable/apps/
```

### Enable the daemon

```bash
systemctl --user daemon-reload
systemctl --user enable --now focusguard.service
```

Check it's running:

```bash
systemctl --user status focusguard.service
focusguardctl status
```

Launch the GUI from your app launcher ("FocusGuard") or:

```bash
focusguard
```

## Uninstalling

```bash
systemctl --user disable --now focusguard.service
```

**PKGBUILD install:** `sudo pacman -R focusguard`

**pip install:** `pip uninstall focusguard`, then remove the files you
copied manually (`~/.config/systemd/user/focusguard.service`,
`~/.local/share/applications/focusguard.desktop`,
`~/.local/share/icons/hicolor/scalable/apps/focusguard.svg`).

**Either way**, your configuration and history are not touched
automatically — remove them yourself if you want a clean slate:

```bash
rm -rf ~/.config/focusguard
```

## Configuration

Config lives at `~/.config/focusguard/config.json` (human-readable JSON,
written atomically — a crash mid-save can never corrupt it). You normally
edit it through the GUI, but the format is simple enough to hand-edit:

```json
{
  "profiles": {
    "School": {
      "name": "School",
      "blocked_apps": ["discord.desktop", "steam.desktop", "spotify.desktop", "vivaldi-stable.desktop"],
      "schedule": { "enabled": true, "days": [0, 1, 2, 3, 4], "start": "08:00", "end": "15:00" },
      "manual_duration_minutes": 45
    }
  },
  "settings": {
    "poll_interval_seconds": 1.0,
    "grace_period_seconds": 3.0,
    "notifications_enabled": true
  }
}
```

- `blocked_apps` are `.desktop` file IDs (as shown by the picker) — the
  same ID `gio launch <id>` or `gtk-launch <id>` would use.
- `schedule.days`: `0`=Monday ... `6`=Sunday.
- A schedule that crosses midnight (e.g. `22:00` → `06:00` for a "Bedtime"
  profile) works correctly.
- `manual_duration_minutes` is how long a *manual* ("start now") activation
  of that profile lasts; it doesn't affect the scheduled window.

If the file is malformed, the daemon logs an error and keeps running with
whatever config it last loaded successfully — it will never overwrite or
delete a bad file for you, so you can fix it and run
`focusguardctl reload`.

## CLI

```
focusguardctl status              # what's blocked right now, per-profile state
focusguardctl start <profile>     # manually start a profile now (uses its manual_duration_minutes)
focusguardctl stop [profile]      # stop the active block (all profiles, or just one)
focusguardctl pause <minutes>     # suspend all enforcement for N minutes, then auto-resume
focusguardctl resume              # cancel an active pause immediately
focusguardctl toggle <profile>    # start if inactive, stop if active — ideal for a keybind
focusguardctl reload              # force-reload config.json from disk
```

Add `--json` *after* any command (e.g. `focusguardctl status --json`) for
machine-readable output. Exit code is `0` on success and `1` on error
either way.

## Hyprland keybind (optional, not installed automatically)

FocusGuard never edits your Hyprland config. Add a line like this yourself,
using whichever key combo is free on your setup (check your existing binds
first — `SUPER+SHIFT+S` is a common screenshot bind and already likely
taken):

```
bind = SUPER SHIFT, F, exec, focusguardctl toggle School
```

(If your Hyprland config is Lua-based, e.g. `hl.bind("SUPER + SHIFT + F",
hl.dsp.exec_cmd("focusguardctl toggle School"))`.)

### Optional Waybar/status indicator

`focusguardctl status --json` prints machine-readable state, so a Waybar
`custom` module can poll it, e.g.:

```jsonc
"custom/focusguard": {
  "exec": "focusguardctl status --json | jq -r '.blocked_apps | length | if . > 0 then \"🔒 \" + tostring else \"\" end'",
  "interval": 5
}
```

## Notifications

The daemon sends a desktop notification (via `notify-send`) when a block
starts or ends. If `notify-send`/`libnotify` isn't installed, notifications
are silently skipped — this never affects enforcement.

## Logging

Under systemd, view logs with:

```bash
journalctl --user -u focusguard -f
```

Set `FOCUSGUARD_LOG_LEVEL=DEBUG` in the service's environment for more
detail.

## Security notes

- Runs entirely as your own user — no root, no setuid, no polkit rules.
- The control socket lives under `$XDG_RUNTIME_DIR/focusguard/` (mode
  `0700` directory, `0600` socket) and every connection's peer UID is
  checked before any command is parsed.
- The IPC protocol is a fixed whitelist of commands with validated
  arguments — there is no way to run an arbitrary command through it, and
  nothing in the codebase spawns a shell or interpolates config/IPC data
  into a command line.
- The daemon will never signal a process owned by another UID, and a fixed
  list of session-critical process names (compositor, systemd, D-Bus,
  audio stack, and FocusGuard's own processes) can never be blocked no
  matter what you configure.
- `config.json` and `state.json` are written atomically (temp file +
  `rename`) and created with `0600` permissions.

## Development / tests

```bash
python -m venv .venv --system-site-packages   # need system PyGObject/GTK4
.venv/bin/pip install -e . pytest
.venv/bin/python -m pytest
```

`--system-site-packages` is required because PyGObject/GTK bindings are
installed as system packages on Arch, not via pip.
