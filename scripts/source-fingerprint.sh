#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CACHYOS_SOURCE_VARIANT="${1:-linux-cachyos-rc}"

case "$CACHYOS_SOURCE_VARIANT" in
    linux-cachyos|linux-cachyos-rc) ;;
    *) printf 'ERROR: unsupported source variant: %s\n' "$CACHYOS_SOURCE_VARIANT" >&2; exit 1 ;;
esac

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
BASE="https://raw.githubusercontent.com/CachyOS/linux-cachyos/master/${CACHYOS_SOURCE_VARIANT}"
curl -fsSL --retry 5 --retry-all-errors -o "$TMP/PKGBUILD" "$BASE/PKGBUILD"
curl -fsSL --retry 5 --retry-all-errors -o "$TMP/config" "$BASE/config"
printf '%s\n' "$CACHYOS_SOURCE_VARIANT" > "$TMP/source-variant"
printf '%s\n' 'linux-cachyos-bc250' > "$TMP/package-base"
printf '%s\n' 'generic_v3' > "$TMP/processor-opt"
printf '%s\n' 'znver2' > "$TMP/cpu-tune"

{
    sha256sum "$TMP/PKGBUILD" "$TMP/config" "$TMP/source-variant" \
        "$TMP/package-base" "$TMP/processor-opt" "$TMP/cpu-tune"
    sha256sum "$ROOT_DIR"/patches/*.patch
    sha256sum "$ROOT_DIR"/scripts/prepare-pkgbuild.sh \
        "$ROOT_DIR"/scripts/build-package.sh "$ROOT_DIR"/scripts/ci-build.sh
} | sha256sum | awk '{print $1}'
