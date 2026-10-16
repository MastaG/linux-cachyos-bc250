#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_DIR="${ROOT_DIR}/packages/bc250-fixes"
BUILD_DIR="${BC250_FIXES_BUILD_DIR:-${ROOT_DIR}/build/bc250-fixes}"
OUT_DIR="${ROOT_DIR}/out/repo"

# No upstream source: this PKGBUILD is entirely our own and source= is local
# files sitting next to it. Work on a copy anyway so a failed build never
# leaves state in the tracked source dir -- same shape as
# build-linux-cachyos-bc250-meta-package.sh and build-bc250-dual-audio-package.sh.
rm -rf -- "$BUILD_DIR"
mkdir -p -- "$BUILD_DIR"
cp -- "$PKG_DIR/PKGBUILD" "$PKG_DIR/bc250-fixes.sh" "$PKG_DIR/bc250-fixes.hook" "$BUILD_DIR/"

# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/repo-package-helpers.sh"

cd -- "$BUILD_DIR"
makepkg --syncdeps --noconfirm --cleanbuild --clean --skippgpcheck
makepkg --printsrcinfo > .SRCINFO

shopt -s nullglob
packages=("$BUILD_DIR"/*.pkg.tar.zst)
(( ${#packages[@]} == 1 )) || {
    printf 'ERROR: expected exactly one bc250-fixes package; found %d\n' "${#packages[@]}" >&2
    exit 1
}

mkdir -p -- "$OUT_DIR"
remove_pkgbase_from_repo "$OUT_DIR" bc250-fixes
cp -- "${packages[@]}" "$OUT_DIR/"
normalize_repo_package_filenames "$OUT_DIR"

cp -- "$BUILD_DIR/PKGBUILD" "$OUT_DIR/bc250-fixes-PKGBUILD"
cp -- "$BUILD_DIR/.SRCINFO" "$OUT_DIR/bc250-fixes.SRCINFO"

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

bc250_fixes_pkgbase="$(srcinfo_value pkgbase)"
bc250_fixes_pkgver="$(srcinfo_value pkgver)"
bc250_fixes_pkgrel="$(srcinfo_value pkgrel)"

[[ "$bc250_fixes_pkgbase" == bc250-fixes && -n "$bc250_fixes_pkgver" && -n "$bc250_fixes_pkgrel" ]] || {
    printf 'ERROR: invalid bc250-fixes .SRCINFO metadata\n' >&2
    sed -n '1,100p' "$BUILD_DIR/.SRCINFO" >&2
    exit 1
}

cat > "$OUT_DIR/bc250-fixes-info.env" <<EOF_INFO
BC250_FIXES_FINGERPRINT=${BC250_FIXES_FINGERPRINT:-unknown}
BC250_FIXES_PKGVER=${bc250_fixes_pkgver}
BC250_FIXES_PKGREL=${bc250_fixes_pkgrel}
EOF_INFO

printf '==> bc250-fixes staged in %s\n' "$OUT_DIR"
printf '    Version: %s-%s\n' "$bc250_fixes_pkgver" "$bc250_fixes_pkgrel"
