import os
import signal
from unittest.mock import patch

import pytest

from focusguard.common.appinfo import AppEntry
from focusguard.common.procs import ProcInfo, PROTECTED_COMM
from focusguard.daemon import enforcer as enforcer_mod
from focusguard.daemon.enforcer import Enforcer, _matches


def _entry(app_id, *sigs):
    return AppEntry(id=app_id, name=app_id, icon=None, signatures=list(sigs))


def test_exact_basename_match():
    sig_index = {"discord": "discord.desktop"}
    proc = ProcInfo(pid=1, uid=1000, comm="discord", exe="/usr/bin/discord", cmdline=["discord"])
    assert _matches(proc, sig_index) == "discord.desktop"


def test_substring_is_not_a_match():
    # "discord" should not match a process merely containing it as a substring
    sig_index = {"discord": "discord.desktop"}
    proc = ProcInfo(pid=1, uid=1000, comm="discordanalyzer", exe="/usr/bin/discordanalyzer", cmdline=[])
    assert _matches(proc, sig_index) is None


def test_realpath_match_for_wrapped_binary():
    sig_index = {"/opt/vivaldi/vivaldi-bin": "vivaldi.desktop"}
    proc = ProcInfo(pid=1, uid=1000, comm="vivaldi-bin", exe="/opt/vivaldi/vivaldi-bin", cmdline=[])
    assert _matches(proc, sig_index) == "vivaldi.desktop"


def test_flatpak_app_id_argv_match():
    sig_index = {"com.discordapp.Discord": "discord.flatpak.desktop"}
    proc = ProcInfo(
        pid=1, uid=1000, comm="discord",
        exe="/usr/lib/flatpak/exe/discord",
        cmdline=["/newroot/app/bin/discord", "--", "com.discordapp.Discord"],
    )
    assert _matches(proc, sig_index) == "discord.flatpak.desktop"


def test_unrelated_process_never_matches():
    sig_index = {"discord": "discord.desktop", "steam": "steam.desktop"}
    proc = ProcInfo(pid=1, uid=1000, comm="firefox", exe="/usr/lib/firefox/firefox", cmdline=["firefox"])
    assert _matches(proc, sig_index) is None


@pytest.mark.parametrize("protected_name", sorted(PROTECTED_COMM))
def test_protected_names_are_excluded_from_signature_index(protected_name):
    with patch.object(enforcer_mod, "lookup_app", return_value=_entry("evil.desktop", protected_name)):
        index = enforcer_mod._build_signature_index(["evil.desktop"])
    assert protected_name not in index


def test_focusguard_own_components_are_protected():
    for name in ("focusguardd", "focusguard", "focusguardctl", "focusguard-gui"):
        assert name in PROTECTED_COMM


def test_sigterm_then_sigkill_escalation():
    sent = []

    def fake_kill(pid, sig):
        sent.append((pid, sig))

    fake_procs = [ProcInfo(pid=999, uid=os.getuid(), comm="discord", exe="/usr/bin/discord", cmdline=[])]

    with patch.object(enforcer_mod.os, "kill", side_effect=fake_kill), \
         patch.object(enforcer_mod.procs, "iter_processes", return_value=iter(fake_procs)), \
         patch.object(enforcer_mod.procs, "read_proc", return_value=fake_procs[0]), \
         patch.object(enforcer_mod, "lookup_app", return_value=_entry("discord.desktop", "discord")), \
         patch.object(enforcer_mod.time, "time", side_effect=[1000.0, 1004.0]):
        e = Enforcer(grace_period_seconds=3.0)
        e.tick(["discord.desktop"])  # tick 1: should SIGTERM only
        assert sent == [(999, signal.SIGTERM)]

        e.tick(["discord.desktop"])  # tick 2: grace expired (4s > 3s), still alive -> SIGKILL
        assert sent == [(999, signal.SIGTERM), (999, signal.SIGKILL)]


def test_process_that_exits_after_sigterm_is_not_sigkilled():
    fake_procs = [ProcInfo(pid=999, uid=os.getuid(), comm="discord", exe="/usr/bin/discord", cmdline=[])]

    with patch.object(enforcer_mod.os, "kill") as fake_kill, \
         patch.object(enforcer_mod.procs, "iter_processes", return_value=iter(fake_procs)), \
         patch.object(enforcer_mod.procs, "read_proc", return_value=None), \
         patch.object(enforcer_mod, "lookup_app", return_value=_entry("discord.desktop", "discord")), \
         patch.object(enforcer_mod.time, "time", side_effect=[1000.0, 1004.0]):
        e = Enforcer(grace_period_seconds=3.0)
        e.tick(["discord.desktop"])
        fake_kill.reset_mock()
        e.tick(["discord.desktop"])  # process already gone (read_proc -> None): no SIGKILL sent
        fake_kill.assert_not_called()


def test_never_signals_other_uid_process():
    other_uid_proc = ProcInfo(pid=42, uid=os.getuid() + 1, comm="discord", exe="/usr/bin/discord", cmdline=[])
    with patch.object(enforcer_mod.os, "kill") as fake_kill, \
         patch.object(enforcer_mod.procs, "iter_processes", return_value=iter([])), \
         patch.object(enforcer_mod, "lookup_app", return_value=_entry("discord.desktop", "discord")):
        e = Enforcer()
        e._pending[42] = enforcer_mod._Pending(app_id="discord.desktop", comm="discord", sigterm_at=0)
        with patch.object(enforcer_mod.procs, "read_proc", return_value=other_uid_proc), \
             patch.object(enforcer_mod.time, "time", return_value=1000.0):
            e.tick(["discord.desktop"])
    fake_kill.assert_not_called()


def test_protected_process_never_signaled_even_if_selected():
    fake_procs = [ProcInfo(pid=1, uid=os.getuid(), comm="Hyprland", exe="/usr/bin/Hyprland", cmdline=[])]
    with patch.object(enforcer_mod.os, "kill") as fake_kill, \
         patch.object(enforcer_mod.procs, "iter_processes", return_value=iter(fake_procs)), \
         patch.object(enforcer_mod, "lookup_app", return_value=_entry("evil.desktop", "Hyprland")):
        e = Enforcer()
        e.tick(["evil.desktop"])
    fake_kill.assert_not_called()
