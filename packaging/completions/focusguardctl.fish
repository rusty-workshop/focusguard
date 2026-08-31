# Fish completion for focusguardctl.
#
# Manual install: copy to ~/.config/fish/completions/focusguardctl.fish
# (fish loads this directory automatically -- no sourcing needed), or to
# /usr/share/fish/vendor_completions.d/focusguardctl.fish (done
# automatically by the PKGBUILD).

function __focusguardctl_profiles
    set -l cfg "$HOME/.config/focusguard/config.json"
    if set -q XDG_CONFIG_HOME
        set cfg "$XDG_CONFIG_HOME/focusguard/config.json"
    end
    if test -r "$cfg"; and command -q jq
        jq -r '.profiles | keys[]?' "$cfg" 2>/dev/null
    end
end

set -l commands status start stop pause resume toggle reload doctor vigi

complete -c focusguardctl -f

complete -c focusguardctl -n "not __fish_seen_subcommand_from $commands" -a status -d "show current blocking state"
complete -c focusguardctl -n "not __fish_seen_subcommand_from $commands" -a start -d "manually start a profile now"
complete -c focusguardctl -n "not __fish_seen_subcommand_from $commands" -a stop -d "stop the active block"
complete -c focusguardctl -n "not __fish_seen_subcommand_from $commands" -a pause -d "pause all enforcement for N minutes"
complete -c focusguardctl -n "not __fish_seen_subcommand_from $commands" -a resume -d "cancel an active pause immediately"
complete -c focusguardctl -n "not __fish_seen_subcommand_from $commands" -a toggle -d "start profile if inactive, stop it if active"
complete -c focusguardctl -n "not __fish_seen_subcommand_from $commands" -a reload -d "force the daemon to reload config.json"
complete -c focusguardctl -n "not __fish_seen_subcommand_from $commands" -a doctor -d "check daemon/socket/systemd/config health"
complete -c focusguardctl -n "not __fish_seen_subcommand_from $commands" -a vigi -d "say hi to Vigi"

complete -c focusguardctl -n "__fish_seen_subcommand_from start toggle stop" -a "(__focusguardctl_profiles)" -d "profile"
complete -c focusguardctl -n "__fish_seen_subcommand_from status start stop pause resume toggle reload doctor" -l json -d "machine-readable JSON output"
