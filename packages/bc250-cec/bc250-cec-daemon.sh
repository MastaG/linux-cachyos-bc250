#!/usr/bin/env bash
# BC-250 CEC daemon: announces this board to the HDMI CEC bus as "SteamOS"
# and triggers a DRM hotplug replug when the display reports powering on,
# or when another CEC device points the active source at us.
#
# Why: the HDMI 2.1 link through a DP-to-HDMI converter (or a native HDMI
# 2.1 PCON) sometimes needs a re-detect -- the same unplug/replug cycle a
# physical cable pull would trigger -- to bring the picture back after the
# display has been off, beyond what the kernel's own long-blank relink
# heuristic catches on its own (it fires on blank duration, not on the
# display's actual power state). CEC gives a real, event-driven signal
# instead, from two independent sources:
#   1. the display's own power state (off -> on), polled periodically;
#   2. another device (TV/AVR) naming our physical address as the new
#      active source -- e.g. switching TV input back to SteamOS while the
#      display never actually powered off. The power-state poll alone
#      cannot see this, since the display was "on" throughout.
#
# Never sends <Standby> or <Image View On> -- detection only, per the
# feature request this shipped for. Verified on a real CEC bus trace that
# claiming a logical address never transmits anything beyond the mandatory
# address-claim broadcasts and our own power-status queries. Separately,
# after the replug settles, it injects one synthetic keypress via uinput
# -- not a CEC command at all, just a workaround for Steam/gamescope's own
# UI being left on a black screen instead of its usual screensaver after a
# hotplug replug. The one opt-in exception, off by default
# (SWITCH_INPUT_ON_POWER_ON), broadcasts <Active Source> after a power-on
# so the TV switches to this board's input on its own.
#
# The debugfs trigger_hotplug write needs root; the CEC calls do not
# (/dev/cecN is group `video`), but the whole service runs as root anyway
# to keep this one small rather than split across a privilege boundary for
# a single write.
#
# All tunables below read from the environment, which is how
# /etc/bc250-cec.conf reaches this script: it is wired up as
# EnvironmentFile=-/etc/bc250-cec.conf in the unit, parsed by systemd
# itself as plain KEY=value (not sourced as shell), so an edited config
# file can never inject shell code here.

set -Eeuo pipefail

readonly OSD_NAME="${BC250_CEC_DISPLAY_NAME:-SteamOS}"
readonly POLL_INTERVAL_S="${BC250_CEC_POLL_INTERVAL_S:-5}"
readonly TRIGGER_COOLDOWN_S="${BC250_CEC_TRIGGER_COOLDOWN_S:-30}"
readonly TV_LOGICAL_ADDRESS=0
# Independently toggle the replug and the wake keypress per trigger
# source, so e.g. one source's detection can be disabled without losing
# the other, or the keypress can be disabled while keeping the replug.
readonly HOTPLUG_ON_POWER_ON="${BC250_CEC_HOTPLUG_ON_POWER_ON:-1}"
readonly HOTPLUG_ON_ACTIVE_SOURCE="${BC250_CEC_HOTPLUG_ON_ACTIVE_SOURCE:-1}"
readonly WAKE_KEY_ON_POWER_ON="${BC250_CEC_WAKE_KEY_ON_POWER_ON:-1}"
readonly WAKE_KEY_ON_ACTIVE_SOURCE="${BC250_CEC_WAKE_KEY_ON_ACTIVE_SOURCE:-1}"
# Steam/gamescope can be left showing a black screen instead of its usual
# screensaver after a hotplug replug -- confirmed on hardware 2026-09-28,
# fixed by one synthetic keypress. F15 is the user's explicit choice of
# default: not present on physical keyboards at all (unlike F13, which
# some extended keyboards do have) and essentially never bound to
# anything in a game or in Steam's own UI, unlike a real key that could
# double as an in-game action if a game happens to be running when this
# fires. Empty disables the wake keypress entirely.
readonly WAKE_KEY="${BC250_CEC_WAKE_KEY:-KEY_F15}"
readonly WAKE_DELAY_S="${BC250_CEC_WAKE_DELAY_S:-1}"
# Opt-in and off by default: this is the one thing the rest of this daemon
# deliberately never does on its own (see the top-of-file note on why) --
# broadcast ACTIVE_SOURCE so the TV switches its input to us. Only wired
# to the power-on trigger (an active-source trigger means the TV already
# switched to us, so sending it again would be pointless). The delay lets
# the replug and the display's own post-power-on settling happen first
# rather than racing a CEC broadcast against them.
readonly SWITCH_INPUT_ON_POWER_ON="${BC250_CEC_SWITCH_INPUT_ON_POWER_ON:-0}"
readonly SWITCH_INPUT_DELAY_S="${BC250_CEC_SWITCH_INPUT_DELAY_S:-3}"
# Shared between the poll loop and the active-source monitor loop, which
# run as two concurrent background jobs -- a plain shell variable is not
# visible across them, but a file is. RuntimeDirectory=bc250-cec in the
# unit creates this, root-owned, cleaned up on stop.
readonly TRIGGER_STATE_FILE="${BC250_CEC_TRIGGER_STATE_FILE:-/run/bc250-cec/last-trigger}"

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

