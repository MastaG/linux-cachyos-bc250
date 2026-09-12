#!/usr/bin/env bash
#
# Package the Steam Linux Runtime Proton for the BC-250.
#
# Stage two of two. The tree this packages is compiled first by
# scripts/build-proton-runtime-dist.sh, which needs Valve's SDK image and so
# cannot run under makepkg. This script expects that tarball to exist already
# and says where to get it if it does not.
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_DIR="${ROOT_DIR}/packages/proton-cachyos-slr-bc250"
BUILD_DIR="${PROTON_CACHYOS_SLR_BC250_BUILD_DIR:-${ROOT_DIR}/build/proton-cachyos-slr-bc250}"
OUT_DIR="${ROOT_DIR}/out/repo"
DIST_DIR="${BC250_PROTON_DIST_DIR:-${ROOT_DIR}/out/dist}"

# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/repo-package-helpers.sh"
# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/fsr4-payload-sources.sh"

rm -rf -- "$BUILD_DIR"
mkdir -p -- "$BUILD_DIR"

printf '==> resolving the CachyOS SLR release\n'
slr_env="$("$ROOT_DIR/scripts/resolve-proton-cachyos-slr.sh")"
eval "$slr_env"
printf '    %s (pkgver %s)\n' "$SLR_TAG" "$SLR_VERSION"

DIST_ASSET="proton-cachyos-slr-bc250-${SLR_VERSION}-dist.tar.xz"
if [[ ! -f "$DIST_DIR/$DIST_ASSET" ]]; then
    printf 'ERROR: %s has not been built yet.\n' "$DIST_DIR/$DIST_ASSET" >&2
    printf '       This package wraps a tree compiled in Valve'"'"'s SDK image, which\n' >&2
    printf '       makepkg cannot do from inside itself. Build it first:\n\n' >&2
    printf '         scripts/build-proton-runtime-dist.sh \\\n' >&2
    printf '             --repo https://github.com/CachyOS/proton-cachyos.git \\\n' >&2
    printf '             --tag %s --name proton-cachyos-slr-bc250 \\\n' "$SLR_TAG" >&2
    printf '             --out %s\n' "$DIST_DIR/$DIST_ASSET" >&2
    exit 1
fi
cp -- "$DIST_DIR/$DIST_ASSET" "$BUILD_DIR/"
SHA_DIST="$(sha256sum < "$DIST_DIR/$DIST_ASSET" | awk '{print $1}')"
printf '    tree %s (%s)\n' "$DIST_ASSET" "$(du -h "$DIST_DIR/$DIST_ASSET" | cut -f1)"

# Same OptiScaler selection as the other two packages: pinned by default so a
# nightly does not rebuild a ~700 MB package daily.
select_args=(--preset "${ROOT_DIR}/packages/bc250-fsr4-common/optiscaler-preset.json")
if [[ "${BC250_FSR4_TRACK_OPTISCALER:-0}" != 1 ]]; then
    select_args+=(--force-fallback)
fi
printf '==> selecting the OptiScaler build\n'
optiscaler_env="$(python3 "${ROOT_DIR}/scripts/select-optiscaler.py" "${select_args[@]}")"
eval "$optiscaler_env"
printf '    %s (%s)\n' "$OPTISCALER_TAG" "$OPTISCALER_VERSION"

printf '==> resolving the fakenvapi release\n'
fakenvapi_env="$("$ROOT_DIR/scripts/resolve-fakenvapi.sh")"
eval "$fakenvapi_env"
printf '    %s (%s)\n' "$FAKENVAPI_TAG" "$FAKENVAPI_ASSET"

# The proton-cachyos-rooted patch: this tree is CachyOS's, not GE's.
stage_fsr4_payload_sources "$ROOT_DIR" "$BUILD_DIR" proton-cachyos
cp -- "$PKG_DIR/ntsync.conf" "$BUILD_DIR/"
FSR4_PAYLOAD_SHA256[SHA_NTSYNC]="$(sha256sum < "$PKG_DIR/ntsync.conf" | awk '{print $1}')"

