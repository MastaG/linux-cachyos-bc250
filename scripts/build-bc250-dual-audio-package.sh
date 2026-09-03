#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_DIR="${ROOT_DIR}/packages/bc250-dual-audio"
BUILD_DIR="${BC250_DUAL_AUDIO_BUILD_DIR:-${ROOT_DIR}/build/bc250-dual-audio}"
OUT_DIR="${ROOT_DIR}/out/repo"

# Unlike the kernel/Mesa components, this PKGBUILD is not derived from an
# upstream PKGBUILD we fetch and rewrite -- it is our own, and its source= is
# already pinned to an immutable tag. There is nothing to "prepare"; just work
# on a copy so a failed build never leaves state in the tracked source dir.
rm -rf -- "$BUILD_DIR"
mkdir -p -- "$BUILD_DIR"
cp -- "$PKG_DIR/PKGBUILD" "$PKG_DIR/bc250-dual-audio.install" "$BUILD_DIR/"

# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/repo-package-helpers.sh"

cd -- "$BUILD_DIR"
makepkg --syncdeps --noconfirm --cleanbuild --clean --skippgpcheck
makepkg --printsrcinfo > .SRCINFO

shopt -s nullglob
packages=("$BUILD_DIR"/*.pkg.tar.zst)
(( ${#packages[@]} == 1 )) || {
    printf 'ERROR: expected exactly one bc250-dual-audio package; found %d\n' "${#packages[@]}" >&2
    exit 1
}

mkdir -p -- "$OUT_DIR"
remove_pkgbase_from_repo "$OUT_DIR" bc250-dual-audio
cp -- "${packages[@]}" "$OUT_DIR/"
normalize_repo_package_filenames "$OUT_DIR"

cp -- "$BUILD_DIR/PKGBUILD" "$OUT_DIR/bc250-dual-audio-PKGBUILD"
cp -- "$BUILD_DIR/.SRCINFO" "$OUT_DIR/bc250-dual-audio.SRCINFO"

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

bc250_dual_audio_pkgbase="$(srcinfo_value pkgbase)"
bc250_dual_audio_pkgver="$(srcinfo_value pkgver)"
bc250_dual_audio_pkgrel="$(srcinfo_value pkgrel)"

[[ "$bc250_dual_audio_pkgbase" == bc250-dual-audio && -n "$bc250_dual_audio_pkgver" && -n "$bc250_dual_audio_pkgrel" ]] || {
    printf 'ERROR: invalid bc250-dual-audio .SRCINFO metadata\n' >&2
    sed -n '1,100p' "$BUILD_DIR/.SRCINFO" >&2
    exit 1
}

cat > "$OUT_DIR/bc250-dual-audio-info.env" <<EOF_INFO
BC250_DUAL_AUDIO_FINGERPRINT=${BC250_DUAL_AUDIO_FINGERPRINT:-unknown}
BC250_DUAL_AUDIO_PKGVER=${bc250_dual_audio_pkgver}
BC250_DUAL_AUDIO_PKGREL=${bc250_dual_audio_pkgrel}
EOF_INFO

printf '==> bc250-dual-audio staged in %s\n' "$OUT_DIR"
printf '    Version: %s-%s\n' "$bc250_dual_audio_pkgver" "$bc250_dual_audio_pkgrel"
