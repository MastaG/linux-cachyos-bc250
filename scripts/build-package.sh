#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CACHYOS_VARIANT="${CACHYOS_VARIANT:-linux-cachyos-rc}"
BC250_PKGREL="${BC250_PKGREL:-1}"
SOURCE_FINGERPRINT="${SOURCE_FINGERPRINT:-local}"
BUILD_DIR="${BUILD_DIR:-${ROOT_DIR}/build/${CACHYOS_VARIANT}}"

"${ROOT_DIR}/scripts/prepare-pkgbuild.sh"
# shellcheck disable=SC1091
source "$BUILD_DIR/bc250-build.env"

cd -- "$BUILD_DIR"

# The CachyOS PKGBUILD honours _processor_opt from the environment. generic_v3
# selects CONFIG_GENERIC_CPU with X86_64_VERSION=3 instead of runner-native.
export _processor_opt=generic_v3
export MAKEFLAGS="${MAKEFLAGS:--j$(nproc)}"

# A fresh CI user has no personal OpenPGP keyring. Source integrity is still
# enforced by the upstream PKGBUILD's BLAKE2 checksums.
makepkg --syncdeps --noconfirm --cleanbuild --clean --skippgpcheck
makepkg --printsrcinfo > .SRCINFO

OUT_DIR="${ROOT_DIR}/out/${CHANNEL}"
rm -rf -- "$OUT_DIR"
mkdir -p -- "$OUT_DIR"

shopt -s nullglob
packages=("$BUILD_DIR"/*.pkg.tar.zst)
(( ${#packages[@]} > 0 )) || {
    printf 'ERROR: makepkg produced no .pkg.tar.zst files\n' >&2
    exit 1
}
cp -- "${packages[@]}" "$OUT_DIR/"

cd -- "$OUT_DIR"
repo-add -R "${REPO_NAME}.db.tar.zst" ./*.pkg.tar.zst

# GitHub release assets cannot act as useful symlinks. Publish regular copies
# with the names pacman requests: <repo>.db and <repo>.files.
cp -L --remove-destination "${REPO_NAME}.db.tar.zst" "${REPO_NAME}.db"
cp -L --remove-destination "${REPO_NAME}.files.tar.zst" "${REPO_NAME}.files"

cp -- "$BUILD_DIR/PKGBUILD" "$OUT_DIR/PKGBUILD"
cp -- "$BUILD_DIR/config" "$OUT_DIR/config"
cp -- "$BUILD_DIR/.SRCINFO" "$OUT_DIR/.SRCINFO"

pkgbase="$(awk -F ' = ' '$1 == "pkgbase" {print $2; exit}' "$BUILD_DIR/.SRCINFO")"
pkgver="$(awk -F ' = ' '$1 == "pkgver" {print $2; exit}' "$BUILD_DIR/.SRCINFO")"
pkgrel="$(awk -F ' = ' '$1 == "pkgrel" {print $2; exit}' "$BUILD_DIR/.SRCINFO")"

cat > "$OUT_DIR/build-info.env" <<EOF_INFO
SOURCE_FINGERPRINT=${SOURCE_FINGERPRINT}
CACHYOS_VARIANT=${CACHYOS_VARIANT}
CHANNEL=${CHANNEL}
REPO_NAME=${REPO_NAME}
RELEASE_TAG=${RELEASE_TAG}
ARCH_LEVEL=x86-64-v3
PROCESSOR_OPT=generic_v3
PKGBASE=${pkgbase}
PKGVER=${pkgver}
PKGREL=${pkgrel}
GITHUB_SHA=${GITHUB_SHA:-local}
BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF_INFO

cat > "$OUT_DIR/RELEASE_NOTES.md" <<EOF_NOTES
# BC-250 CachyOS kernel repository (${CHANNEL})

- Upstream variant: \`${CACHYOS_VARIANT}\`
- Package: \`${pkgbase}\`
- Version: \`${pkgver}-${pkgrel}\`
- CPU target: **x86-64-v3** (CachyOS \`generic_v3\`)
- Patches: BC-250 6/8-core telemetry, GPU activity, safe GFXCLK fallback, and Cyan Skillfish DP audio quirk

This release is also a pacman repository. Configure pacman with the fixed
release-tag URL documented in the repository README.
EOF_NOTES

printf '%s — %s-%s' "$pkgbase" "$pkgver" "$pkgrel" > "$OUT_DIR/release-title.txt"
sha256sum ./*.pkg.tar.zst ./*.db ./*.db.tar.zst ./*.files ./*.files.tar.zst \
    PKGBUILD config .SRCINFO build-info.env > SHA256SUMS

printf '==> Repository generated in %s\n' "$OUT_DIR"
ls -lh "$OUT_DIR"
