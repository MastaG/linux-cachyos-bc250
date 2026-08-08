#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CACHYOS_SOURCE_VARIANT="${1:-linux-cachyos-rc}"
BUILD_KERNEL="${2:-true}"
NCT6687D_COMMIT="${NCT6687D_COMMIT:-}"
CACHYOS_MESA_COMMIT="${CACHYOS_MESA_COMMIT:-}"

case "$CACHYOS_SOURCE_VARIANT" in
    linux-cachyos|linux-cachyos-rc) ;;
    *) printf 'ERROR: unsupported source variant: %s\n' "$CACHYOS_SOURCE_VARIANT" >&2; exit 1 ;;
esac

case "$BUILD_KERNEL" in
    true|false) ;;
    *) printf 'ERROR: BUILD_KERNEL must be true or false: %s\n' "$BUILD_KERNEL" >&2; exit 1 ;;
esac

if [[ "$BUILD_KERNEL" == true ]]; then
    if [[ -z "$NCT6687D_COMMIT" ]]; then
        NCT6687D_COMMIT="$("$ROOT_DIR/scripts/resolve-nct6687d.sh")"
    fi
    [[ "$NCT6687D_COMMIT" =~ ^[0-9a-f]{40}$ ]] || {
        printf 'ERROR: invalid NCT6687D_COMMIT: %s\n' "$NCT6687D_COMMIT" >&2
        exit 1
    }
fi

if [[ -z "$CACHYOS_MESA_COMMIT" ]]; then
    CACHYOS_MESA_COMMIT="$("$ROOT_DIR/scripts/resolve-cachyos-mesa.sh")"
fi
[[ "$CACHYOS_MESA_COMMIT" =~ ^[0-9a-f]{40}$ ]] || {
    printf 'ERROR: invalid CACHYOS_MESA_COMMIT: %s\n' "$CACHYOS_MESA_COMMIT" >&2
    exit 1
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
KERNEL_BASE="https://raw.githubusercontent.com/CachyOS/linux-cachyos/master/${CACHYOS_SOURCE_VARIANT}"
MESA_BASE="https://raw.githubusercontent.com/CachyOS/CachyOS-PKGBUILDS/${CACHYOS_MESA_COMMIT}/mesa/mesa"

if [[ "$BUILD_KERNEL" == true ]]; then
    curl -fsSL --retry 5 --retry-all-errors -o "$TMP/kernel-PKGBUILD" "$KERNEL_BASE/PKGBUILD"
    curl -fsSL --retry 5 --retry-all-errors -o "$TMP/kernel-config" "$KERNEL_BASE/config"
    curl -fsSL --retry 5 --retry-all-errors \
        -o "$TMP/nct6687.c" \
        "https://raw.githubusercontent.com/Fred78290/nct6687d/${NCT6687D_COMMIT}/nct6687.c"
    printf '%s\n' "$NCT6687D_COMMIT" > "$TMP/nct6687d-commit"
fi

curl -fsSL --retry 5 --retry-all-errors -o "$TMP/mesa-PKGBUILD" "$MESA_BASE/PKGBUILD"
curl -fsSL --retry 5 --retry-all-errors -o "$TMP/mesa-gamescope-fps-limiter.patch" \
    "$MESA_BASE/gamescope-fps-limiter.patch"

printf '%s\n' "$CACHYOS_MESA_COMMIT" > "$TMP/cachyos-mesa-commit"
printf '%s\n' "$CACHYOS_SOURCE_VARIANT" > "$TMP/source-variant"
printf '%s\n' "$BUILD_KERNEL" > "$TMP/build-kernel"
printf '%s\n' 'x86-64-v3' > "$TMP/mesa-march"
printf '%s\n' 'znver2' > "$TMP/mesa-mtune"

if [[ "$BUILD_KERNEL" == true ]]; then
    printf '%s\n' 'linux-cachyos-bc250' > "$TMP/package-base"
    printf '%s\n' 'generic_v3' > "$TMP/processor-opt"
    printf '%s\n' 'znver2' > "$TMP/cpu-tune"
fi

{
    if [[ "$BUILD_KERNEL" == true ]]; then
        sha256sum "$TMP/kernel-PKGBUILD" "$TMP/kernel-config" "$TMP/nct6687.c" \
            "$TMP/nct6687d-commit" "$TMP/package-base" \
            "$TMP/processor-opt" "$TMP/cpu-tune"
        sha256sum "$ROOT_DIR"/patches/*.patch
        sha256sum "$ROOT_DIR"/scripts/prepare-pkgbuild.sh \
            "$ROOT_DIR"/scripts/build-package.sh \
            "$ROOT_DIR"/scripts/resolve-nct6687d.sh
    fi

    sha256sum "$TMP/mesa-PKGBUILD" "$TMP/mesa-gamescope-fps-limiter.patch" \
        "$TMP/cachyos-mesa-commit" "$TMP/source-variant" "$TMP/build-kernel" \
        "$TMP/mesa-march" "$TMP/mesa-mtune"
    sha256sum "$ROOT_DIR"/patches/mesa/*.patch
    sha256sum "$ROOT_DIR"/scripts/ci-build.sh \
        "$ROOT_DIR"/scripts/resolve-cachyos-mesa.sh \
        "$ROOT_DIR"/scripts/prepare-mesa-pkgbuild.sh \
        "$ROOT_DIR"/scripts/build-mesa-package.sh
} | sha256sum | awk '{print $1}'
