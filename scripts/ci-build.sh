#!/usr/bin/env bash
set -Eeuo pipefail

: "${BC250_PKGREL:?BC250_PKGREL is required}"
: "${CACHYOS_MESA_COMMIT:?CACHYOS_MESA_COMMIT is required}"
: "${MESA_GIT_COMMIT:?MESA_GIT_COMMIT is required}"
: "${KERNEL_STABLE_FINGERPRINT:?KERNEL_STABLE_FINGERPRINT is required}"
: "${KERNEL_RC_FINGERPRINT:?KERNEL_RC_FINGERPRINT is required}"
: "${KERNEL_BORE_FINGERPRINT:?KERNEL_BORE_FINGERPRINT is required}"
: "${MESA_FINGERPRINT:?MESA_FINGERPRINT is required}"
: "${LIB32_MESA_FINGERPRINT:?LIB32_MESA_FINGERPRINT is required}"
: "${MESA_GIT_FINGERPRINT:?MESA_GIT_FINGERPRINT is required}"
: "${MESA_TESTING_FINGERPRINT:?MESA_TESTING_FINGERPRINT is required}"
: "${LIB32_MESA_TESTING_FINGERPRINT:?LIB32_MESA_TESTING_FINGERPRINT is required}"

BUILD_KERNEL_STABLE="${BUILD_KERNEL_STABLE:-false}"
BUILD_KERNEL_RC="${BUILD_KERNEL_RC:-false}"
BUILD_KERNEL_BORE="${BUILD_KERNEL_BORE:-false}"
BUILD_MESA="${BUILD_MESA:-false}"
BUILD_LIB32_MESA="${BUILD_LIB32_MESA:-false}"
BUILD_MESA_GIT="${BUILD_MESA_GIT:-false}"
BUILD_MESA_TESTING="${BUILD_MESA_TESTING:-false}"
BUILD_LIB32_MESA_TESTING="${BUILD_LIB32_MESA_TESTING:-false}"
NCT6687D_COMMIT="${NCT6687D_COMMIT:-}"

for var in BUILD_KERNEL_STABLE BUILD_KERNEL_RC BUILD_KERNEL_BORE BUILD_MESA BUILD_LIB32_MESA \
           BUILD_MESA_GIT BUILD_MESA_TESTING BUILD_LIB32_MESA_TESTING; do
    value="${!var}"
    [[ "$value" == true || "$value" == false ]] || {
        printf 'ERROR: %s must be true or false: %s\n' "$var" "$value" >&2
        exit 1
    }
done

if [[ "$BUILD_KERNEL_STABLE" == true || "$BUILD_KERNEL_RC" == true || "$BUILD_KERNEL_BORE" == true ]]; then
    : "${NCT6687D_COMMIT:?NCT6687D_COMMIT is required when a kernel is built}"
fi

# Stable lib32-mesa and mesa-git's lib32-mesa-git output need Arch multilib.
if ! grep -Eq '^[[:space:]]*\[multilib\][[:space:]]*$' /etc/pacman.conf; then
    cat >> /etc/pacman.conf <<'EOF_MULTILIB'

[multilib]
Include = /etc/pacman.d/mirrorlist
EOF_MULTILIB
fi

pacman -Syy --noconfirm
if ! pacman-conf --repo-list | grep -qx multilib; then
    printf 'ERROR: Arch multilib repository is not enabled in /etc/pacman.conf\n' >&2
    exit 1
fi
if ! pacman -Si lib32-clang >/dev/null 2>&1; then
    printf 'ERROR: multilib is enabled but lib32-clang cannot be resolved\n' >&2
    exit 1
fi

pacman -S --noconfirm --needed archlinux-keyring
pacman -Syu --noconfirm --needed base-devel ccache curl git libarchive sudo

if ! id builder >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash builder
fi
printf 'builder ALL=(ALL:ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/builder
chmod 0440 /etc/sudoers.d/builder
chown -R builder:builder /workspace

# ccache is shared by every makepkg invocation below: all three kernels,
# stable Mesa, stable lib32-mesa and mesa-git/lib32-mesa-git. BUILDENV enables
# makepkg's native integration; prepending the wrapper directory makes the
# compiler routing explicit for Meson and nested build systems as well.
: "${CCACHE_DIR:=/ccache}"
: "${CCACHE_MAXSIZE:=30G}"
: "${CCACHE_COMPILERCHECK:=content}"
CCACHE_WRAPPER_DIR=/usr/lib/ccache/bin
mkdir -p -- "$CCACHE_DIR"
chown builder:builder "$CCACHE_DIR"
sed -i 's/!ccache/ccache/g' /etc/makepkg.conf
if ! grep -Eq '^[[:space:]]*BUILDENV=.*[([:space:]]ccache([[:space:]]|\))' /etc/makepkg.conf; then
    printf 'ERROR: failed to enable ccache in /etc/makepkg.conf BUILDENV\n' >&2
    grep -n '^[[:space:]]*BUILDENV=' /etc/makepkg.conf >&2 || true
    exit 1
