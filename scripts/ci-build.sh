#!/usr/bin/env bash
set -Eeuo pipefail

: "${CACHYOS_SOURCE_VARIANT:?CACHYOS_SOURCE_VARIANT is required}"
: "${BC250_PKGREL:?BC250_PKGREL is required}"
: "${SOURCE_FINGERPRINT:?SOURCE_FINGERPRINT is required}"
: "${NCT6687D_COMMIT:?NCT6687D_COMMIT is required}"

pacman -Sy --noconfirm archlinux-keyring
pacman -Syu --noconfirm --needed base-devel curl git libarchive sudo

if ! id builder >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash builder
fi
printf 'builder ALL=(ALL:ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/builder
chmod 0440 /etc/sudoers.d/builder
chown -R builder:builder /workspace

# Do not pass CI or GITHUB_RUN_ID to makepkg. CachyOS otherwise intentionally
# switches to a smaller CI config instead of its normal performance config.
runuser -u builder -- env \
    HOME=/home/builder \
    PATH="$PATH" \
    CACHYOS_SOURCE_VARIANT="$CACHYOS_SOURCE_VARIANT" \
    BC250_PKGREL="$BC250_PKGREL" \
    SOURCE_FINGERPRINT="$SOURCE_FINGERPRINT" \
    NCT6687D_COMMIT="$NCT6687D_COMMIT" \
    GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-unknown/unknown}" \
    GITHUB_SHA="${GITHUB_SHA:-unknown}" \
    bash /workspace/scripts/build-package.sh
