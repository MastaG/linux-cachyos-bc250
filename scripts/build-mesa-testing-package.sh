#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
MESA_TESTING_BUILD_DIR="${MESA_TESTING_BUILD_DIR:-${ROOT_DIR}/build/mesa-testing}"
OUT_DIR="${ROOT_DIR}/out/repo"

"${ROOT_DIR}/scripts/prepare-mesa-testing-pkgbuild.sh"
# shellcheck disable=SC1091
source "$MESA_TESTING_BUILD_DIR/bc250-mesa-testing-build.env"
# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/repo-package-helpers.sh"

cd -- "$MESA_TESTING_BUILD_DIR"
export MAKEFLAGS="${MAKEFLAGS:--j$(nproc)}"

makepkg --syncdeps --noconfirm --cleanbuild --clean --skippgpcheck
makepkg --printsrcinfo > .SRCINFO

shopt -s nullglob
mesa_testing_packages=("$MESA_TESTING_BUILD_DIR"/*.pkg.tar.zst)
(( ${#mesa_testing_packages[@]} > 0 )) || {
    printf 'ERROR: Mesa makepkg produced no .pkg.tar.zst files\n' >&2
    exit 1
}

mkdir -p -- "$OUT_DIR"
remove_pkgbase_from_repo "$OUT_DIR" mesa-testing
cp -- "${mesa_testing_packages[@]}" "$OUT_DIR/"
normalize_repo_package_filenames "$OUT_DIR"

cp -- "$MESA_TESTING_BUILD_DIR/PKGBUILD" "$OUT_DIR/mesa-testing-PKGBUILD"
cp -- "$MESA_TESTING_BUILD_DIR/.SRCINFO" "$OUT_DIR/mesa-testing.SRCINFO"
for patch in "$ROOT_DIR"/patches/mesa-testing/*.patch; do
    cp -- "$patch" "$OUT_DIR/$(basename "$patch")"
done

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
    ' "$MESA_TESTING_BUILD_DIR/.SRCINFO"
}

mesa_testing_pkgbase="$(srcinfo_value pkgbase)"
mesa_testing_pkgver="$(srcinfo_value pkgver)"
mesa_testing_pkgrel="$(srcinfo_value pkgrel)"
mesa_testing_epoch="$(srcinfo_value epoch)"

[[ "$mesa_testing_pkgbase" == mesa-testing && -n "$mesa_testing_pkgver" && -n "$mesa_testing_pkgrel" ]] || {
    printf 'ERROR: invalid Mesa .SRCINFO metadata\n' >&2
    sed -n '1,100p' "$MESA_TESTING_BUILD_DIR/.SRCINFO" >&2
    exit 1
}

cat > "$OUT_DIR/mesa-testing-info.env" <<EOF_INFO
MESA_TESTING_FINGERPRINT=${MESA_TESTING_FINGERPRINT:-unknown}
CACHYOS_MESA_COMMIT=${CACHYOS_MESA_COMMIT}
CACHYOS_MESA_PKGBUILD_URL=${CACHYOS_MESA_PKGBUILD_URL}
MESA_TESTING_PKGBASE=${mesa_testing_pkgbase}
MESA_TESTING_EPOCH=${mesa_testing_epoch}
MESA_TESTING_PKGVER=${mesa_testing_pkgver}
MESA_TESTING_PKGREL=${mesa_testing_pkgrel}
MESA_TESTING_APPLIED_PATCHES=${MESA_TESTING_APPLIED_PATCHES}
MESA_TESTING_MARCH=${MESA_TESTING_MARCH}
MESA_TESTING_MTUNE=${MESA_TESTING_MTUNE}
EOF_INFO

printf '==> Stable Mesa staged in %s\n' "$OUT_DIR"
printf '    Mesa: %s-%s\n' "$mesa_testing_pkgver" "$mesa_testing_pkgrel"
printf '    Packages built: %d\n' "${#mesa_testing_packages[@]}"
