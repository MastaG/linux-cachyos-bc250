#!/usr/bin/env bash
#
# Which CachyOS Proton release the Steam Linux Runtime package builds.
#
# Read from CachyOS's own proton-cachyos-slr PKGBUILD at the same
# CachyOS-PKGBUILDS commit the Mesa and native Proton packages pin, so all three
# move together rather than drifting apart on separate schedules.
#
# Emits shell assignments: SLR_TAG, SLR_VERSION.
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
COMMIT="${CACHYOS_MESA_COMMIT:-}"
if [[ -z "$COMMIT" ]]; then
    COMMIT="$("$ROOT_DIR/scripts/resolve-cachyos-mesa.sh")"
fi
[[ "$COMMIT" =~ ^[0-9a-f]{40}$ ]] || {
    printf 'ERROR: invalid CACHYOS_MESA_COMMIT: %s\n' "$COMMIT" >&2
    exit 1
}

URL="https://raw.githubusercontent.com/CachyOS/CachyOS-PKGBUILDS/${COMMIT}/proton-cachyos-slr/PKGBUILD"
pkgbuild="$(curl -fsSL --retry 5 --retry-delay 5 --retry-all-errors "$URL")" || {
    printf 'ERROR: could not fetch %s\n' "$URL" >&2
    exit 1
}

# _srctag=11.0-20260703 -> tag cachyos-11.0-20260703-slr, pkgver 11.0.20260703
srctag="$(printf '%s\n' "$pkgbuild" | sed -n 's/^_srctag=//p' | head -1)"
[[ "$srctag" =~ ^[0-9]+\.[0-9]+-[0-9]{8}$ ]] || {
    printf 'ERROR: unexpected _srctag in the upstream PKGBUILD: %s\n' "$srctag" >&2
    printf '       proton-cachyos-slr has changed shape; check it before building.\n' >&2
    exit 1
}

printf 'SLR_TAG=%s\n' "cachyos-${srctag}-slr"
printf 'SLR_VERSION=%s\n' "${srctag//-/.}"
