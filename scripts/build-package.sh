#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CACHYOS_SOURCE_VARIANT="${CACHYOS_SOURCE_VARIANT:-linux-cachyos}"
BC250_PKGREL="${BC250_PKGREL:-1}"
BUILD_DIR="${BUILD_DIR:-${ROOT_DIR}/build/${CACHYOS_SOURCE_VARIANT}}"

"${ROOT_DIR}/scripts/prepare-pkgbuild.sh"
# shellcheck disable=SC1091
source "$BUILD_DIR/bc250-build.env"
# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/repo-package-helpers.sh"

case "$KERNEL_ID" in
    stable) COMPONENT_FINGERPRINT="${KERNEL_STABLE_FINGERPRINT:-local}" ;;
    rc)     COMPONENT_FINGERPRINT="${KERNEL_RC_FINGERPRINT:-local}" ;;
    bore)   COMPONENT_FINGERPRINT="${KERNEL_BORE_FINGERPRINT:-local}" ;;
    *) printf 'ERROR: unknown KERNEL_ID: %s\n' "$KERNEL_ID" >&2; exit 1 ;;
esac

cd -- "$BUILD_DIR"

# Keep an x86-64-v3 ISA baseline and tune scheduling/code generation for Zen 2.
# makepkg's ccache integration is enabled by ci-build.sh for CI builds.
export _processor_opt="$PROCESSOR_OPT"
export KCFLAGS="${KCFLAGS:+${KCFLAGS} }-mtune=${CPU_TUNE}"
export MAKEFLAGS="${MAKEFLAGS:--j$(nproc)}"

# A fresh CI user has no personal OpenPGP keyring. Source integrity remains
# enforced by the upstream PKGBUILD's BLAKE2 checksums.
makepkg --syncdeps --noconfirm --cleanbuild --clean --skippgpcheck
makepkg --printsrcinfo > .SRCINFO

OUT_DIR="${ROOT_DIR}/out/${OUT_CHANNEL}"
mkdir -p -- "$OUT_DIR"

# Replace only this kernel family. The other two kernels and all Mesa packages
# remain staged from the previous fixed release.
remove_pkgbase_from_repo "$OUT_DIR" "$EXPECTED_PKGBASE"

shopt -s nullglob
packages=("$BUILD_DIR"/*.pkg.tar.zst)
(( ${#packages[@]} > 0 )) || {
    printf 'ERROR: makepkg produced no .pkg.tar.zst files\n' >&2
    exit 1
}

module_listing="$(for package in "${packages[@]}"; do bsdtar -tf "$package"; done)"
if ! grep -Eq '(^|/)nct6687\.ko(\.(zst|xz|gz))?$' <<<"$module_listing"; then
    printf 'ERROR: nct6687 kernel module is missing from generated packages\n' >&2
    exit 1
fi
if grep -Eq '(^|/)nct6683\.ko(\.(zst|xz|gz))?$' <<<"$module_listing"; then
    printf 'ERROR: conflicting nct6683 kernel module is present in generated packages\n' >&2
    exit 1
fi

cp -- "${packages[@]}" "$OUT_DIR/"

srcinfo_value() {
    local key="$1"
    awk -F '=' -v key="$key" '
        {
            lhs = $1
            gsub(/^[[:space:]]+|[[:space:]]+$/, "", lhs)
            if (lhs == key) {
                value = substr($0, index($0, "=") + 1)
                gsub(/^[[:space:]]+|[[:space:]]+$/, "", value)
                print value
                exit
            }
        }
    ' "$BUILD_DIR/.SRCINFO"
}

pkgbase="$(srcinfo_value pkgbase)"
pkgver="$(srcinfo_value pkgver)"
pkgrel="$(srcinfo_value pkgrel)"

for field in pkgbase pkgver pkgrel; do
    [[ -n "${!field}" ]] || {
        printf 'ERROR: could not read %s from %s\n' "$field" "$BUILD_DIR/.SRCINFO" >&2
        sed -n '1,80p' "$BUILD_DIR/.SRCINFO" >&2
        exit 1
    }
done

if [[ "$pkgbase" != "$EXPECTED_PKGBASE" ]]; then
    printf 'ERROR: unexpected package base: %s (expected %s)\n' "$pkgbase" "$EXPECTED_PKGBASE" >&2
    exit 1
fi

final_config="$BUILD_DIR/config-${pkgver}-${pkgrel}${pkgbase#linux}"
if [[ ! -f "$final_config" ]]; then
    printf 'ERROR: final generated kernel config not found: %s\n' "$final_config" >&2
    find "$BUILD_DIR" -maxdepth 1 -type f -name 'config-*' -print >&2
    exit 1
fi
grep -qx 'CONFIG_SENSORS_NCT6687=m' "$final_config" || {
    printf 'ERROR: final config does not build CONFIG_SENSORS_NCT6687=m\n' >&2
    exit 1
}
grep -qx '# CONFIG_SENSORS_NCT6683 is not set' "$final_config" || {
    printf 'ERROR: final config did not disable CONFIG_SENSORS_NCT6683\n' >&2
    exit 1
}

# Publish unambiguous build inputs for all three kernel families.
cp -- "$BUILD_DIR/PKGBUILD" "$OUT_DIR/kernel-${KERNEL_ID}-PKGBUILD"
cp -- "$BUILD_DIR/.SRCINFO" "$OUT_DIR/kernel-${KERNEL_ID}.SRCINFO"
cp -- "$final_config" "$OUT_DIR/kernel-${KERNEL_ID}-config"
cp -- "$BUILD_DIR/nct6687.c" "$OUT_DIR/nct6687.c"

for patch in "$ROOT_DIR/patches/$PATCH_SET"/*.patch; do
    [[ -f "$patch" ]] || continue
    cp -- "$patch" "$OUT_DIR/${PATCH_SET}-$(basename "$patch")"
done

cat > "$OUT_DIR/kernel-${KERNEL_ID}-info.env" <<EOF_KERNEL
KERNEL_ID=${KERNEL_ID}
KERNEL_FINGERPRINT=${COMPONENT_FINGERPRINT}
CACHYOS_SOURCE_VARIANT=${CACHYOS_SOURCE_VARIANT}
PATCH_SET=${PATCH_SET}
KERNEL_PKGBASE=${pkgbase}
KERNEL_PKGVER=${pkgver}
KERNEL_PKGREL=${pkgrel}
ISA_BASELINE=x86-64-v3
PROCESSOR_OPT=${PROCESSOR_OPT}
CPU_TUNE=${CPU_TUNE}
KCFLAGS=-mtune=${CPU_TUNE}
NCT6687D_COMMIT=${NCT6687D_COMMIT}
NCT6687D_SOURCE_URL=${NCT6687D_SOURCE_URL}
EOF_KERNEL

printf '==> Built %s kernel family: %s %s-%s\n' "$KERNEL_ID" "$pkgbase" "$pkgver" "$pkgrel"
