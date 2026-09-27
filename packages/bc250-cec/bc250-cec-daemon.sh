#!/usr/bin/env bash
# BC-250 CEC daemon: announces this board to the HDMI CEC bus as "SteamOS"
# and triggers a DRM hotplug replug when the display reports powering on.
#
# Why: the HDMI 2.1 link through a DP-to-HDMI converter (or a native HDMI
# 2.1 PCON) sometimes needs a re-detect -- the same unplug/replug cycle a
# physical cable pull would trigger -- to bring the picture back after the
# display has been off, beyond what the kernel's own long-blank relink
# heuristic catches on its own (it fires on blank duration, not on the
# display's actual power state). CEC gives a real, event-driven "the
# display just turned on" signal instead.
#
# Deliberately does not send any power commands (no <Standby>, no waking
# the display) -- detection only, per the feature request this shipped for.
#
# The debugfs trigger_hotplug write needs root; the CEC calls do not
# (/dev/cecN is group `video`), but the whole service runs as root anyway
# to keep this one small rather than split across a privilege boundary for
# a single write.

set -Eeuo pipefail

readonly OSD_NAME="SteamOS"
readonly POLL_INTERVAL_S="${BC250_CEC_POLL_INTERVAL_S:-5}"
readonly TRIGGER_COOLDOWN_S="${BC250_CEC_TRIGGER_COOLDOWN_S:-30}"
readonly TV_LOGICAL_ADDRESS=0

log() { printf 'bc250-cec: %s\n' "$1"; }

# Discover the CEC device node and the DRM connector it belongs to.
# `cec-ctl --list-devices` prints e.g.:
#   amdgpu (DP-1):
#       /dev/cec0
# Both are resolved fresh on every start rather than hardcoded: the
# connector is fixed on this board today, but nothing here needs it to
# stay that way, and re-discovery costs nothing.
discover_cec() {
    local list connector dev
    list="$(cec-ctl --list-devices 2>/dev/null)" || return 1
    connector="$(sed -nE 's/^[A-Za-z0-9_]+ \(([^)]+)\):$/\1/p' <<<"$list" | head -1)"
    dev="$(grep -oE '/dev/cec[0-9]+' <<<"$list" | head -1)"
    [[ -n "$connector" && -n "$dev" ]] || return 1
    printf '%s\n%s\n' "$dev" "$connector"
}

# This connector's trigger_hotplug debugfs file. The PCI address segment of
# the path is not hardcoded -- a glob costs nothing and does not assume the
# GPU stays at the same PCI address.
find_trigger_hotplug() {
    local connector="$1" path
    for path in /sys/kernel/debug/dri/*/"$connector"/trigger_hotplug; do
        [[ -e "$path" ]] && { printf '%s\n' "$path"; return 0; }
    done
    return 1
}

# "on" if the display answered GIVE_DEVICE_POWER_STATUS with pwr-state: on;
# "off" for standby, any other reported state, or no reply at all (display
# fully powered off, or unreachable through a currently-off AVR in the
# chain). CEC's logical address 0 is always the TV by the spec's own
# convention, regardless of how many CEC repeaters (an AVR, for instance)
# sit between this board and it, so this needs no topology-specific logic.
query_power_state() {
    local dev="$1" out
    out="$(cec-ctl -d "$dev" --to "$TV_LOGICAL_ADDRESS" --give-device-power-status 2>/dev/null)" || true
    if grep -qE 'pwr-state: on\b' <<<"$out"; then
        printf 'on\n'
    else
        printf 'off\n'
    fi
}

main() {
    local cec_info cec_dev connector trigger_path
    local state prev_state="" baseline_set=0 last_trigger=0 now

    cec_info="$(discover_cec)" || {
        log "no CEC adapter found (no /dev/cecN yet); exiting for a restart"
        exit 1
    }
    cec_dev="$(sed -n 1p <<<"$cec_info")"
    connector="$(sed -n 2p <<<"$cec_info")"
    log "found $cec_dev on connector $connector"

    trigger_path="$(find_trigger_hotplug "$connector")" || {
        log "no trigger_hotplug debugfs entry for $connector; exiting for a restart"
        exit 1
    }

    cec-ctl -d "$cec_dev" --playback --osd-name "$OSD_NAME" >/dev/null || {
        log "failed to claim a CEC logical address on $cec_dev; exiting for a restart"
        exit 1
    }
    log "claimed a Playback logical address on $cec_dev as '$OSD_NAME'"

    while :; do
        state="$(query_power_state "$cec_dev")"

        # First reading is a baseline only: a display that is already on
        # when this service (re)starts must not fire a spurious replug.
        if (( baseline_set )) && [[ "$prev_state" != on && "$state" == on ]]; then
            now="$(date +%s)"
            if (( now - last_trigger >= TRIGGER_COOLDOWN_S )); then
                log "display powered on ($prev_state -> on); triggering hotplug replug on $connector"
                echo 1 > "$trigger_path" || log "failed to write $trigger_path"
                last_trigger="$now"
            else
                log "display powered on, but within the ${TRIGGER_COOLDOWN_S}s cooldown; skipping"
            fi
        elif (( ! baseline_set )); then
            log "baseline display power state: $state"
        fi

        baseline_set=1
        prev_state="$state"
        sleep "$POLL_INTERVAL_S"
    done
}

main "$@"