fi
[[ -x "$CCACHE_WRAPPER_DIR/gcc" ]] || {
    printf 'ERROR: ccache compiler wrappers not found in %s\n' "$CCACHE_WRAPPER_DIR" >&2
    exit 1
}

# Do not pass CI or GITHUB_RUN_ID to makepkg. CachyOS otherwise intentionally
# selects its reduced CI kernel configuration.
runuser -u builder -- env \
    HOME=/home/builder \
    PATH="$CCACHE_WRAPPER_DIR:$PATH" \
    CCACHE_DIR="$CCACHE_DIR" \
    CCACHE_MAXSIZE="$CCACHE_MAXSIZE" \
    CCACHE_COMPILERCHECK="$CCACHE_COMPILERCHECK" \
    BUILD_KERNEL_STABLE="$BUILD_KERNEL_STABLE" \
    BUILD_KERNEL_RC="$BUILD_KERNEL_RC" \
    BUILD_KERNEL_BORE="$BUILD_KERNEL_BORE" \
    BUILD_MESA="$BUILD_MESA" \
    BUILD_LIB32_MESA="$BUILD_LIB32_MESA" \
    BUILD_MESA_GIT="$BUILD_MESA_GIT" \
    BUILD_MESA_TESTING="$BUILD_MESA_TESTING" \
    BUILD_LIB32_MESA_TESTING="$BUILD_LIB32_MESA_TESTING" \
    BC250_PKGREL="$BC250_PKGREL" \
    MESA_PKGREL="$BC250_PKGREL" \
    LIB32_MESA_PKGREL="$BC250_PKGREL" \
    MESA_GIT_PKGREL="$BC250_PKGREL" \
    MESA_TESTING_PKGREL="$BC250_PKGREL" \
    LIB32_MESA_TESTING_PKGREL="$BC250_PKGREL" \
    SOURCE_FINGERPRINT="${SOURCE_FINGERPRINT:-componentized}" \
    KERNEL_STABLE_FINGERPRINT="$KERNEL_STABLE_FINGERPRINT" \
    KERNEL_RC_FINGERPRINT="$KERNEL_RC_FINGERPRINT" \
    KERNEL_BORE_FINGERPRINT="$KERNEL_BORE_FINGERPRINT" \
    MESA_FINGERPRINT="$MESA_FINGERPRINT" \
    LIB32_MESA_FINGERPRINT="$LIB32_MESA_FINGERPRINT" \
    MESA_GIT_FINGERPRINT="$MESA_GIT_FINGERPRINT" \
    MESA_TESTING_FINGERPRINT="$MESA_TESTING_FINGERPRINT" \
    LIB32_MESA_TESTING_FINGERPRINT="$LIB32_MESA_TESTING_FINGERPRINT" \
    NCT6687D_COMMIT="$NCT6687D_COMMIT" \
    CACHYOS_MESA_COMMIT="$CACHYOS_MESA_COMMIT" \
    MESA_GIT_COMMIT="$MESA_GIT_COMMIT" \
    GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-unknown/unknown}" \
    GITHUB_SHA="${GITHUB_SHA:-unknown}" \
    bash -c '
        set -Eeuo pipefail
        ccache -M "$CCACHE_MAXSIZE" >/dev/null
        echo "==> ccache: persistent cache at $CCACHE_DIR (max $CCACHE_MAXSIZE)"
        echo "==> ccache compiler wrapper: $(command -v gcc)"
        ccache -z >/dev/null
        _ccache_stats() {
            echo "==> ccache statistics for this build"
            ccache -s || true
        }
        trap _ccache_stats EXIT

        if [[ "$BUILD_KERNEL_STABLE" == true ]]; then
            CACHYOS_SOURCE_VARIANT=linux-cachyos /workspace/scripts/build-package.sh
        fi
        if [[ "$BUILD_KERNEL_RC" == true ]]; then
            CACHYOS_SOURCE_VARIANT=linux-cachyos-rc /workspace/scripts/build-package.sh
        fi
        if [[ "$BUILD_KERNEL_BORE" == true ]]; then
            CACHYOS_SOURCE_VARIANT=linux-cachyos-bore /workspace/scripts/build-package.sh
        fi
        if [[ "$BUILD_MESA" == true ]]; then /workspace/scripts/build-mesa-package.sh; fi
        if [[ "$BUILD_LIB32_MESA" == true ]]; then /workspace/scripts/build-lib32-mesa-package.sh; fi
        if [[ "$BUILD_MESA_GIT" == true ]]; then /workspace/scripts/build-mesa-git-package.sh; fi
        if [[ "$BUILD_MESA_TESTING" == true ]]; then /workspace/scripts/build-mesa-testing-package.sh; fi
        if [[ "$BUILD_LIB32_MESA_TESTING" == true ]]; then /workspace/scripts/build-lib32-mesa-testing-package.sh; fi

        /workspace/scripts/finalize-repository.sh
    '
