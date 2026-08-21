#!/usr/bin/env bash
set -Eeuo pipefail

# Fingerprints must not depend on the machine computing them. Glob expansion and
# sort order follow LC_COLLATE, and the temporary directory below mixes cases
# (PKGBUILD vs config, cpu-tune, ...), so a runner using C collation hashes those
# files in a different order than one using a UTF-8 locale and produces a
# different fingerprint for identical sources. That made every component look
# changed whenever a job moved between the two self-hosted runners.
export LC_ALL=C

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
COMPONENT="${1:?component is required}"
NCT6687D_COMMIT="${NCT6687D_COMMIT:-}"
CACHYOS_MESA_COMMIT="${CACHYOS_MESA_COMMIT:-}"
MESA_GIT_COMMIT="${MESA_GIT_COMMIT:-}"

case "$COMPONENT" in
    kernel-stable)
        CACHYOS_SOURCE_VARIANT=linux-cachyos
        EXPECTED_PKGBASE=linux-cachyos-bc250
        PATCH_SET=linux-cachyos
        ;;
    kernel-rc)
        CACHYOS_SOURCE_VARIANT=linux-cachyos-rc
        EXPECTED_PKGBASE=linux-cachyos-rc-bc250
        PATCH_SET=linux-cachyos-rc
        ;;
    kernel-bore)
        CACHYOS_SOURCE_VARIANT=linux-cachyos-bore
        EXPECTED_PKGBASE=linux-cachyos-bore-bc250
        PATCH_SET=linux-cachyos
        ;;
    mesa|lib32-mesa|mesa-git) ;;
    *)
        printf 'ERROR: unsupported fingerprint component: %s\n' "$COMPONENT" >&2
        exit 1
        ;;
esac

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Hash file contents plus the bare file name. Plain `sha256sum "$@"` would put
# the absolute path in its output, which makes the fingerprint depend on where
# the checkout happens to live. Self-hosted runners use different work
# directories, so that made every component look changed whenever a job moved
# between machines, forcing a full rebuild of all three kernels and all of Mesa.
# Basenames are unique within each call site here, so renames still count.
hash_files() {
    local f
    for f in "$@"; do
        printf '%s  %s\n' "$(sha256sum < "$f" | awk '{print $1}')" "$(basename -- "$f")"
    done
}

case "$COMPONENT" in
    kernel-*)
        if [[ -z "$NCT6687D_COMMIT" ]]; then
            NCT6687D_COMMIT="$("$ROOT_DIR/scripts/resolve-nct6687d.sh")"
        fi
        [[ "$NCT6687D_COMMIT" =~ ^[0-9a-f]{40}$ ]] || {
            printf 'ERROR: invalid NCT6687D_COMMIT: %s\n' "$NCT6687D_COMMIT" >&2
            exit 1
        }

        patch_dir="$ROOT_DIR/patches/$PATCH_SET"
        [[ -d "$patch_dir" ]] || {
            printf 'ERROR: missing patch set: %s\n' "$patch_dir" >&2
            exit 1
        }

        base="https://raw.githubusercontent.com/CachyOS/linux-cachyos/master/${CACHYOS_SOURCE_VARIANT}"
        curl -fsSL --retry 5 --retry-all-errors -o "$TMP/PKGBUILD" "$base/PKGBUILD"
        curl -fsSL --retry 5 --retry-all-errors -o "$TMP/config" "$base/config"
        curl -fsSL --retry 5 --retry-all-errors -o "$TMP/nct6687.c" \
            "https://raw.githubusercontent.com/Fred78290/nct6687d/${NCT6687D_COMMIT}/nct6687.c"
        printf '%s\n' "$CACHYOS_SOURCE_VARIANT" > "$TMP/source-variant"
        printf '%s\n' "$EXPECTED_PKGBASE" > "$TMP/pkgbase"
        printf '%s\n' "$PATCH_SET" > "$TMP/patch-set"
        printf '%s\n' 'generic_v3' > "$TMP/processor-opt"
        printf '%s\n' 'znver2' > "$TMP/cpu-tune"
        {
            (cd "$TMP" && sha256sum *)
            hash_files "$patch_dir"/*.patch
            hash_files "$ROOT_DIR/scripts/prepare-pkgbuild.sh" \
                "$ROOT_DIR/scripts/build-package.sh" \
                "$ROOT_DIR/scripts/resolve-nct6687d.sh" \
                "$ROOT_DIR/scripts/repo-package-helpers.sh"
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
                hash_files "$ROOT_DIR"/patches/mesa-git/*.patch
                hash_files "$ROOT_DIR"/scripts/resolve-cachyos-mesa.sh \
                    "$ROOT_DIR"/scripts/resolve-mesa-git.sh \
                    "$ROOT_DIR"/scripts/prepare-mesa-git-pkgbuild.sh \
                    "$ROOT_DIR"/scripts/build-mesa-git-package.sh \
                    "$ROOT_DIR"/scripts/repo-package-helpers.sh
            } | sha256sum | awk '{print $1}'
        fi
        ;;
esac
