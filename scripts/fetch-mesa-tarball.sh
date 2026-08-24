#!/usr/bin/env bash
# Pre-fetch the upstream Mesa release tarball into a prepared build directory.
#
# archive.mesa3d.org (annarchy.freedesktop.org) has been intermittently
# unreachable, answering roughly one request in five while port 443 hangs on
# the rest. makepkg gives up after a few attempts and the whole build fails,
# which has broken this repository's builds repeatedly.
#
# Downloading the tarball ourselves with a long retry budget turns that from a
# hard failure into a slow success. If the file is already present and complete
# makepkg skips its own download, and it still verifies the checksum from the
# PKGBUILD afterwards, so a truncated or corrupt fetch is caught normally
# rather than silently used.
#
# Usage: fetch-mesa-tarball.sh <build-dir>
# The PKGBUILD in <build-dir> supplies the version; nothing is hardcoded here.
set -Eeuo pipefail

BUILD_DIR="${1:?build directory is required}"
PKGBUILD="${BUILD_DIR}/PKGBUILD"
[[ -f "$PKGBUILD" ]] || {
    printf 'ERROR: no PKGBUILD in %s\n' "$BUILD_DIR" >&2
    exit 1
}

# pkgver=26.2.1 and _pkgver=${pkgver/[a-z]/-&}, i.e. a release-candidate suffix
# gets a dash inserted (26.2.1rc1 -> 26.2.1-rc1). Reproduce that here.
pkgver="$(sed -n 's/^pkgver=\(.*\)$/\1/p' "$PKGBUILD" | head -n1)"
[[ -n "$pkgver" ]] || {
    printf 'ERROR: could not read pkgver from %s\n' "$PKGBUILD" >&2
    exit 1
}
_pkgver="$(sed -E 's/([a-z])/-\1/' <<<"$pkgver")"

tarball="mesa-${_pkgver}.tar.xz"
url="https://archive.mesa3d.org/${tarball}"
dest="${BUILD_DIR}/${tarball}"

# Only bother if the PKGBUILD actually pulls this tarball; if upstream ever
# switches to a git source this becomes a no-op instead of a failure.
if ! grep -q 'archive\.mesa3d\.org' "$PKGBUILD"; then
    printf '==> PKGBUILD does not use archive.mesa3d.org; skipping pre-fetch\n'
    exit 0
fi

if [[ -s "$dest" ]]; then
    printf '==> %s already present; skipping pre-fetch\n' "$tarball"
    exit 0
fi

printf '==> Pre-fetching %s (long retry budget; the host is frequently down)\n' "$url"
if curl -fL --output "$dest" \
        --retry 20 --retry-all-errors --retry-delay 15 --retry-max-time 1200 \
        --connect-timeout 20 --speed-time 60 --speed-limit 1024 \
        "$url"; then
    printf '==> Pre-fetched %s (%s bytes)\n' "$tarball" "$(stat -c%s "$dest")"
else
    # Leave the decision to makepkg rather than failing the build here: it may
    # still succeed on its own, and a partial file must not be left behind.
    rm -f -- "$dest"
    printf 'WARNING: could not pre-fetch %s; letting makepkg try instead\n' "$tarball" >&2
fi
