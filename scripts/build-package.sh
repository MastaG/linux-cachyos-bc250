#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CACHYOS_SOURCE_VARIANT="${CACHYOS_SOURCE_VARIANT:-linux-cachyos-rc}"
BC250_PKGREL="${BC250_PKGREL:-1}"
SOURCE_FINGERPRINT="${SOURCE_FINGERPRINT:-local}"
BUILD_DIR="${BUILD_DIR:-${ROOT_DIR}/build/${CACHYOS_SOURCE_VARIANT}}"

"${ROOT_DIR}/scripts/prepare-pkgbuild.sh"
# shellcheck disable=SC1091
source "$BUILD_DIR/bc250-build.env"

cd -- "$BUILD_DIR"

# CachyOS currently exposes generic x86-64 levels, Zen 4, and native through
# _processor_opt. Keep the safe x86-64-v3 ISA baseline and tune scheduling/code
# generation for the BC-250's Zen 2 cores without enabling a wider ISA.
export _processor_opt="$PROCESSOR_OPT"
export KCFLAGS="${KCFLAGS:+${KCFLAGS} }-mtune=${CPU_TUNE}"
export MAKEFLAGS="${MAKEFLAGS:--j$(nproc)}"

# A fresh CI user has no personal OpenPGP keyring. Source integrity is still
# enforced by the upstream PKGBUILD's BLAKE2 checksums.
makepkg --syncdeps --noconfirm --cleanbuild --clean --skippgpcheck
makepkg --printsrcinfo > .SRCINFO

OUT_DIR="${ROOT_DIR}/out/${OUT_CHANNEL}"
rm -rf -- "$OUT_DIR"
mkdir -p -- "$OUT_DIR"

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

cd -- "$OUT_DIR"
repo-add -R "${REPO_NAME}.db.tar.zst" ./*.pkg.tar.zst

# GitHub release assets cannot act as useful symlinks. Publish regular copies
# with the names pacman requests: <repo>.db and <repo>.files.
cp -L --remove-destination "${REPO_NAME}.db.tar.zst" "${REPO_NAME}.db"
cp -L --remove-destination "${REPO_NAME}.files.tar.zst" "${REPO_NAME}.files"

cp -- "$BUILD_DIR/PKGBUILD" "$OUT_DIR/PKGBUILD"
cp -- "$BUILD_DIR/.SRCINFO" "$OUT_DIR/.SRCINFO"
cp -- "$BUILD_DIR/nct6687.c" "$OUT_DIR/nct6687.c"
cp -- "$BUILD_DIR/0003-nct6687d-hwmon.patch" "$OUT_DIR/0003-nct6687d-hwmon.patch"
cp -- "$BUILD_DIR/0004-gfx1013-mmio-pasid-route.patch" "$OUT_DIR/0004-gfx1013-mmio-pasid-route.patch"
cp -- "$BUILD_DIR/0005-gfx1013-compute-gfxoff-guard.patch" "$OUT_DIR/0005-gfx1013-compute-gfxoff-guard.patch"
cp -- "$BUILD_DIR/0006-gfx1013-scoped-pasid-type0.patch" "$OUT_DIR/0006-gfx1013-scoped-pasid-type0.patch"

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
    if [[ -z "${!field}" ]]; then
        printf 'ERROR: could not read %s from %s\n' "$field" "$BUILD_DIR/.SRCINFO" >&2
        sed -n '1,80p' "$BUILD_DIR/.SRCINFO" >&2
        exit 1
    fi
done

if [[ "$pkgbase" != "linux-cachyos-bc250" ]]; then
    printf 'ERROR: unexpected package base: %s\n' "$pkgbase" >&2
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
cp -- "$final_config" "$OUT_DIR/config"

cat > "$OUT_DIR/build-info.env" <<EOF_INFO
SOURCE_FINGERPRINT=${SOURCE_FINGERPRINT}
CACHYOS_SOURCE_VARIANT=${CACHYOS_SOURCE_VARIANT}
REPO_NAME=${REPO_NAME}
RELEASE_TAG=${RELEASE_TAG}
ISA_BASELINE=x86-64-v3
PROCESSOR_OPT=${PROCESSOR_OPT}
CPU_TUNE=${CPU_TUNE}
KCFLAGS=-mtune=${CPU_TUNE}
NCT6687D_COMMIT=${NCT6687D_COMMIT}
NCT6687D_SOURCE_URL=${NCT6687D_SOURCE_URL}
PKGBASE=${pkgbase}
PKGVER=${pkgver}
PKGREL=${pkgrel}
GITHUB_SHA=${GITHUB_SHA:-local}
BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF_INFO

cat > "$OUT_DIR/RELEASE_NOTES.md" <<EOF_NOTES
# BC-250 CachyOS kernel repository

- Upstream source package: \`${CACHYOS_SOURCE_VARIANT}\`
- Published package: \`${pkgbase}\`
- Version: \`${pkgver}-${pkgrel}\`
- ISA baseline: **x86-64-v3** (CachyOS \`${PROCESSOR_OPT}\`)
- CPU tuning: **Zen 2** (\`KCFLAGS=-mtune=${CPU_TUNE}\`)
- Patches: BC-250 6/8-core telemetry, GPU activity, safe GFXCLK fallback, Cyan Skillfish DP audio quirk, and GFX1013 compute/PASID stability fixes
- GFX1013 fixes: MMIO PASID TLB routing, compute GFXOFF guard, and scoped PASID type-0 invalidation
- Extra hwmon module: \`nct6687.ko\` from Fred78290/nct6687d commit \`${NCT6687D_COMMIT}\`
- Conflicting upstream module: \`nct6683\` disabled in this kernel configuration

The package and repository names stay unchanged when the upstream source is
switched from \`linux-cachyos-rc\` to \`linux-cachyos\`.
EOF_NOTES

printf '%s — %s-%s' "$pkgbase" "$pkgver" "$pkgrel" > "$OUT_DIR/release-title.txt"
sha256sum ./*.pkg.tar.zst ./*.db ./*.db.tar.zst ./*.files ./*.files.tar.zst \
    PKGBUILD config .SRCINFO build-info.env nct6687.c \
    0003-nct6687d-hwmon.patch \
    0004-gfx1013-mmio-pasid-route.patch \
    0005-gfx1013-compute-gfxoff-guard.patch \
    0006-gfx1013-scoped-pasid-type0.patch > SHA256SUMS

printf '==> Repository generated in %s\n' "$OUT_DIR"
ls -lh "$OUT_DIR"
