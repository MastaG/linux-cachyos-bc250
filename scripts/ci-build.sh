#!/usr/bin/env bash
set -Eeuo pipefail

: "${CACHYOS_SOURCE_VARIANT:?CACHYOS_SOURCE_VARIANT is required}"
: "${BC250_PKGREL:?BC250_PKGREL is required}"
: "${CACHYOS_MESA_COMMIT:?CACHYOS_MESA_COMMIT is required}"
: "${MESA_GIT_COMMIT:?MESA_GIT_COMMIT is required}"
: "${KERNEL_FINGERPRINT:?KERNEL_FINGERPRINT is required}"
: "${MESA_FINGERPRINT:?MESA_FINGERPRINT is required}"
: "${LIB32_MESA_FINGERPRINT:?LIB32_MESA_FINGERPRINT is required}"
: "${MESA_GIT_FINGERPRINT:?MESA_GIT_FINGERPRINT is required}"

BUILD_KERNEL="${BUILD_KERNEL:-false}"
BUILD_MESA="${BUILD_MESA:-false}"
BUILD_LIB32_MESA="${BUILD_LIB32_MESA:-false}"
BUILD_MESA_GIT="${BUILD_MESA_GIT:-false}"
KERNEL_GUARD_REASON="${KERNEL_GUARD_REASON:-none}"
NCT6687D_COMMIT="${NCT6687D_COMMIT:-}"

for var in BUILD_KERNEL BUILD_MESA BUILD_LIB32_MESA BUILD_MESA_GIT; do
    value="${!var}"
    [[ "$value" == true || "$value" == false ]] || {
        printf 'ERROR: %s must be true or false: %s\n' "$var" "$value" >&2
        exit 1
    }
done

if [[ "$BUILD_KERNEL" == true ]]; then
    : "${NCT6687D_COMMIT:?NCT6687D_COMMIT is required when BUILD_KERNEL=true}"
    # build-package.sh starts a fresh out/repo. Never allow that to discard
    # unchanged Mesa components: a kernel rebuild must repopulate all of them.
    [[ "$BUILD_MESA" == true && "$BUILD_LIB32_MESA" == true && "$BUILD_MESA_GIT" == true ]] || {
        printf 'ERROR: kernel rebuild requires all Mesa components to rebuild too\n' >&2
        exit 1
    }
fi

# Stable lib32-mesa and mesa-git's lib32-mesa-git output need Arch's
# multilib repository inside the clean build container.  Do not depend on
# the image shipping a particular commented-out [multilib] template: current
# and future archlinux:base-devel images may omit or reformat that block.
if ! grep -Eq '^[[:space:]]*\[multilib\][[:space:]]*$' /etc/pacman.conf; then
    cat >> /etc/pacman.conf <<'EOF_MULTILIB'

[multilib]
Include = /etc/pacman.d/mirrorlist
EOF_MULTILIB
fi

# Refresh after enabling multilib and fail early with a useful error instead
# of letting makepkg report dozens of unresolved lib32-* dependencies.
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
pacman -Syu --noconfirm --needed base-devel curl git libarchive sudo

if ! id builder >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash builder
fi
printf 'builder ALL=(ALL:ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/builder
chmod 0440 /etc/sudoers.d/builder
chown -R builder:builder /workspace

# Do not pass CI or GITHUB_RUN_ID to makepkg. CachyOS otherwise intentionally
# switches to smaller CI configurations instead of its normal package config.
runuser -u builder -- env \
    HOME=/home/builder \
    PATH="$PATH" \
    CACHYOS_SOURCE_VARIANT="$CACHYOS_SOURCE_VARIANT" \
    BUILD_KERNEL="$BUILD_KERNEL" \
    BUILD_MESA="$BUILD_MESA" \
    BUILD_LIB32_MESA="$BUILD_LIB32_MESA" \
    BUILD_MESA_GIT="$BUILD_MESA_GIT" \
    KERNEL_GUARD_REASON="$KERNEL_GUARD_REASON" \
    BC250_PKGREL="$BC250_PKGREL" \
    MESA_PKGREL="$BC250_PKGREL" \
    LIB32_MESA_PKGREL="$BC250_PKGREL" \
    MESA_GIT_PKGREL="$BC250_PKGREL" \
    SOURCE_FINGERPRINT="${SOURCE_FINGERPRINT:-componentized}" \
    KERNEL_FINGERPRINT="$KERNEL_FINGERPRINT" \
    MESA_FINGERPRINT="$MESA_FINGERPRINT" \
    LIB32_MESA_FINGERPRINT="$LIB32_MESA_FINGERPRINT" \
    MESA_GIT_FINGERPRINT="$MESA_GIT_FINGERPRINT" \
    NCT6687D_COMMIT="$NCT6687D_COMMIT" \
    CACHYOS_MESA_COMMIT="$CACHYOS_MESA_COMMIT" \
    MESA_GIT_COMMIT="$MESA_GIT_COMMIT" \
    GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-unknown/unknown}" \
    GITHUB_SHA="${GITHUB_SHA:-unknown}" \
    bash -c '
        set -Eeuo pipefail
        if [[ "$BUILD_KERNEL" == true ]]; then
            /workspace/scripts/build-package.sh
        else
            echo "==> Kernel build skipped: $KERNEL_GUARD_REASON"
        fi
        if [[ "$BUILD_MESA" == true ]]; then /workspace/scripts/build-mesa-package.sh; fi
        if [[ "$BUILD_LIB32_MESA" == true ]]; then /workspace/scripts/build-lib32-mesa-package.sh; fi
        if [[ "$BUILD_MESA_GIT" == true ]]; then /workspace/scripts/build-mesa-git-package.sh; fi
        /workspace/scripts/finalize-repository.sh
    '
