#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${LIB32_MESA_TESTING_BUILD_DIR:-${ROOT_DIR}/build/lib32-mesa-testing}"
OUT_DIR="${ROOT_DIR}/out/repo"

"${ROOT_DIR}/scripts/prepare-lib32-mesa-testing-pkgbuild.sh"
# shellcheck disable=SC1091
source "$BUILD_DIR/bc250-lib32-mesa-testing-build.env"
# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/repo-package-helpers.sh"

cd -- "$BUILD_DIR"
export MAKEFLAGS="${MAKEFLAGS:--j$(nproc)}"
makepkg --syncdeps --noconfirm --cleanbuild --clean --skippgpcheck
makepkg --printsrcinfo > .SRCINFO

shopt -s nullglob
packages=("$BUILD_DIR"/*.pkg.tar.zst)
(( ${#packages[@]} > 0 )) || {
    printf 'ERROR: lib32-mesa-testing makepkg produced no .pkg.tar.zst files\n' >&2
    exit 1
}

# Must not contain the architecture-independent drirc/ICD files: those ship in
# the 64-bit package, and duplicating them here breaks co-installation.
expected_files="usr/lib32/libvulkan_radeon.so
usr/share/licenses/lib32-vulkan-radeon-testing/license.rst"
for pkg in "${packages[@]}"; do
    actual_files="$(bsdtar -tf "$pkg" | grep -vE '^\.|/$' | LC_ALL=C sort)"
    [[ "$actual_files" == "$expected_files" ]] || {
        printf 'ERROR: %s does not ship the expected file set\n' "$(basename "$pkg")" >&2
        printf -- '--- expected ---\n%s\n--- got ---\n%s\n' "$expected_files" "$actual_files" >&2
        exit 1
    }
done

mkdir -p -- "$OUT_DIR"
remove_pkgbase_from_repo "$OUT_DIR" lib32-mesa-testing
cp -- "${packages[@]}" "$OUT_DIR/"
normalize_repo_package_filenames "$OUT_DIR"

cp -- "$BUILD_DIR/PKGBUILD" "$OUT_DIR/lib32-mesa-testing-PKGBUILD"
cp -- "$BUILD_DIR/.SRCINFO" "$OUT_DIR/lib32-mesa-testing.SRCINFO"

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
epoch="$(srcinfo_value epoch)"
[[ "$pkgbase" == lib32-mesa-testing && -n "$pkgver" && -n "$pkgrel" ]] || {
    printf 'ERROR: invalid lib32-mesa-testing .SRCINFO metadata\n' >&2
    sed -n '1,100p' "$BUILD_DIR/.SRCINFO" >&2
    exit 1
}

cat > "$OUT_DIR/lib32-mesa-testing-info.env" <<EOF_INFO
LIB32_MESA_TESTING_FINGERPRINT=${LIB32_MESA_TESTING_FINGERPRINT:-unknown}
CACHYOS_MESA_COMMIT=${CACHYOS_MESA_COMMIT}
CACHYOS_LIB32_MESA_TESTING_PKGBUILD_URL=${CACHYOS_MESA_PKGBUILD_URL}
LIB32_MESA_TESTING_PKGBASE=${pkgbase}
LIB32_MESA_TESTING_EPOCH=${epoch}
LIB32_MESA_TESTING_PKGVER=${pkgver}
LIB32_MESA_TESTING_PKGREL=${pkgrel}
LIB32_MESA_TESTING_APPLIED_PATCHES=${LIB32_MESA_TESTING_APPLIED_PATCHES}
LIB32_MESA_TESTING_MARCH=${LIB32_MESA_TESTING_MARCH}
LIB32_MESA_TESTING_MTUNE=${LIB32_MESA_TESTING_MTUNE}
EOF_INFO

printf '==> lib32-mesa-testing staged in %s\n' "$OUT_DIR"
printf '    lib32-vulkan-radeon-testing: %s-%s\n' "$pkgver" "$pkgrel"
printf '    Packages built: %d\n' "${#packages[@]}"
