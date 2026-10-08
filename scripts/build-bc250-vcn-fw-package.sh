#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_DIR="${ROOT_DIR}/packages/bc250-vcn-fw"
BUILD_DIR="${BC250_VCN_FW_BUILD_DIR:-${ROOT_DIR}/build/bc250-vcn-fw}"
OUT_DIR="${ROOT_DIR}/out/repo"

# No upstream source: this PKGBUILD is entirely our own and source= is local
# files sitting next to it. Work on a copy anyway so a failed build never
# leaves state in the tracked source dir -- same shape as
# build-linux-cachyos-bc250-meta-package.sh and build-bc250-dual-audio-package.sh.
rm -rf -- "$BUILD_DIR"
mkdir -p -- "$BUILD_DIR"
# makepkg resolves local sources by file name, so everything goes in flat.
cp -- "$PKG_DIR"/* "$BUILD_DIR/"

# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/repo-package-helpers.sh"

cd -- "$BUILD_DIR"
makepkg --syncdeps --noconfirm --cleanbuild --clean --skippgpcheck
makepkg --printsrcinfo > .SRCINFO

shopt -s nullglob
packages=("$BUILD_DIR"/*.pkg.tar.zst)
(( ${#packages[@]} == 1 )) || {
    printf 'ERROR: expected exactly one bc250-vcn-fw package; found %d\n' "${#packages[@]}" >&2
    exit 1
}

mkdir -p -- "$OUT_DIR"
remove_pkgbase_from_repo "$OUT_DIR" bc250-vcn-fw
cp -- "${packages[@]}" "$OUT_DIR/"
normalize_repo_package_filenames "$OUT_DIR"

cp -- "$BUILD_DIR/PKGBUILD" "$OUT_DIR/bc250-vcn-fw-PKGBUILD"
cp -- "$BUILD_DIR/.SRCINFO" "$OUT_DIR/bc250-vcn-fw.SRCINFO"

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

bc250_vcn_fw_pkgbase="$(srcinfo_value pkgbase)"
bc250_vcn_fw_pkgver="$(srcinfo_value pkgver)"
bc250_vcn_fw_pkgrel="$(srcinfo_value pkgrel)"

[[ "$bc250_vcn_fw_pkgbase" == bc250-vcn-fw && -n "$bc250_vcn_fw_pkgver" && -n "$bc250_vcn_fw_pkgrel" ]] || {
    printf 'ERROR: invalid bc250-vcn-fw .SRCINFO metadata\n' >&2
    sed -n '1,100p' "$BUILD_DIR/.SRCINFO" >&2
    exit 1
}

cat > "$OUT_DIR/bc250-vcn-fw-info.env" <<EOF_INFO
BC250_VCN_FW_FINGERPRINT=${BC250_VCN_FW_FINGERPRINT:-unknown}
BC250_VCN_FW_PKGVER=${bc250_vcn_fw_pkgver}
BC250_VCN_FW_PKGREL=${bc250_vcn_fw_pkgrel}
EOF_INFO

printf '==> bc250-vcn-fw staged in %s\n' "$OUT_DIR"
printf '    Version: %s-%s\n' "$bc250_vcn_fw_pkgver" "$bc250_vcn_fw_pkgrel"
