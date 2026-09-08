#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_DIR="${ROOT_DIR}/packages/linux-cachyos-bc250-meta"
BUILD_DIR="${LINUX_CACHYOS_BC250_META_BUILD_DIR:-${ROOT_DIR}/build/linux-cachyos-bc250-meta}"
OUT_DIR="${ROOT_DIR}/out/repo"

# No upstream source and nothing to prepare/rewrite: this PKGBUILD is entirely
# our own, has no source= array, and package() installs no files. Work on a
# copy anyway so a failed build never leaves state in the tracked source dir.
rm -rf -- "$BUILD_DIR"
mkdir -p -- "$BUILD_DIR"
cp -- "$PKG_DIR/PKGBUILD" "$BUILD_DIR/"

# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/repo-package-helpers.sh"

# Every dependency of this metapackage is a package this repository itself
# provides, so it must not be published unless all of them are actually in the
# repository -- otherwise `pacman -S linux-cachyos-bc250-meta` fails for
# everyone with an unresolvable dependency.
#
# This used to be guaranteed by finalize-repository.sh refusing to publish an
# incomplete repository at all. Components are now published as they build, so
# the guarantee has to be made here: fail rather than produce a metapackage
# whose dependencies are missing, and it will be retried on the next run once
# they exist.
meta_depends="$(
    bash -c 'source "$1" >/dev/null 2>&1; printf "%s\n" "${depends[@]}"' _ "$BUILD_DIR/PKGBUILD"
)"
missing=()
while IFS= read -r dependency; do
    [[ -n "$dependency" ]] || continue
    found=false
    shopt -s nullglob
    for package in "$OUT_DIR"/*.pkg.tar.zst; do
        name="$(bsdtar -xOf "$package" .PKGINFO 2>/dev/null |
            awk -F ' = ' '$1 == "pkgname" { print $2; exit }')"
        if [[ "$name" == "$dependency" ]]; then found=true; break; fi
    done
    [[ "$found" == true ]] || missing+=("$dependency")
done <<< "$meta_depends"

if (( ${#missing[@]} )); then
    printf 'ERROR: refusing to build the metapackage; these dependencies are not in the repository yet:\n' >&2
    printf '       %s\n' "${missing[@]}" >&2
    printf '       They must be published before a metapackage that requires them.\n' >&2
    exit 1
fi

cd -- "$BUILD_DIR"
# --nodeps, not --syncdeps: every entry in depends= here is one of our own
# bc250-cachyos packages, resolvable on an end-user machine that has added
# this repository, but not from a stock Arch mirror on a fresh build
# container. package() installs no files and needs none of them present to
# run, so skipping the check is correct rather than a workaround.
makepkg --nodeps --noconfirm --cleanbuild --clean --skippgpcheck
makepkg --printsrcinfo > .SRCINFO

shopt -s nullglob
packages=("$BUILD_DIR"/*.pkg.tar.zst)
(( ${#packages[@]} == 1 )) || {
    printf 'ERROR: expected exactly one linux-cachyos-bc250-meta package; found %d\n' "${#packages[@]}" >&2
    exit 1
}

mkdir -p -- "$OUT_DIR"
remove_pkgbase_from_repo "$OUT_DIR" linux-cachyos-bc250-meta
cp -- "${packages[@]}" "$OUT_DIR/"
normalize_repo_package_filenames "$OUT_DIR"

cp -- "$BUILD_DIR/PKGBUILD" "$OUT_DIR/linux-cachyos-bc250-meta-PKGBUILD"
cp -- "$BUILD_DIR/.SRCINFO" "$OUT_DIR/linux-cachyos-bc250-meta.SRCINFO"

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

meta_pkgbase="$(srcinfo_value pkgbase)"
meta_pkgver="$(srcinfo_value pkgver)"
meta_pkgrel="$(srcinfo_value pkgrel)"

[[ "$meta_pkgbase" == linux-cachyos-bc250-meta && -n "$meta_pkgver" && -n "$meta_pkgrel" ]] || {
    printf 'ERROR: invalid linux-cachyos-bc250-meta .SRCINFO metadata\n' >&2
    sed -n '1,100p' "$BUILD_DIR/.SRCINFO" >&2
    exit 1
}

cat > "$OUT_DIR/linux-cachyos-bc250-meta-info.env" <<EOF_INFO
LINUX_CACHYOS_BC250_META_FINGERPRINT=${LINUX_CACHYOS_BC250_META_FINGERPRINT:-unknown}
LINUX_CACHYOS_BC250_META_PKGVER=${meta_pkgver}
LINUX_CACHYOS_BC250_META_PKGREL=${meta_pkgrel}
EOF_INFO

printf '==> linux-cachyos-bc250-meta staged in %s\n' "$OUT_DIR"
printf '    Version: %s-%s\n' "$meta_pkgver" "$meta_pkgrel"
