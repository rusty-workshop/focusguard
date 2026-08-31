# Bash completion for focusguardctl.
#
# Manual install: source this file from ~/.bashrc, or copy it to
# /usr/share/bash-completion/completions/focusguardctl (done automatically
# by the PKGBUILD).

_focusguardctl_profiles() {
    local cfg="${XDG_CONFIG_HOME:-$HOME/.config}/focusguard/config.json"
    [[ -r "$cfg" ]] || return
    command -v jq >/dev/null 2>&1 || return
    jq -r '.profiles | keys[]?' "$cfg" 2>/dev/null
}

_focusguardctl() {
    local cur prev
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    local commands="status start stop pause resume toggle reload doctor vigi"

    if [[ $COMP_CWORD -eq 1 ]]; then
        COMPREPLY=($(compgen -W "$commands" -- "$cur"))
        return
    fi

    local cmd="${COMP_WORDS[1]}"
    if [[ $COMP_CWORD -eq 2 && ( "$cmd" == "start" || "$cmd" == "toggle" || "$cmd" == "stop" ) ]]; then
        COMPREPLY=($(compgen -W "$(_focusguardctl_profiles)" -- "$cur"))
        return
    fi

    COMPREPLY=($(compgen -W "--json" -- "$cur"))
}

complete -F _focusguardctl focusguardctl
