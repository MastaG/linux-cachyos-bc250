#!/usr/bin/env bash
# Download the local files (patches etc.) an upstream PKGBUILD lists in source=(),
# from the same directory URL the PKGBUILD came from. URL entries (with ://) are
# left to makepkg. This way a patch CachyOS adds to its Mesa PKGBUILD (such as
# 0001-panfrost-Fix-types-of-panfrost_vdrm-functions.patch, 2026-11) is fetched
# instead of failing the build with "was not found in the build directory".
#
# Usage: fetch-pkgbuild-local-sources.sh <dir with PKGBUILD> <upstream directory URL>
set -Eeuo pipefail

dir="${1:?build directory}"
base="${2:?upstream directory URL}"

mapfile -t entries < <(
    cd -- "$dir" &&
    bash -c 'set +eu; source ./PKGBUILD >/dev/null 2>&1; printf "%s\n" "${source[@]}"'
)
[[ ${#entries[@]} -gt 0 ]] || {
    printf 'ERROR: no source=() entries read from %s/PKGBUILD\n' "$dir" >&2
    exit 1
}

for entry in "${entries[@]}"; do
    [[ -z "$entry" || "$entry" == *://* ]] && continue
    name="${entry%%::*}"
    [[ "$name" =~ ^[A-Za-z0-9._+-]+$ ]] || {
        printf 'ERROR: unexpected local source name: %s\n' "$name" >&2
        exit 1
    }
    printf '==> Downloading upstream local source %s\n' "$name"
    curl -fL --retry 5 --retry-all-errors -o "$dir/$name" "$base/$name"
done