: "${BC250_PKGREL:=1}"
: "${BC250_FSR4_PAYLOAD_BASE:=https://github.com/MastaG/linux-cachyos-bc250/releases/download/bc250-fsr4-payload}"

render() {
    local template="$1" output="$2" key
    local -A values=(
        [SLR_TAG]="$SLR_TAG"
        [SLR_VERSION]="$SLR_VERSION"
        [DIST_ASSET]="$DIST_ASSET"
        [SHA_DIST]="$SHA_DIST"
        [OPTISCALER_ASSET]="$OPTISCALER_ASSET"
        [OPTISCALER_URL]="$OPTISCALER_URL"
        [OPTISCALER_SHA256]="$OPTISCALER_SHA256"
        [FAKENVAPI_ASSET]="$FAKENVAPI_ASSET"
        [FAKENVAPI_URL]="$FAKENVAPI_URL"
        [FAKENVAPI_SHA256]="$FAKENVAPI_SHA256"
        [OPTISCALER_VERSION]="$OPTISCALER_VERSION"
        [PAYLOAD_BASE]="$BC250_FSR4_PAYLOAD_BASE"
        [PKGREL]="$BC250_PKGREL"
    )
    for key in "${!FSR4_PAYLOAD_SHA256[@]}"; do
        values[$key]="${FSR4_PAYLOAD_SHA256[$key]}"
    done

    cp -- "$template" "$output"
    for key in "${!values[@]}"; do
        python3 - "$output" "$key" "${values[$key]}" <<'EOF_SUBST'
import sys
path, key, value = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, encoding="utf-8") as handle:
    text = handle.read()
with open(path, "w", encoding="utf-8") as handle:
    handle.write(text.replace("@" + key + "@", value))
EOF_SUBST
    done

    if grep -nE '@[A-Z_]+@' "$output"; then
        printf 'ERROR: unsubstituted placeholders remain in %s\n' "$output" >&2
        exit 1
    fi
}

render "$PKG_DIR/PKGBUILD.in" "$BUILD_DIR/PKGBUILD"

cd -- "$BUILD_DIR"
makepkg --syncdeps --noconfirm --cleanbuild --clean --skippgpcheck
makepkg --printsrcinfo > .SRCINFO

shopt -s nullglob
packages=("$BUILD_DIR"/*.pkg.tar.zst)
(( ${#packages[@]} == 1 )) || {
    printf 'ERROR: expected exactly one proton-cachyos-slr-bc250 package; found %d\n' \
        "${#packages[@]}" >&2
    exit 1
}

mkdir -p -- "$OUT_DIR"
remove_pkgbase_from_repo "$OUT_DIR" proton-cachyos-slr-bc250
cp -- "${packages[@]}" "$OUT_DIR/"
normalize_repo_package_filenames "$OUT_DIR"

cp -- "$BUILD_DIR/PKGBUILD" "$OUT_DIR/proton-cachyos-slr-bc250-PKGBUILD"
cp -- "$BUILD_DIR/.SRCINFO" "$OUT_DIR/proton-cachyos-slr-bc250.SRCINFO"

cat > "$OUT_DIR/proton-cachyos-slr-bc250-info.env" <<EOF_INFO
PROTON_CACHYOS_SLR_BC250_FINGERPRINT=${PROTON_CACHYOS_SLR_BC250_FINGERPRINT:-}
PROTON_CACHYOS_SLR_BC250_PKGVER=${SLR_VERSION}
PROTON_CACHYOS_SLR_BC250_PKGREL=${BC250_PKGREL}
PROTON_CACHYOS_SLR_BC250_SRCTAG=${SLR_TAG}
PROTON_CACHYOS_SLR_BC250_OPTISCALER=${OPTISCALER_VERSION}
PROTON_CACHYOS_SLR_BC250_FAKENVAPI=${FAKENVAPI_TAG#v}
EOF_INFO

printf '==> proton-cachyos-slr-bc250 staged in %s\n' "$OUT_DIR"
printf '    Version: %s-%s (%s, OptiScaler %s)\n' \
    "$SLR_VERSION" "$BC250_PKGREL" "$SLR_TAG" "$OPTISCALER_VERSION"
