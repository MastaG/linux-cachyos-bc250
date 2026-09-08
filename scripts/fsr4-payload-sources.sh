#!/usr/bin/env bash
# Shared staging for the files both FSR4 Proton packages build from.
#
# proton-cachyos-native-bc250 and protonge-latest-bc250 ship the same payload,
# the same wrapper and the same preset over different Protons. Keeping the list
# in one place is what stops the two packages from drifting into shipping
# subtly different OptiScaler configurations.
#
# The one thing that is NOT shared is the upscalers.py patch. GE-Proton ships
# umu-protonfixes as released, while proton-cachyos applies eight patches of its
# own to the same file first, so the two need separately rebased patches with
# different roots -- see packages/bc250-fsr4-common/README.md. Pick with <base>.
#
# Source this, then call:
#   stage_fsr4_payload_sources <root-dir> <destination-dir> <ge-proton|proton-cachyos>
# It copies the files in and leaves their SHA256s in FSR4_PAYLOAD_SHA256, keyed
# by the placeholder name the PKGBUILD templates use.

declare -gA FSR4_PAYLOAD_SHA256=()

stage_fsr4_payload_sources() {
    local root="$1"
    local dest="$2"
    local base="$3"
    local common="$root/packages/bc250-fsr4-common"
    local name source

    case "$base" in
        ge-proton|proton-cachyos) ;;
        *)
            printf 'ERROR: unknown Proton base for the FSR4 patch: %s\n' "$base" >&2
            return 1
            ;;
    esac

    # placeholder -> path, in the order the PKGBUILD source= array lists them.
    local -A sources=(
        [SHA_PATCH]="$common/patches/$base/0001-pinned-upscaler-manifest.patch"
        [SHA_LAUNCH]="$common/bc250-fsr4-launch.py"
        [SHA_PAYLOAD_BUILDER]="$root/scripts/build-fsr4-payload.py"
        [SHA_PRESET]="$common/optiscaler-preset.json"
    )

    for name in "${!sources[@]}"; do
        source="${sources[$name]}"
        [[ -f "$source" ]] || {
            printf 'ERROR: missing FSR4 payload source: %s\n' "$source" >&2
            return 1
        }
        cp -- "$source" "$dest/$(basename -- "$source")"
        FSR4_PAYLOAD_SHA256[$name]="$(sha256sum < "$source" | awk '{print $1}')"
    done

    # The notices that ship beside the binaries they cover. Their SHA256s are
    # pinned literally in the PKGBUILD templates, because they are upstream
    # files fetched from immutable URLs rather than anything we author.
    cp -- "$common/licenses/FidelityFX-SDK-4.0.2.txt" \
          "$common/licenses/NVIDIA-DLSS.txt" "$dest/"
}

# The files that decide what these packages contain, for the rebuild
# fingerprints. Printed one path per line.
fsr4_payload_source_paths() {
    local root="$1"
    local base="$2"
    printf '%s\n' \
        "$root/packages/bc250-fsr4-common/patches/$base/0001-pinned-upscaler-manifest.patch" \
        "$root/packages/bc250-fsr4-common/bc250-fsr4-launch.py" \
        "$root/packages/bc250-fsr4-common/optiscaler-preset.json" \
        "$root/packages/bc250-fsr4-common/licenses/FidelityFX-SDK-4.0.2.txt" \
        "$root/packages/bc250-fsr4-common/licenses/NVIDIA-DLSS.txt" \
        "$root/scripts/build-fsr4-payload.py" \
        "$root/scripts/select-optiscaler.py" \
        "$root/scripts/fsr4-payload-sources.sh"
}
