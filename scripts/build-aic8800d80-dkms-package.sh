#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_DIR="${ROOT_DIR}/packages/aic8800d80-dkms"
BUILD_DIR="${AIC8800D80_DKMS_BUILD_DIR:-${ROOT_DIR}/build/aic8800d80-dkms}"
OUT_DIR="${ROOT_DIR}/out/repo"

# Unlike the kernel/Mesa components, this PKGBUILD is not derived from an
# upstream PKGBUILD we fetch and rewrite -- it is our own, and its source= is
# already pinned to an immutable tag. There is nothing to "prepare"; just work
# on a copy so a failed build never leaves state in the tracked source dir.
rm -rf -- "$BUILD_DIR"
mkdir -p -- "$BUILD_DIR"
cp -- "$PKG_DIR/PKGBUILD" "$BUILD_DIR/"

# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/repo-package-helpers.sh"

cd -- "$BUILD_DIR"
makepkg --syncdeps --noconfirm --cleanbuild --clean --skippgpcheck
makepkg --printsrcinfo > .SRCINFO

shopt -s nullglob
packages=("$BUILD_DIR"/*.pkg.tar.zst)
(( ${#packages[@]} == 1 )) || {
    printf 'ERROR: expected exactly one aic8800d80-dkms package; found %d\n' "${#packages[@]}" >&2
    exit 1
}

mkdir -p -- "$OUT_DIR"
remove_pkgbase_from_repo "$OUT_DIR" aic8800d80-dkms
cp -- "${packages[@]}" "$OUT_DIR/"
normalize_repo_package_filenames "$OUT_DIR"

cp -- "$BUILD_DIR/PKGBUILD" "$OUT_DIR/aic8800d80-dkms-PKGBUILD"
cp -- "$BUILD_DIR/.SRCINFO" "$OUT_DIR/aic8800d80-dkms.SRCINFO"

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

aic8800d80_dkms_pkgbase="$(srcinfo_value pkgbase)"
aic8800d80_dkms_pkgver="$(srcinfo_value pkgver)"
aic8800d80_dkms_pkgrel="$(srcinfo_value pkgrel)"

[[ "$aic8800d80_dkms_pkgbase" == aic8800d80-dkms && -n "$aic8800d80_dkms_pkgver" && -n "$aic8800d80_dkms_pkgrel" ]] || {
    printf 'ERROR: invalid aic8800d80-dkms .SRCINFO metadata\n' >&2
    sed -n '1,100p' "$BUILD_DIR/.SRCINFO" >&2
    exit 1
}

cat > "$OUT_DIR/aic8800d80-dkms-info.env" <<EOF_INFO
AIC8800D80_DKMS_FINGERPRINT=${AIC8800D80_DKMS_FINGERPRINT:-unknown}
AIC8800D80_DKMS_PKGVER=${aic8800d80_dkms_pkgver}
AIC8800D80_DKMS_PKGREL=${aic8800d80_dkms_pkgrel}
EOF_INFO

printf '==> aic8800d80-dkms staged in %s\n' "$OUT_DIR"
printf '    Version: %s-%s\n' "$aic8800d80_dkms_pkgver" "$aic8800d80_dkms_pkgrel"
