#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${MESA_GIT_BUILD_DIR:-${ROOT_DIR}/build/mesa-git}"
OUT_DIR="${ROOT_DIR}/out/repo"

"${ROOT_DIR}/scripts/prepare-mesa-git-pkgbuild.sh"
# shellcheck disable=SC1091
source "$BUILD_DIR/bc250-mesa-git-build.env"
# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/repo-package-helpers.sh"

cd -- "$BUILD_DIR"
export MAKEFLAGS="${MAKEFLAGS:--j$(nproc)}"

# Upstream CachyOS customization.cfg builds both mesa-git and lib32-mesa-git.
# user.cfg only pins the resolved Mesa commit; all other mesa-git settings stay
# aligned with the CachyOS packaging defaults.
makepkg --syncdeps --noconfirm --cleanbuild --skippgpcheck

shopt -s nullglob
packages=("$BUILD_DIR"/*.pkg.tar.zst)
(( ${#packages[@]} == 2 )) || {
    printf 'ERROR: mesa-git should produce mesa-git + lib32-mesa-git; found %d package(s)\n' "${#packages[@]}" >&2
    exit 1
}

mesa_package=""
lib32_package=""
mesa_pkgver_full=""
lib32_pkgver_full=""
for package in "${packages[@]}"; do
    pkginfo="$(bsdtar -xOf "$package" .PKGINFO)"
    pkgbase="$(awk -F ' = ' '$1 == "pkgbase" { print $2; exit }' <<<"$pkginfo")"
    pkgname="$(awk -F ' = ' '$1 == "pkgname" { print $2; exit }' <<<"$pkginfo")"
    pkgver_full="$(awk -F ' = ' '$1 == "pkgver" { print $2; exit }' <<<"$pkginfo")"
    [[ "$pkgbase" == mesa-git && -n "$pkgver_full" ]] || {
        printf 'ERROR: unexpected mesa-git package metadata in %s\n%s\n' "$package" "$pkginfo" >&2
        exit 1
    }
    case "$pkgname" in
        mesa-git)
            [[ -z "$mesa_package" ]] || { printf 'ERROR: duplicate mesa-git package\n' >&2; exit 1; }
            mesa_package="$package"
            mesa_pkgver_full="$pkgver_full"
            ;;
        lib32-mesa-git)
            [[ -z "$lib32_package" ]] || { printf 'ERROR: duplicate lib32-mesa-git package\n' >&2; exit 1; }
            lib32_package="$package"
            lib32_pkgver_full="$pkgver_full"
            ;;
        *)
            printf 'ERROR: unexpected package from mesa-git pkgbase: %s\n' "$pkgname" >&2
            exit 1
            ;;
    esac
done

[[ -n "$mesa_package" && -n "$lib32_package" ]] || {
    printf 'ERROR: mesa-git build did not produce both mesa-git and lib32-mesa-git\n' >&2
    exit 1
}
[[ "$mesa_pkgver_full" == "$lib32_pkgver_full" ]] || {
    printf 'ERROR: mesa-git/lib32-mesa-git versions differ: %s vs %s\n' "$mesa_pkgver_full" "$lib32_pkgver_full" >&2
    exit 1
}

pkgrel="${mesa_pkgver_full##*-}"
pkgver="${mesa_pkgver_full%-*}"

# Generate a source-info asset. VCS PKGBUILDs may report pkgver=0 here after
# their cleanup trap, so replace that field with the version from .PKGINFO.
makepkg --printsrcinfo > .SRCINFO || true
if [[ -s .SRCINFO ]]; then
    sed -i -E "0,/^[[:space:]]*pkgver = .*/s//\tpkgver = ${pkgver}/" .SRCINFO
    sed -i -E "0,/^[[:space:]]*pkgrel = .*/s//\tpkgrel = ${pkgrel}/" .SRCINFO
else
    printf 'pkgbase = mesa-git\n\tpkgver = %s\n\tpkgrel = %s\n\tpkgname = mesa-git\n\tpkgname = lib32-mesa-git\n' "$pkgver" "$pkgrel" > .SRCINFO
fi

mkdir -p -- "$OUT_DIR"
remove_pkgbase_from_repo "$OUT_DIR" mesa-git
cp -- "${packages[@]}" "$OUT_DIR/"
normalize_repo_package_filenames "$OUT_DIR"

cp -- "$BUILD_DIR/PKGBUILD" "$OUT_DIR/mesa-git-PKGBUILD"
cp -- "$BUILD_DIR/customization.cfg" "$OUT_DIR/mesa-git-customization.cfg"
cp -- "$BUILD_DIR/mesa-userpatches/user.cfg" "$OUT_DIR/mesa-git-user.cfg"
cp -- "$BUILD_DIR/.SRCINFO" "$OUT_DIR/mesa-git.SRCINFO"
cp -- "$ROOT_DIR/patches/mesa-git/0001-gfx1013-compute-queue-fix.patch" "$OUT_DIR/mesa-git-0001-gfx1013-compute-queue-fix.patch"
cp -- "$ROOT_DIR/patches/mesa-git/0002-gfx1013-mesh-task-shaders.patch" "$OUT_DIR/mesa-git-0002-gfx1013-mesh-task-shaders.patch"
cp -- "$ROOT_DIR/patches/mesa-git/0003-gfx1013-taskmesh-queries.patch" "$OUT_DIR/mesa-git-0003-gfx1013-taskmesh-queries.patch"

cat > "$OUT_DIR/mesa-git-info.env" <<EOF_INFO
MESA_GIT_FINGERPRINT=${MESA_GIT_FINGERPRINT:-unknown}
CACHYOS_MESA_COMMIT=${CACHYOS_MESA_COMMIT}
CACHYOS_MESA_GIT_PKGBUILD_URL=${CACHYOS_MESA_GIT_PKGBUILD_URL}
MESA_GIT_COMMIT=${MESA_GIT_COMMIT}
MESA_GIT_PKGBASE=mesa-git
MESA_GIT_PKGVER=${pkgver}
MESA_GIT_PKGREL=${pkgrel}
MESA_GIT_APPLIED_PATCH=${MESA_GIT_APPLIED_PATCH}
MESA_GIT_MARCH=${MESA_GIT_MARCH}
MESA_GIT_MTUNE=${MESA_GIT_MTUNE}
MESA_GIT_LIB32=${MESA_GIT_LIB32}
EOF_INFO

printf '==> mesa-git packages staged in %s\n' "$OUT_DIR"
printf '    mesa-git:       %s-%s\n' "$pkgver" "$pkgrel"
printf '    lib32-mesa-git: %s-%s\n' "$pkgver" "$pkgrel"
printf '    Mesa commit:    %s\n' "$MESA_GIT_COMMIT"
