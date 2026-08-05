#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CACHYOS_VARIANT="${1:-linux-cachyos-rc}"

case "$CACHYOS_VARIANT" in
    linux-cachyos|linux-cachyos-rc) ;;
    *) printf 'ERROR: unsupported variant: %s\n' "$CACHYOS_VARIANT" >&2; exit 1 ;;
esac

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
BASE="https://raw.githubusercontent.com/CachyOS/linux-cachyos/master/${CACHYOS_VARIANT}"
curl -fsSL --retry 5 --retry-all-errors -o "$TMP/PKGBUILD" "$BASE/PKGBUILD"
curl -fsSL --retry 5 --retry-all-errors -o "$TMP/config" "$BASE/config"
printf '%s\n' "$CACHYOS_VARIANT" > "$TMP/variant"

{
    sha256sum "$TMP/PKGBUILD" "$TMP/config" "$TMP/variant"
    sha256sum "$ROOT_DIR"/patches/*.patch
    sha256sum "$ROOT_DIR"/scripts/prepare-pkgbuild.sh "$ROOT_DIR"/scripts/build-package.sh
} | sha256sum | awk '{print $1}'
