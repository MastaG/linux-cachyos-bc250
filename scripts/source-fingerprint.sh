#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
COMPONENT="${1:?component is required: kernel|mesa|lib32-mesa|mesa-git}"
CACHYOS_SOURCE_VARIANT="${2:-linux-cachyos-rc}"
NCT6687D_COMMIT="${NCT6687D_COMMIT:-}"
CACHYOS_MESA_COMMIT="${CACHYOS_MESA_COMMIT:-}"
MESA_GIT_COMMIT="${MESA_GIT_COMMIT:-}"

case "$COMPONENT" in
    kernel|mesa|lib32-mesa|mesa-git) ;;
    *) printf 'ERROR: unsupported fingerprint component: %s\n' "$COMPONENT" >&2; exit 1 ;;
esac
case "$CACHYOS_SOURCE_VARIANT" in
    linux-cachyos|linux-cachyos-rc) ;;
    *) printf 'ERROR: unsupported source variant: %s\n' "$CACHYOS_SOURCE_VARIANT" >&2; exit 1 ;;
esac

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

hash_files() {
    sha256sum "$@"
}

case "$COMPONENT" in
    kernel)
        if [[ -z "$NCT6687D_COMMIT" ]]; then
            NCT6687D_COMMIT="$("$ROOT_DIR/scripts/resolve-nct6687d.sh")"
        fi
        [[ "$NCT6687D_COMMIT" =~ ^[0-9a-f]{40}$ ]] || {
            printf 'ERROR: invalid NCT6687D_COMMIT: %s\n' "$NCT6687D_COMMIT" >&2
            exit 1
        }
        base="https://raw.githubusercontent.com/CachyOS/linux-cachyos/master/${CACHYOS_SOURCE_VARIANT}"
        curl -fsSL --retry 5 --retry-all-errors -o "$TMP/PKGBUILD" "$base/PKGBUILD"
        curl -fsSL --retry 5 --retry-all-errors -o "$TMP/config" "$base/config"
        curl -fsSL --retry 5 --retry-all-errors -o "$TMP/nct6687.c" \
            "https://raw.githubusercontent.com/Fred78290/nct6687d/${NCT6687D_COMMIT}/nct6687.c"
        printf '%s\n' "$CACHYOS_SOURCE_VARIANT" > "$TMP/source-variant"
        printf '%s\n' "$NCT6687D_COMMIT" > "$TMP/nct-commit"
        printf '%s\n' 'linux-cachyos-bc250' > "$TMP/pkgbase"
        printf '%s\n' 'generic_v3' > "$TMP/processor-opt"
        printf '%s\n' 'znver2' > "$TMP/cpu-tune"
        {
            (cd "$TMP" && sha256sum *)
            hash_files "$ROOT_DIR"/patches/*.patch
            hash_files "$ROOT_DIR"/scripts/prepare-pkgbuild.sh \
                "$ROOT_DIR"/scripts/build-package.sh \
                "$ROOT_DIR"/scripts/resolve-nct6687d.sh
        } | sha256sum | awk '{print $1}'
        ;;

    mesa|lib32-mesa|mesa-git)
        if [[ -z "$CACHYOS_MESA_COMMIT" ]]; then
            CACHYOS_MESA_COMMIT="$("$ROOT_DIR/scripts/resolve-cachyos-mesa.sh")"
        fi
        [[ "$CACHYOS_MESA_COMMIT" =~ ^[0-9a-f]{40}$ ]] || {
            printf 'ERROR: invalid CACHYOS_MESA_COMMIT: %s\n' "$CACHYOS_MESA_COMMIT" >&2
            exit 1
        }
        printf '%s\n' 'x86-64-v3' > "$TMP/march"
        printf '%s\n' 'znver2' > "$TMP/mtune"

        if [[ "$COMPONENT" == mesa ]]; then
            base="https://raw.githubusercontent.com/CachyOS/CachyOS-PKGBUILDS/${CACHYOS_MESA_COMMIT}/mesa/mesa"
            curl -fsSL --retry 5 --retry-all-errors -o "$TMP/PKGBUILD" "$base/PKGBUILD"
            curl -fsSL --retry 5 --retry-all-errors -o "$TMP/gamescope.patch" "$base/gamescope-fps-limiter.patch"
            {
                (cd "$TMP" && sha256sum *)
                hash_files "$ROOT_DIR"/patches/mesa/*.patch
                hash_files "$ROOT_DIR"/scripts/resolve-cachyos-mesa.sh \
                    "$ROOT_DIR"/scripts/prepare-mesa-pkgbuild.sh \
                    "$ROOT_DIR"/scripts/build-mesa-package.sh \
                    "$ROOT_DIR"/scripts/repo-package-helpers.sh
            } | sha256sum | awk '{print $1}'

        elif [[ "$COMPONENT" == lib32-mesa ]]; then
            base="https://raw.githubusercontent.com/CachyOS/CachyOS-PKGBUILDS/${CACHYOS_MESA_COMMIT}/mesa/lib32-mesa"
            curl -fsSL --retry 5 --retry-all-errors -o "$TMP/PKGBUILD" "$base/PKGBUILD"
            curl -fsSL --retry 5 --retry-all-errors -o "$TMP/gamescope.patch" "$base/gamescope-fps-limiter.patch"
            {
                (cd "$TMP" && sha256sum *)
                hash_files "$ROOT_DIR"/patches/mesa/*.patch
                hash_files "$ROOT_DIR"/scripts/resolve-cachyos-mesa.sh \
                    "$ROOT_DIR"/scripts/prepare-lib32-mesa-pkgbuild.sh \
                    "$ROOT_DIR"/scripts/build-lib32-mesa-package.sh \
                    "$ROOT_DIR"/scripts/repo-package-helpers.sh
            } | sha256sum | awk '{print $1}'

        else
            if [[ -z "$MESA_GIT_COMMIT" ]]; then
                MESA_GIT_COMMIT="$("$ROOT_DIR/scripts/resolve-mesa-git.sh")"
            fi
            [[ "$MESA_GIT_COMMIT" =~ ^[0-9a-f]{40}$ ]] || {
                printf 'ERROR: invalid MESA_GIT_COMMIT: %s\n' "$MESA_GIT_COMMIT" >&2
                exit 1
            }
            base="https://raw.githubusercontent.com/CachyOS/CachyOS-PKGBUILDS/${CACHYOS_MESA_COMMIT}/mesa/mesa-git"
            for file in PKGBUILD customization.cfg LICENSE llvm32.native; do
                curl -fsSL --retry 5 --retry-all-errors -o "$TMP/$file" "$base/$file"
            done
            printf '%s\n' "$MESA_GIT_COMMIT" > "$TMP/mesa-git-commit"
            {
                (cd "$TMP" && sha256sum *)
                hash_files "$ROOT_DIR"/patches/mesa-git/*.patch "$ROOT_DIR"/patches/mesa-git/series
                hash_files "$ROOT_DIR"/scripts/resolve-cachyos-mesa.sh \
                    "$ROOT_DIR"/scripts/resolve-mesa-git.sh \
                    "$ROOT_DIR"/scripts/prepare-mesa-git-pkgbuild.sh \
                    "$ROOT_DIR"/scripts/build-mesa-git-package.sh \
                    "$ROOT_DIR"/scripts/repo-package-helpers.sh
            } | sha256sum | awk '{print $1}'
        fi
        ;;
esac