# Re-assert our logical address claim. A real display power cycle can reset
# more of the CEC/AUX link state than just "is the display on" -- observed
# on hardware: a TV off for as little as 5s left the adapter fully
# unconfigured (logical address mask 0x0000, OSD name cleared), which
# silently blinds every later poll forever since nothing else re-claims it.
claim_logical_address() {
    local dev="$1"
    cec-ctl -d "$dev" --playback --osd-name "$OSD_NAME" >/dev/null 2>&1
}

# This adapter's own physical address (e.g. "2.3.0.0"), used to recognize
# ourselves in another device's SET_STREAM_PATH/ACTIVE_SOURCE broadcasts.
own_physical_address() {
    local dev="$1"
    cec-ctl -d "$dev" -S 2>/dev/null | sed -nE 's/^\s*Physical Address\s*:\s*([0-9a-fA-F.]+)\s*$/\1/p' | head -1
}

# "on" if the display answered GIVE_DEVICE_POWER_STATUS with pwr-state: on;
# "off" for standby, any other reported state, or no reply at all (display
# fully powered off, or unreachable through a currently-off AVR in the
# chain). CEC's logical address 0 is always the TV by the spec's own
# convention, regardless of how many CEC repeaters (an AVR, for instance)
# sit between this board and it, so this needs no topology-specific logic.
#
# If our own adapter has lost its logical address claim (cec-ctl reports
# "unconfigured"), that is not a display power state at all -- re-claim and
# retry once immediately, so a lost claim costs at most one extra query
# rather than blinding every poll until the service is restarted.
query_power_state() {
    local dev="$1" out
    out="$(cec-ctl -d "$dev" --to "$TV_LOGICAL_ADDRESS" --give-device-power-status 2>&1)" || true
    if grep -qE 'unconfigured' <<<"$out"; then
        log "adapter lost its logical address claim; re-claiming"
        claim_logical_address "$dev"
        out="$(cec-ctl -d "$dev" --to "$TV_LOGICAL_ADDRESS" --give-device-power-status 2>&1)" || true
    fi
    if grep -qE 'pwr-state: on\b' <<<"$out"; then
        printf 'on\n'
    else
        printf 'off\n'
    fi
}

# One synthetic keypress via a throwaway uinput virtual keyboard --
# python-evdev is already present on this system (confirmed 2026-09-28),
# so this needs no new input-injection tool like ydotool. A fresh
# UInput() per call is deliberately simple/stateless, matching how the
# rest of this daemon shells out to cec-ctl fresh each time rather than
# holding a persistent handle; this only runs after an actual trigger,
# gated by the same cooldown, so it is not a hot path.
inject_wake_key() {
    [[ -n "$WAKE_KEY" ]] || return 0
    python3 - "$WAKE_KEY" <<'PYEOF' 2>/dev/null || log "failed to inject the wake keypress"
import sys, time
from evdev import UInput, ecodes as e

key = getattr(e, sys.argv[1])
with UInput({e.EV_KEY: [key]}, name="bc250-cec-wake") as ui:
    time.sleep(0.1)  # let udev/libinput enumerate the new virtual device
    ui.write(e.EV_KEY, key, 1)
    ui.syn()
    time.sleep(0.05)
    ui.write(e.EV_KEY, key, 0)
    ui.syn()
PYEOF
}

# Broadcast ACTIVE_SOURCE naming our own physical address, so the TV
# switches its input to us. The one command in this whole daemon that can
# change the display's active input -- opt-in only, see
# SWITCH_INPUT_ON_POWER_ON above.
switch_input_to_us() {
    local dev="$1" own_addr="$2"
    cec-ctl -d "$dev" --active-source "phys-addr=$own_addr" >/dev/null 2>&1 \
        || log "failed to send active-source"
}

# Fire the debugfs replug, the wake keypress, and/or (power-on only,
# opt-in) the active-source switch, for one trigger source ("power_on" or
# "active_source") -- each independently switchable. Shares one cooldown
# across both sources via TRIGGER_STATE_FILE so a power-on and an
# active-source switch landing close together cannot double-trigger.
fire_trigger() {
    local trigger_path="$1" connector="$2" cec_dev="$3" own_addr="$4" source="$5" reason="$6"
    local do_hotplug do_wake do_switch_input now last

    case "$source" in
        power_on) do_hotplug="$HOTPLUG_ON_POWER_ON"; do_wake="$WAKE_KEY_ON_POWER_ON"
                  do_switch_input="$SWITCH_INPUT_ON_POWER_ON" ;;
        active_source) do_hotplug="$HOTPLUG_ON_ACTIVE_SOURCE"; do_wake="$WAKE_KEY_ON_ACTIVE_SOURCE"
                  do_switch_input=0 ;;
    esac

    if [[ "$do_hotplug" != 1 && "$do_wake" != 1 && "$do_switch_input" != 1 ]]; then
        log "$reason, but everything is disabled for this trigger; skipping"
        return 0
    fi

    now="$(date +%s)"
    last="$(cat "$TRIGGER_STATE_FILE" 2>/dev/null || printf '0')"
    if (( now - last >= TRIGGER_COOLDOWN_S )); then
        log "$reason"
        if [[ "$do_hotplug" == 1 ]]; then
            log "triggering hotplug replug on $connector"
            echo 1 > "$trigger_path" || log "failed to write $trigger_path"
        fi
        printf '%s\n' "$now" > "$TRIGGER_STATE_FILE"
        if [[ "$do_wake" == 1 ]]; then
            sleep "$WAKE_DELAY_S"
            inject_wake_key
        fi
        if [[ "$do_switch_input" == 1 ]]; then
            sleep "$SWITCH_INPUT_DELAY_S"
            log "switching TV input to us ($own_addr)"
            switch_input_to_us "$cec_dev" "$own_addr"
        fi
    else
        log "$reason, but within the ${TRIGGER_COOLDOWN_S}s cooldown; skipping"
    fi
}

