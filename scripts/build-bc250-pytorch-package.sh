#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_DIR="${ROOT_DIR}/packages/bc250-pytorch"
BUILD_DIR="${BC250_PYTORCH_BUILD_DIR:-${ROOT_DIR}/build/bc250-pytorch}"
OUT_DIR="${ROOT_DIR}/out/repo"

# Our own PKGBUILD: the local files next to it, the standalone Python and the
# wheels from the rocm-pytorch release (rocm/build-rocm.sh), all checksummed.
# Work on a copy so a failed build never leaves state in the tracked source dir.
# Until rocm/update-pkgbuild.sh has pointed it at a build there is nothing to
# package; say so and stage nothing rather than failing the component.
# The info file is still written, with the fingerprint and no version, so the
# nightly run sees nothing changed instead of retrying every night.
if grep -q '^_build_id=PENDING$' "$PKG_DIR/PKGBUILD"; then
    mkdir -p -- "$OUT_DIR"
    cat > "$OUT_DIR/bc250-pytorch-info.env" <<EOF_INFO
BC250_PYTORCH_FINGERPRINT=${BC250_PYTORCH_FINGERPRINT:-unknown}
BC250_PYTORCH_PKGVER=
BC250_PYTORCH_PKGREL=
EOF_INFO
    printf '==> bc250-pytorch: no wheel build selected yet (rocm/update-pkgbuild.sh); nothing staged\n'
    exit 0
fi
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
    printf 'ERROR: expected exactly one bc250-pytorch package; found %d\n' "${#packages[@]}" >&2
    exit 1
}

mkdir -p -- "$OUT_DIR"
remove_pkgbase_from_repo "$OUT_DIR" bc250-pytorch
cp -- "${packages[@]}" "$OUT_DIR/"
normalize_repo_package_filenames "$OUT_DIR"

cp -- "$BUILD_DIR/PKGBUILD" "$OUT_DIR/bc250-pytorch-PKGBUILD"
cp -- "$BUILD_DIR/.SRCINFO" "$OUT_DIR/bc250-pytorch.SRCINFO"

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

bc250_pytorch_pkgbase="$(srcinfo_value pkgbase)"
bc250_pytorch_pkgver="$(srcinfo_value pkgver)"
bc250_pytorch_pkgrel="$(srcinfo_value pkgrel)"

[[ "$bc250_pytorch_pkgbase" == bc250-pytorch && -n "$bc250_pytorch_pkgver" && -n "$bc250_pytorch_pkgrel" ]] || {
    printf 'ERROR: invalid bc250-pytorch .SRCINFO metadata\n' >&2
    sed -n '1,100p' "$BUILD_DIR/.SRCINFO" >&2
    exit 1
}

cat > "$OUT_DIR/bc250-pytorch-info.env" <<EOF_INFO
BC250_PYTORCH_FINGERPRINT=${BC250_PYTORCH_FINGERPRINT:-unknown}
BC250_PYTORCH_PKGVER=${bc250_pytorch_pkgver}
BC250_PYTORCH_PKGREL=${bc250_pytorch_pkgrel}
EOF_INFO

printf '==> bc250-pytorch staged in %s\n' "$OUT_DIR"
printf '    Version: %s-%s\n' "$bc250_pytorch_pkgver" "$bc250_pytorch_pkgrel"
