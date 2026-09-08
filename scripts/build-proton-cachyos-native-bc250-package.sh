#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${PROTON_CACHYOS_NATIVE_BUILD_DIR:-${ROOT_DIR}/build/proton-cachyos-native-bc250}"
OUT_DIR="${ROOT_DIR}/out/repo"

"${ROOT_DIR}/scripts/prepare-proton-cachyos-native-pkgbuild.sh"
# shellcheck disable=SC1091
source "$BUILD_DIR/bc250-proton-build.env"
# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/repo-package-helpers.sh"

cd -- "$BUILD_DIR"
export MAKEFLAGS="${MAKEFLAGS:--j$(nproc)}"

# This one compiles Proton and Wine from source and takes hours. It is gated by
# the same fingerprint mechanism as everything else, so it only runs when the
# upstream PKGBUILD, the FSR4 payload inputs or our own packaging change.
makepkg --syncdeps --noconfirm --cleanbuild --clean --skippgpcheck
makepkg --printsrcinfo > .SRCINFO

shopt -s nullglob
packages=("$BUILD_DIR"/*.pkg.tar.zst)
(( ${#packages[@]} == 1 )) || {
    printf 'ERROR: expected exactly one proton-cachyos-native-bc250 package; found %d\n' \
        "${#packages[@]}" >&2
    exit 1
}

mkdir -p -- "$OUT_DIR"
remove_pkgbase_from_repo "$OUT_DIR" proton-cachyos-native-bc250
cp -- "${packages[@]}" "$OUT_DIR/"
# The package carries epoch=1, so makepkg names the file with a ':' in it, which
# pacman cannot fetch over HTTP from a release asset. This is what rewrites it.
normalize_repo_package_filenames "$OUT_DIR"

cp -- "$BUILD_DIR/PKGBUILD" "$OUT_DIR/proton-cachyos-native-bc250-PKGBUILD"
cp -- "$BUILD_DIR/.SRCINFO" "$OUT_DIR/proton-cachyos-native-bc250.SRCINFO"

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

proton_pkgbase="$(srcinfo_value pkgbase)"
proton_pkgver="$(srcinfo_value pkgver)"
proton_pkgrel="$(srcinfo_value pkgrel)"
proton_epoch="$(srcinfo_value epoch)"

[[ "$proton_pkgbase" == proton-cachyos-native-bc250 && -n "$proton_pkgver" && -n "$proton_pkgrel" ]] || {
    printf 'ERROR: invalid proton-cachyos-native-bc250 .SRCINFO metadata\n' >&2
    sed -n '1,100p' "$BUILD_DIR/.SRCINFO" >&2
    exit 1
}

# The whole point of this package is that it installs next to the official one.
# Inheriting either of these would make pacman remove proton-cachyos instead.
for field in provides replaces conflicts; do
    if grep -qE "^[[:space:]]*${field} = " "$BUILD_DIR/.SRCINFO"; then
        printf 'ERROR: %s must be empty so this coexists with proton-cachyos\n' "$field" >&2
        grep -nE "^[[:space:]]*${field} = " "$BUILD_DIR/.SRCINFO" >&2
        exit 1
    fi
done

cat > "$OUT_DIR/proton-cachyos-native-bc250-info.env" <<EOF_INFO
PROTON_CACHYOS_NATIVE_BC250_FINGERPRINT=${PROTON_CACHYOS_NATIVE_BC250_FINGERPRINT:-unknown}
PROTON_CACHYOS_NATIVE_BC250_PKGVER=${proton_pkgver}
PROTON_CACHYOS_NATIVE_BC250_PKGREL=${proton_pkgrel}
PROTON_CACHYOS_NATIVE_BC250_EPOCH=${proton_epoch:-0}
PROTON_CACHYOS_NATIVE_BC250_CACHYOS_COMMIT=${CACHYOS_MESA_COMMIT}
PROTON_CACHYOS_NATIVE_BC250_OPTISCALER=${OPTISCALER_VERSION}
EOF_INFO

printf '==> proton-cachyos-native-bc250 staged in %s\n' "$OUT_DIR"
printf '    Version: %s-%s (OptiScaler %s, -march=%s -mtune=%s)\n' \
    "$proton_pkgver" "$proton_pkgrel" "$OPTISCALER_VERSION" "$PROTON_MARCH" "$PROTON_MTUNE"