# Loop 1: poll the display's power state, trigger on a genuine off -> on
# transition. Baseline-only on the first reading, so a display already on
# when this service (re)starts does not glitch the picture.
poll_power_loop() {
    local cec_dev="$1" trigger_path="$2" connector="$3" own_addr="$4"
    local state prev_state="" baseline_set=0

    while :; do
        state="$(query_power_state "$cec_dev")"

        if (( baseline_set )) && [[ "$prev_state" != on && "$state" == on ]]; then
            fire_trigger "$trigger_path" "$connector" "$cec_dev" "$own_addr" power_on "display powered on ($prev_state -> on)"
        elif (( ! baseline_set )); then
            log "baseline display power state: $state"
        fi

        baseline_set=1
        prev_state="$state"
        sleep "$POLL_INTERVAL_S"
    done
}

# Loop 2: passively watch the bus for SET_STREAM_PATH/ACTIVE_SOURCE naming
# our own physical address -- the signal that a TV/AVR just switched its
# active input to us while the display itself never went to standby, which
# the power-state poll alone cannot see. Read-only: never replies on the
# bus, so this cannot itself cause an input switch.
#
# Our own trigger_hotplug writes invalidate `cec-ctl -m`'s open handle --
# confirmed on hardware, it exits a few seconds after we fire a replug
# (presumably the DRM connector disconnect/reconnect cycling the CEC
# adapter underneath it). The device path itself stays stable (still
# /dev/cec0 every time), so just reattach in place rather than treating
# this as fatal -- the first design killed and restarted the whole
# service on every such hiccup, which briefly blinds the power-poll loop
# too (a fresh instance's first reading is always baseline-only, so a
# transition landing in that gap would be silently missed).
monitor_active_source_loop() {
    local cec_dev="$1" trigger_path="$2" connector="$3" own_addr="$4"
    local pending line

    if [[ -z "$own_addr" ]]; then
        log "could not determine our own physical address; active-source watch disabled"
        return 1
    fi
    log "watching for active-source switches to $own_addr"

    while :; do
        pending=0
        # cec-ctl -m prints each message opcode on one line and its fields
        # (e.g. "phys-addr: 2.3.0.0") on the following indented lines --
        # track whether the last opcode line was one we care about, then
        # check the next phys-addr line against our own address.
        while IFS= read -r line; do
            if grep -qE 'SET_STREAM_PATH|ACTIVE_SOURCE' <<<"$line"; then
                pending=1
                continue
            fi
            if (( pending )) && grep -qE 'phys-addr:' <<<"$line"; then
                if grep -qF "$own_addr" <<<"$line"; then
                    fire_trigger "$trigger_path" "$connector" "$cec_dev" "$own_addr" active_source "active source switched to us ($own_addr)"
                fi
                pending=0
            fi
        done < <(cec-ctl -d "$cec_dev" -m 2>/dev/null)

        log "active-source monitor's cec-ctl exited; reattaching"
        sleep 1
    done
}

main() {
    local cec_info cec_dev connector trigger_path own_addr

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
    own_addr="$(own_physical_address "$cec_dev")"

    mkdir -p "$(dirname "$TRIGGER_STATE_FILE")"

    poll_power_loop "$cec_dev" "$trigger_path" "$connector" "$own_addr" &
    local poll_pid=$!
    monitor_active_source_loop "$cec_dev" "$trigger_path" "$connector" "$own_addr" &
    local monitor_pid=$!

    # Either loop exiting is unexpected (both are infinite by design) --
    # tear down the other and exit so systemd restarts the whole service
    # cleanly rather than leaving an orphaned background loop running
    # under the old PID while systemd starts a fresh instance. `|| true`
    # keeps `set -e` from skipping the cleanup below on a nonzero exit.
    wait -n "$poll_pid" "$monitor_pid" || true
    kill "$poll_pid" "$monitor_pid" 2>/dev/null || true
    log "a monitoring loop exited unexpectedly; exiting for a restart"
    exit 1
}

main "$@"
