#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
MESA_BUILD_DIR="${MESA_BUILD_DIR:-${ROOT_DIR}/build/mesa}"
OUT_DIR="${ROOT_DIR}/out/repo"

"${ROOT_DIR}/scripts/prepare-mesa-pkgbuild.sh"
# shellcheck disable=SC1091
source "$MESA_BUILD_DIR/bc250-mesa-build.env"
# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/repo-package-helpers.sh"

cd -- "$MESA_BUILD_DIR"
export MAKEFLAGS="${MAKEFLAGS:--j$(nproc)}"

# Only 0001 is active. 0002/0003 remain release assets for testing/review.
makepkg --syncdeps --noconfirm --cleanbuild --clean --skippgpcheck
makepkg --printsrcinfo > .SRCINFO

shopt -s nullglob
mesa_packages=("$MESA_BUILD_DIR"/*.pkg.tar.zst)
(( ${#mesa_packages[@]} > 0 )) || {
    printf 'ERROR: Mesa makepkg produced no .pkg.tar.zst files\n' >&2
    exit 1
}

mkdir -p -- "$OUT_DIR"
remove_pkgbase_from_repo "$OUT_DIR" mesa
cp -- "${mesa_packages[@]}" "$OUT_DIR/"
normalize_repo_package_filenames "$OUT_DIR"

cp -- "$MESA_BUILD_DIR/PKGBUILD" "$OUT_DIR/mesa-PKGBUILD"
cp -- "$MESA_BUILD_DIR/.SRCINFO" "$OUT_DIR/mesa.SRCINFO"
cp -- "$MESA_BUILD_DIR/0001-gfx1013-compute-queue-fix.patch" "$OUT_DIR/0001-gfx1013-compute-queue-fix.patch"
cp -- "$ROOT_DIR/patches/mesa/0002-gfx1013-mesh-task-shaders.patch" "$OUT_DIR/0002-gfx1013-mesh-task-shaders.patch"
cp -- "$ROOT_DIR/patches/mesa/0003-gfx1013-taskmesh-queries.patch" "$OUT_DIR/0003-gfx1013-taskmesh-queries.patch"

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
    ' "$MESA_BUILD_DIR/.SRCINFO"
}

mesa_pkgbase="$(srcinfo_value pkgbase)"
mesa_pkgver="$(srcinfo_value pkgver)"
mesa_pkgrel="$(srcinfo_value pkgrel)"
mesa_epoch="$(srcinfo_value epoch)"

[[ "$mesa_pkgbase" == mesa && -n "$mesa_pkgver" && -n "$mesa_pkgrel" ]] || {
    printf 'ERROR: invalid Mesa .SRCINFO metadata\n' >&2
    sed -n '1,100p' "$MESA_BUILD_DIR/.SRCINFO" >&2
    exit 1
}

cat > "$OUT_DIR/mesa-info.env" <<EOF_INFO
MESA_FINGERPRINT=${MESA_FINGERPRINT:-unknown}
CACHYOS_MESA_COMMIT=${CACHYOS_MESA_COMMIT}
CACHYOS_MESA_PKGBUILD_URL=${CACHYOS_MESA_PKGBUILD_URL}
MESA_PKGBASE=${mesa_pkgbase}
MESA_EPOCH=${mesa_epoch}
MESA_PKGVER=${mesa_pkgver}
MESA_PKGREL=${mesa_pkgrel}
MESA_APPLIED_PATCH=${MESA_APPLIED_PATCH}
MESA_MARCH=${MESA_MARCH}
MESA_MTUNE=${MESA_MTUNE}
EOF_INFO

printf '==> Stable Mesa staged in %s\n' "$OUT_DIR"
printf '    Mesa: %s-%s\n' "$mesa_pkgver" "$mesa_pkgrel"
printf '    Packages built: %d\n' "${#mesa_packages[@]}"
