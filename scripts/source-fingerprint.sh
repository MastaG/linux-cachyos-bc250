#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CACHYOS_SOURCE_VARIANT="${1:-linux-cachyos-rc}"
NCT6687D_COMMIT="${NCT6687D_COMMIT:-}"

case "$CACHYOS_SOURCE_VARIANT" in
    linux-cachyos|linux-cachyos-rc) ;;
    *) printf 'ERROR: unsupported source variant: %s\n' "$CACHYOS_SOURCE_VARIANT" >&2; exit 1 ;;
esac

if [[ -z "$NCT6687D_COMMIT" ]]; then
    NCT6687D_COMMIT="$("$ROOT_DIR/scripts/resolve-nct6687d.sh")"
fi
[[ "$NCT6687D_COMMIT" =~ ^[0-9a-f]{40}$ ]] || {
    printf 'ERROR: invalid NCT6687D_COMMIT: %s\n' "$NCT6687D_COMMIT" >&2
    exit 1
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
BASE="https://raw.githubusercontent.com/CachyOS/linux-cachyos/master/${CACHYOS_SOURCE_VARIANT}"
curl -fsSL --retry 5 --retry-all-errors -o "$TMP/PKGBUILD" "$BASE/PKGBUILD"
curl -fsSL --retry 5 --retry-all-errors -o "$TMP/config" "$BASE/config"
curl -fsSL --retry 5 --retry-all-errors \
    -o "$TMP/nct6687.c" \
    "https://raw.githubusercontent.com/Fred78290/nct6687d/${NCT6687D_COMMIT}/nct6687.c"
printf '%s\n' "$NCT6687D_COMMIT" > "$TMP/nct6687d-commit"
printf '%s\n' "$CACHYOS_SOURCE_VARIANT" > "$TMP/source-variant"
printf '%s\n' 'linux-cachyos-bc250' > "$TMP/package-base"
printf '%s\n' 'generic_v3' > "$TMP/processor-opt"
printf '%s\n' 'znver2' > "$TMP/cpu-tune"

{
    sha256sum "$TMP/PKGBUILD" "$TMP/config" "$TMP/nct6687.c" \
        "$TMP/nct6687d-commit" "$TMP/source-variant" "$TMP/package-base" \
        "$TMP/processor-opt" "$TMP/cpu-tune"
    sha256sum "$ROOT_DIR"/patches/*.patch
    sha256sum "$ROOT_DIR"/scripts/prepare-pkgbuild.sh \
        "$ROOT_DIR"/scripts/build-package.sh "$ROOT_DIR"/scripts/ci-build.sh \
        "$ROOT_DIR"/scripts/resolve-nct6687d.sh
} | sha256sum | awk '{print $1}'
