#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
MESA_BUILD_DIR="${MESA_BUILD_DIR:-${ROOT_DIR}/build/mesa}"
OUT_DIR="${ROOT_DIR}/out/repo"
REPO_NAME="bc250-cachyos"

"${ROOT_DIR}/scripts/prepare-mesa-pkgbuild.sh"
# shellcheck disable=SC1091
source "$MESA_BUILD_DIR/bc250-mesa-build.env"

cd -- "$MESA_BUILD_DIR"
export MAKEFLAGS="${MAKEFLAGS:--j$(nproc)}"

# Use CachyOS' Mesa PKGBUILD as-is apart from pkgrel and the single BC-250
# compute-queue patch. The optional mesh/task patches are intentionally not
# present in source= and therefore are not applied or built.
makepkg --syncdeps --noconfirm --cleanbuild --clean --skippgpcheck
makepkg --printsrcinfo > .SRCINFO

shopt -s nullglob
mesa_packages=("$MESA_BUILD_DIR"/*.pkg.tar.zst)
(( ${#mesa_packages[@]} > 0 )) || {
    printf 'ERROR: Mesa makepkg produced no .pkg.tar.zst files\n' >&2
    exit 1
}

mkdir -p -- "$OUT_DIR"
cp -- "${mesa_packages[@]}" "$OUT_DIR/"
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

for field in mesa_pkgbase mesa_pkgver mesa_pkgrel; do
    if [[ -z "${!field}" ]]; then
        printf 'ERROR: could not read %s from Mesa .SRCINFO\n' "$field" >&2
        sed -n '1,100p' "$MESA_BUILD_DIR/.SRCINFO" >&2
        exit 1
    fi
done

if [[ "$mesa_pkgbase" != "mesa" ]]; then
    printf 'ERROR: unexpected Mesa pkgbase: %s\n' "$mesa_pkgbase" >&2
    exit 1
fi

# Recreate the repository database from every package produced in this run so
# the fixed release contains one coherent kernel + Mesa pacman repository.
cd -- "$OUT_DIR"
rm -f -- "${REPO_NAME}.db" "${REPO_NAME}.db.tar.zst" \
          "${REPO_NAME}.files" "${REPO_NAME}.files.tar.zst"
repo-add "${REPO_NAME}.db.tar.zst" ./*.pkg.tar.zst
cp -L --remove-destination "${REPO_NAME}.db.tar.zst" "${REPO_NAME}.db"
cp -L --remove-destination "${REPO_NAME}.files.tar.zst" "${REPO_NAME}.files"

cat >> "$OUT_DIR/build-info.env" <<EOF_INFO
CACHYOS_MESA_COMMIT=${CACHYOS_MESA_COMMIT}
CACHYOS_MESA_PKGBUILD_URL=${CACHYOS_MESA_PKGBUILD_URL}
MESA_PKGBASE=${mesa_pkgbase}
MESA_EPOCH=${mesa_epoch}
MESA_PKGVER=${mesa_pkgver}
MESA_PKGREL=${mesa_pkgrel}
MESA_APPLIED_PATCH=${MESA_APPLIED_PATCH}
EOF_INFO

cat >> "$OUT_DIR/RELEASE_NOTES.md" <<EOF_NOTES

## Patched CachyOS Mesa

- CachyOS PKGBUILD commit: \`${CACHYOS_MESA_COMMIT}\`
- Published Mesa version: \`${mesa_pkgver}-${mesa_pkgrel}\`${mesa_epoch:+ (epoch ${mesa_epoch})}
- Applied Mesa patch: \`0001-gfx1013-compute-queue-fix.patch\`
- The rebased \`0002-gfx1013-mesh-task-shaders.patch\` and
  \`0003-gfx1013-taskmesh-queries.patch\` are included as release assets but are
  **not applied** to the packages yet.
- The GFX1013 compute-queue Mesa patch is intended to be used together with
  this repository's GFX1013 kernel compute/PASID fixes.
EOF_NOTES

# Mesa was added after the kernel build generated its first checksum file.
# Recalculate over the complete fixed-release payload.
rm -f -- SHA256SUMS
while IFS= read -r -d '' file; do
    sha256sum "${file#./}"
done < <(find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 | sort -z) > SHA256SUMS

printf '==> Mesa packages added to %s\n' "$OUT_DIR"
printf '    Mesa: %s-%s\n' "$mesa_pkgver" "$mesa_pkgrel"
printf '    Packages built: %d\n' "${#mesa_packages[@]}"
