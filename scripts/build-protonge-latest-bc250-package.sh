#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_DIR="${ROOT_DIR}/packages/protonge-latest-bc250"
BUILD_DIR="${PROTONGE_LATEST_BC250_BUILD_DIR:-${ROOT_DIR}/build/protonge-latest-bc250}"
OUT_DIR="${ROOT_DIR}/out/repo"

# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/repo-package-helpers.sh"
# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/fsr4-payload-sources.sh"

rm -rf -- "$BUILD_DIR"
mkdir -p -- "$BUILD_DIR"

# Which GE-Proton release this packages. PROTONGE_TAG pins a specific one.
printf '==> resolving the GE-Proton release\n'
protonge_env="$("$ROOT_DIR/scripts/resolve-protonge.sh")"
eval "$protonge_env"
printf '    %s (pkgver %s)\n' "$PROTONGE_TAG" "$PROTONGE_VERSION"

# Which OptiScaler build to pin.
#
# The mirrored build is the default, and that is deliberate rather than lazy.
# OptiScaler-nightly publishes a new tag most days, so tracking it would change
# this package's fingerprint daily and rebuild a ~700 MB package for a payload
# nobody asked to move. The preset is coupled to the build (see
# packages/bc250-fsr4-common/README.md), so moving forward is a decision worth
# making deliberately: bump FALLBACK_TAG in select-optiscaler.py, which changes
# the fingerprint and triggers exactly one rebuild.
#
# Set BC250_FSR4_TRACK_OPTISCALER=1 to validate and take the newest nightly
# instead -- useful for checking whether the preset still applies to it.
select_args=(--preset "${ROOT_DIR}/packages/bc250-fsr4-common/optiscaler-preset.json")
if [[ "${BC250_FSR4_TRACK_OPTISCALER:-0}" != 1 ]]; then
    select_args+=(--force-fallback)
fi
printf '==> selecting the OptiScaler build\n'
optiscaler_env="$(python3 "${ROOT_DIR}/scripts/select-optiscaler.py" "${select_args[@]}")"
eval "$optiscaler_env"
printf '    %s (%s, %s)\n' "$OPTISCALER_TAG" "$OPTISCALER_VERSION" \
    "$([[ "$OPTISCALER_MIRRORED" == True ]] && printf mirrored || printf upstream)"

# Files we author, staged next to the rendered PKGBUILD so makepkg treats them
# as ordinary local sources and checksums them like any other.
stage_fsr4_payload_sources "$ROOT_DIR" "$BUILD_DIR" ge-proton
cp -- "$PKG_DIR/proton-shim.sh" "$PKG_DIR/ntsync.conf" "$BUILD_DIR/"
FSR4_PAYLOAD_SHA256[SHA_SHIM]="$(sha256sum < "$PKG_DIR/proton-shim.sh" | awk '{print $1}')"
FSR4_PAYLOAD_SHA256[SHA_NTSYNC]="$(sha256sum < "$PKG_DIR/ntsync.conf" | awk '{print $1}')"

: "${BC250_PKGREL:=1}"
: "${BC250_FSR4_PAYLOAD_BASE:=https://github.com/MastaG/linux-cachyos-bc250/releases/download/bc250-fsr4-payload}"

render() {
    local template="$1" output="$2" key
    local -A values=(
        [PROTONGE_TAG]="$PROTONGE_TAG"
        [PROTONGE_VERSION]="$PROTONGE_VERSION"
        [PROTONGE_ASSET]="$PROTONGE_ASSET"
        [PROTONGE_URL]="$PROTONGE_URL"
        [PROTONGE_SHA512]="$PROTONGE_SHA512"
        [OPTISCALER_ASSET]="$OPTISCALER_ASSET"
        [OPTISCALER_URL]="$OPTISCALER_URL"
        [OPTISCALER_SHA256]="$OPTISCALER_SHA256"
        [OPTISCALER_VERSION]="$OPTISCALER_VERSION"
        [PAYLOAD_BASE]="$BC250_FSR4_PAYLOAD_BASE"
        [PKGREL]="$BC250_PKGREL"
    )
    for key in "${!FSR4_PAYLOAD_SHA256[@]}"; do
        values[$key]="${FSR4_PAYLOAD_SHA256[$key]}"
    done

    cp -- "$template" "$output"
    for key in "${!values[@]}"; do
        # Values here are hashes, versions and URLs, so a plain substitution is
        # safe; the check below is what catches a placeholder nobody filled in.
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
    printf 'ERROR: expected exactly one protonge-latest-bc250 package; found %d\n' "${#packages[@]}" >&2
    exit 1
}

mkdir -p -- "$OUT_DIR"
remove_pkgbase_from_repo "$OUT_DIR" protonge-latest-bc250
cp -- "${packages[@]}" "$OUT_DIR/"
normalize_repo_package_filenames "$OUT_DIR"

cp -- "$BUILD_DIR/PKGBUILD" "$OUT_DIR/protonge-latest-bc250-PKGBUILD"
cp -- "$BUILD_DIR/.SRCINFO" "$OUT_DIR/protonge-latest-bc250.SRCINFO"

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

protonge_pkgbase="$(srcinfo_value pkgbase)"
protonge_pkgver="$(srcinfo_value pkgver)"
protonge_pkgrel="$(srcinfo_value pkgrel)"

[[ "$protonge_pkgbase" == protonge-latest-bc250 && -n "$protonge_pkgver" && -n "$protonge_pkgrel" ]] || {
    printf 'ERROR: invalid protonge-latest-bc250 .SRCINFO metadata\n' >&2
    sed -n '1,100p' "$BUILD_DIR/.SRCINFO" >&2
    exit 1
}

cat > "$OUT_DIR/protonge-latest-bc250-info.env" <<EOF_INFO
PROTONGE_LATEST_BC250_FINGERPRINT=${PROTONGE_LATEST_BC250_FINGERPRINT:-unknown}
PROTONGE_LATEST_BC250_PKGVER=${protonge_pkgver}
PROTONGE_LATEST_BC250_PKGREL=${protonge_pkgrel}
PROTONGE_LATEST_BC250_GE_TAG=${PROTONGE_TAG}
PROTONGE_LATEST_BC250_OPTISCALER=${OPTISCALER_VERSION}
EOF_INFO

printf '==> protonge-latest-bc250 staged in %s\n' "$OUT_DIR"
printf '    Version: %s-%s (%s, OptiScaler %s)\n' \
    "$protonge_pkgver" "$protonge_pkgrel" "$PROTONGE_TAG" "$OPTISCALER_VERSION"
