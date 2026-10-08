#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${ROOT_DIR}/out/repo"
REPO_NAME="bc250-cachyos"

# shellcheck source=scripts/repo-package-helpers.sh
source "${ROOT_DIR}/scripts/repo-package-helpers.sh"
# shellcheck source=scripts/retired-packages.sh
source "${ROOT_DIR}/scripts/retired-packages.sh"

: "${KERNEL_STABLE_FINGERPRINT:?KERNEL_STABLE_FINGERPRINT is required}"
: "${KERNEL_RC_FINGERPRINT:?KERNEL_RC_FINGERPRINT is required}"
: "${KERNEL_BORE_FINGERPRINT:?KERNEL_BORE_FINGERPRINT is required}"
: "${MESA_FINGERPRINT:?MESA_FINGERPRINT is required}"
: "${LIB32_MESA_FINGERPRINT:?LIB32_MESA_FINGERPRINT is required}"
: "${MESA_GIT_FINGERPRINT:?MESA_GIT_FINGERPRINT is required}"
: "${BC250_DUAL_AUDIO_FINGERPRINT:?BC250_DUAL_AUDIO_FINGERPRINT is required}"
: "${BC250_CEC_FINGERPRINT:?BC250_CEC_FINGERPRINT is required}"
: "${BC250_PACCACHE_CLEANUP_FINGERPRINT:?BC250_PACCACHE_CLEANUP_FINGERPRINT is required}"
: "${BC250_CH7218_FW_FINGERPRINT:?BC250_CH7218_FW_FINGERPRINT is required}"
: "${LINUX_CACHYOS_BC250_META_FINGERPRINT:?LINUX_CACHYOS_BC250_META_FINGERPRINT is required}"
: "${PROTONGE_LATEST_BC250_FINGERPRINT:?PROTONGE_LATEST_BC250_FINGERPRINT is required}"
: "${PROTON_CACHYOS_NATIVE_BC250_FINGERPRINT:?PROTON_CACHYOS_NATIVE_BC250_FINGERPRINT is required}"

BUILD_KERNEL_STABLE="${BUILD_KERNEL_STABLE:-false}"
BUILD_KERNEL_RC="${BUILD_KERNEL_RC:-false}"
BUILD_KERNEL_BORE="${BUILD_KERNEL_BORE:-false}"
BUILD_MESA="${BUILD_MESA:-false}"
BUILD_LIB32_MESA="${BUILD_LIB32_MESA:-false}"
BUILD_MESA_GIT="${BUILD_MESA_GIT:-false}"
BUILD_BC250_DUAL_AUDIO="${BUILD_BC250_DUAL_AUDIO:-false}"
BUILD_BC250_CEC="${BUILD_BC250_CEC:-false}"
BUILD_BC250_PACCACHE_CLEANUP="${BUILD_BC250_PACCACHE_CLEANUP:-false}"
BUILD_BC250_CH7218_FW="${BUILD_BC250_CH7218_FW:-false}"
BUILD_LINUX_CACHYOS_BC250_META="${BUILD_LINUX_CACHYOS_BC250_META:-false}"
BUILD_PROTONGE_LATEST_BC250="${BUILD_PROTONGE_LATEST_BC250:-false}"
BUILD_PROTON_CACHYOS_NATIVE_BC250="${BUILD_PROTON_CACHYOS_NATIVE_BC250:-false}"

required_metadata=(
    kernel-stable-info.env
    kernel-rc-info.env
    kernel-bore-info.env
    mesa-info.env
    lib32-mesa-info.env
    mesa-git-info.env
    bc250-dual-audio-info.env
    bc250-cec-info.env
    bc250-paccache-cleanup-info.env
    bc250-ch7218-fw-info.env
    linux-cachyos-bc250-meta-info.env
    protonge-latest-bc250-info.env
    proton-cachyos-native-bc250-info.env
)

# Not in the list above on purpose. A component that has never published has no
# previous info file to seed, so requiring one would turn its first failed build
# into a failure to publish anything at all -- exactly what the per-component
# design exists to avoid. Its release-notes section is written only when it is
# actually there; a run in this state publishes everything else.
optional_metadata=(
    proton-cachyos-slr-bc250-info.env
)
for file in "${required_metadata[@]}"; do
    [[ -f "$OUT_DIR/$file" ]] || {
        printf 'ERROR: missing component metadata: %s\n' "$OUT_DIR/$file" >&2
        exit 1
    }
done

value() {
    local file="$1" key="$2"
    sed -n "s/^${key}=//p" "$file" | head -n1
}

stable_info="$OUT_DIR/kernel-stable-info.env"
rc_info="$OUT_DIR/kernel-rc-info.env"
bore_info="$OUT_DIR/kernel-bore-info.env"
mesa_info="$OUT_DIR/mesa-info.env"
lib32_info="$OUT_DIR/lib32-mesa-info.env"
mesa_git_info="$OUT_DIR/mesa-git-info.env"

stable_pkgbase="$(value "$stable_info" KERNEL_PKGBASE)"
stable_pkgver="$(value "$stable_info" KERNEL_PKGVER)"
stable_pkgrel="$(value "$stable_info" KERNEL_PKGREL)"
stable_source="$(value "$stable_info" CACHYOS_SOURCE_VARIANT)"
stable_patch_set="$(value "$stable_info" PATCH_SET)"

rc_pkgbase="$(value "$rc_info" KERNEL_PKGBASE)"
rc_pkgver="$(value "$rc_info" KERNEL_PKGVER)"
rc_pkgrel="$(value "$rc_info" KERNEL_PKGREL)"
rc_source="$(value "$rc_info" CACHYOS_SOURCE_VARIANT)"
rc_patch_set="$(value "$rc_info" PATCH_SET)"

bore_pkgbase="$(value "$bore_info" KERNEL_PKGBASE)"
bore_pkgver="$(value "$bore_info" KERNEL_PKGVER)"
bore_pkgrel="$(value "$bore_info" KERNEL_PKGREL)"
bore_source="$(value "$bore_info" CACHYOS_SOURCE_VARIANT)"
bore_patch_set="$(value "$bore_info" PATCH_SET)"

processor_opt="$(value "$stable_info" PROCESSOR_OPT)"
cpu_tune="$(value "$stable_info" CPU_TUNE)"
nct_commit="$(value "$stable_info" NCT6687D_COMMIT)"
bc250_vrm_commit="$(value "$stable_info" BC250_VRM_COMMIT)"
bc250_memory_commit="$(value "$stable_info" BC250_MEMORY_COMMIT)"
bc250_vrm_tag="$(value "$stable_info" BC250_VRM_TAG)"
bc250_memory_tag="$(value "$stable_info" BC250_MEMORY_TAG)"

mesa_pkgver="$(value "$mesa_info" MESA_PKGVER)"
mesa_pkgrel="$(value "$mesa_info" MESA_PKGREL)"
mesa_epoch="$(value "$mesa_info" MESA_EPOCH)"
mesa_cachyos_commit="$(value "$mesa_info" CACHYOS_MESA_COMMIT)"

lib32_pkgver="$(value "$lib32_info" LIB32_MESA_PKGVER)"
lib32_pkgrel="$(value "$lib32_info" LIB32_MESA_PKGREL)"
lib32_epoch="$(value "$lib32_info" LIB32_MESA_EPOCH)"
lib32_cachyos_commit="$(value "$lib32_info" CACHYOS_MESA_COMMIT)"

mesa_git_commit="$(value "$mesa_git_info" MESA_GIT_COMMIT)"
mesa_git_cachyos_commit="$(value "$mesa_git_info" CACHYOS_MESA_COMMIT)"
mesa_git_pkgver="$(value "$mesa_git_info" MESA_GIT_PKGVER)"
mesa_git_pkgrel="$(value "$mesa_git_info" MESA_GIT_PKGREL)"
mesa_git_lib32="$(value "$mesa_git_info" MESA_GIT_LIB32)"


bc250_dual_audio_info="$OUT_DIR/bc250-dual-audio-info.env"
bc250_dual_audio_pkgver="$(value "$bc250_dual_audio_info" BC250_DUAL_AUDIO_PKGVER)"
bc250_dual_audio_pkgrel="$(value "$bc250_dual_audio_info" BC250_DUAL_AUDIO_PKGREL)"

bc250_cec_info="$OUT_DIR/bc250-cec-info.env"
bc250_paccache_cleanup_info="$OUT_DIR/bc250-paccache-cleanup-info.env"
bc250_ch7218_fw_info="$OUT_DIR/bc250-ch7218-fw-info.env"
bc250_cec_pkgver="$(value "$bc250_cec_info" BC250_CEC_PKGVER)"
bc250_paccache_cleanup_pkgver="$(value "$bc250_paccache_cleanup_info" BC250_PACCACHE_CLEANUP_PKGVER)"
bc250_ch7218_fw_pkgver="$(value "$bc250_ch7218_fw_info" BC250_CH7218_FW_PKGVER)"
bc250_cec_pkgrel="$(value "$bc250_cec_info" BC250_CEC_PKGREL)"
bc250_paccache_cleanup_pkgrel="$(value "$bc250_paccache_cleanup_info" BC250_PACCACHE_CLEANUP_PKGREL)"
bc250_ch7218_fw_pkgrel="$(value "$bc250_ch7218_fw_info" BC250_CH7218_FW_PKGREL)"

linux_cachyos_bc250_meta_info="$OUT_DIR/linux-cachyos-bc250-meta-info.env"
linux_cachyos_bc250_meta_pkgver="$(value "$linux_cachyos_bc250_meta_info" LINUX_CACHYOS_BC250_META_PKGVER)"
linux_cachyos_bc250_meta_pkgrel="$(value "$linux_cachyos_bc250_meta_info" LINUX_CACHYOS_BC250_META_PKGREL)"

protonge_info="$OUT_DIR/protonge-latest-bc250-info.env"
protonge_pkgver="$(value "$protonge_info" PROTONGE_LATEST_BC250_PKGVER)"
protonge_pkgrel="$(value "$protonge_info" PROTONGE_LATEST_BC250_PKGREL)"
protonge_ge_tag="$(value "$protonge_info" PROTONGE_LATEST_BC250_GE_TAG)"
protonge_optiscaler="$(value "$protonge_info" PROTONGE_LATEST_BC250_OPTISCALER)"
protonge_fakenvapi="$(value "$protonge_info" PROTONGE_LATEST_BC250_FAKENVAPI)"

proton_native_info="$OUT_DIR/proton-cachyos-native-bc250-info.env"
proton_native_pkgver="$(value "$proton_native_info" PROTON_CACHYOS_NATIVE_BC250_PKGVER)"
proton_native_pkgrel="$(value "$proton_native_info" PROTON_CACHYOS_NATIVE_BC250_PKGREL)"
proton_native_optiscaler="$(value "$proton_native_info" PROTON_CACHYOS_NATIVE_BC250_OPTISCALER)"
proton_native_fakenvapi="$(value "$proton_native_info" PROTON_CACHYOS_NATIVE_BC250_FAKENVAPI)"

proton_slr_info="$OUT_DIR/proton-cachyos-slr-bc250-info.env"
proton_slr_present=false
if [[ -f "$proton_slr_info" ]]; then
    proton_slr_present=true
    proton_slr_pkgver="$(value "$proton_slr_info" PROTON_CACHYOS_SLR_BC250_PKGVER)"
    proton_slr_pkgrel="$(value "$proton_slr_info" PROTON_CACHYOS_SLR_BC250_PKGREL)"
    proton_slr_srctag="$(value "$proton_slr_info" PROTON_CACHYOS_SLR_BC250_SRCTAG)"
    proton_slr_optiscaler="$(value "$proton_slr_info" PROTON_CACHYOS_SLR_BC250_OPTISCALER)"
    proton_slr_fakenvapi="$(value "$proton_slr_info" PROTON_CACHYOS_SLR_BC250_FAKENVAPI)"
else
    printf '::warning title=proton-cachyos-slr-bc250 missing::not in this repository yet; its release-notes section is omitted\n'
fi

for field in \
    stable_pkgbase stable_pkgver stable_pkgrel \
    rc_pkgbase rc_pkgver rc_pkgrel \
    bore_pkgbase bore_pkgver bore_pkgrel \
    mesa_pkgver mesa_pkgrel lib32_pkgver lib32_pkgrel \
    mesa_git_commit mesa_git_pkgver mesa_git_pkgrel mesa_git_lib32 \
    bc250_dual_audio_pkgver bc250_dual_audio_pkgrel \
    bc250_cec_pkgver bc250_cec_pkgrel \
    bc250_paccache_cleanup_pkgver bc250_paccache_cleanup_pkgrel \
    bc250_ch7218_fw_pkgver bc250_ch7218_fw_pkgrel \
    linux_cachyos_bc250_meta_pkgver linux_cachyos_bc250_meta_pkgrel \
    protonge_pkgver protonge_pkgrel protonge_ge_tag protonge_optiscaler \
    proton_native_pkgver proton_native_pkgrel proton_native_optiscaler; do
    [[ -n "${!field}" ]] || {
        printf 'ERROR: missing metadata field %s\n' "$field" >&2
        exit 1
    }
done

[[ "$stable_pkgbase" == linux-cachyos-bc250 ]] || { printf 'ERROR: unexpected stable pkgbase: %s\n' "$stable_pkgbase" >&2; exit 1; }
[[ "$rc_pkgbase" == linux-cachyos-rc-bc250 ]] || { printf 'ERROR: unexpected RC pkgbase: %s\n' "$rc_pkgbase" >&2; exit 1; }
[[ "$bore_pkgbase" == linux-cachyos-bore-bc250 ]] || { printf 'ERROR: unexpected BORE pkgbase: %s\n' "$bore_pkgbase" >&2; exit 1; }
[[ "$stable_patch_set" == linux-cachyos && "$bore_patch_set" == linux-cachyos ]] || {
    printf 'ERROR: stable and BORE kernels must use the linux-cachyos patch set\n' >&2
    exit 1
}
[[ "$rc_patch_set" == linux-cachyos-rc ]] || {
    printf 'ERROR: RC kernel must use the linux-cachyos-rc patch set\n' >&2
    exit 1
}

cd -- "$OUT_DIR"
shopt -s nullglob
# Never count, describe or publish a package this repository has retired.
retire_packages "$OUT_DIR"
packages=(./*.pkg.tar.zst)
(( ${#packages[@]} > 0 )) || {
    printf 'ERROR: no packages staged in %s\n' "$OUT_DIR" >&2
    exit 1
}

pkgbase_count() {
    local wanted="$1" package found=0 pkgbase
    for package in "${packages[@]}"; do
        pkgbase="$(bsdtar -xOf "$package" .PKGINFO 2>/dev/null | awk -F ' = ' '$1 == "pkgbase" { print $2; exit }')"
        [[ "$pkgbase" == "$wanted" ]] && ((found += 1))
    done
    printf '%d\n' "$found"
}

stable_count="$(pkgbase_count "$stable_pkgbase")"
rc_count="$(pkgbase_count "$rc_pkgbase")"
bore_count="$(pkgbase_count "$bore_pkgbase")"
mesa_count="$(pkgbase_count mesa)"
lib32_count="$(pkgbase_count lib32-mesa)"
mesa_git_count="$(pkgbase_count mesa-git)"
bc250_dual_audio_count="$(pkgbase_count bc250-dual-audio)"
bc250_cec_count="$(pkgbase_count bc250-cec)"
bc250_paccache_cleanup_count="$(pkgbase_count bc250-paccache-cleanup)"
bc250_ch7218_fw_count="$(pkgbase_count bc250-ch7218-fw)"
linux_cachyos_bc250_meta_count="$(pkgbase_count linux-cachyos-bc250-meta)"
protonge_count="$(pkgbase_count protonge-latest-bc250)"
proton_native_count="$(pkgbase_count proton-cachyos-native-bc250)"
proton_slr_count="$(pkgbase_count proton-cachyos-slr-bc250)"
[[ "$proton_slr_present" == true ]] || proton_slr_count=1

(( stable_count >= 2 )) || { printf 'ERROR: expected stable kernel + headers; found %d package(s)\n' "$stable_count" >&2; exit 1; }
(( rc_count >= 2 )) || { printf 'ERROR: expected RC kernel + headers; found %d package(s)\n' "$rc_count" >&2; exit 1; }
(( bore_count >= 2 )) || { printf 'ERROR: expected BORE kernel + headers; found %d package(s)\n' "$bore_count" >&2; exit 1; }
(( mesa_count >= 1 )) || { printf 'ERROR: stable Mesa packages are missing\n' >&2; exit 1; }
(( lib32_count >= 1 )) || { printf 'ERROR: lib32-mesa packages are missing\n' >&2; exit 1; }
(( mesa_git_count == 2 )) || { printf 'ERROR: expected mesa-git + lib32-mesa-git; found %d package(s)\n' "$mesa_git_count" >&2; exit 1; }
(( bc250_dual_audio_count == 1 )) || { printf 'ERROR: expected exactly one bc250-dual-audio package; found %d\n' "$bc250_dual_audio_count" >&2; exit 1; }
(( bc250_cec_count == 1 )) || { printf 'ERROR: expected exactly one bc250-cec package; found %d\n' "$bc250_cec_count" >&2; exit 1; }
(( bc250_paccache_cleanup_count == 1 )) || { printf 'ERROR: expected exactly one bc250-paccache-cleanup package; found %d\n' "$bc250_paccache_cleanup_count" >&2; exit 1; }
(( bc250_ch7218_fw_count == 1 )) || { printf 'ERROR: expected exactly one bc250-ch7218-fw package; found %d\n' "$bc250_ch7218_fw_count" >&2; exit 1; }
(( linux_cachyos_bc250_meta_count == 1 )) || { printf 'ERROR: expected exactly one linux-cachyos-bc250-meta package; found %d\n' "$linux_cachyos_bc250_meta_count" >&2; exit 1; }
(( protonge_count == 1 )) || { printf 'ERROR: expected exactly one protonge-latest-bc250 package; found %d\n' "$protonge_count" >&2; exit 1; }
(( proton_native_count == 1 )) || { printf 'ERROR: expected exactly one proton-cachyos-native-bc250 package; found %d\n' "$proton_native_count" >&2; exit 1; }
(( proton_slr_count == 1 )) || { printf 'ERROR: expected exactly one proton-cachyos-slr-bc250 package; found %d\n' "$proton_slr_count" >&2; exit 1; }

# The database is rebuilt after every component so the runner can publish each
# one as it lands; do it once more here so the final release is built from the
# complete set rather than from whatever the last component happened to stage.
"${ROOT_DIR}/scripts/update-repo-db.sh"

# Record each component's fingerprint as reported by its own -info.env rather
# than from the environment.
#
# OUT_DIR is seeded with the previously published release, so every component
# starts out holding its last successfully built metadata. A component that
# builds this run overwrites that file with the fingerprint it was given; a
# component that is skipped, or whose build FAILED, leaves the seeded file in
# place. Reading the fingerprint back from the file therefore records the old
# value for a failed component, so the next run still sees a mismatch and
# retries it. Taking it from the environment instead would stamp the new
# fingerprint on a component that was never successfully built and the failure
# would be cached forever.
fingerprint_from() {
    local file="$1" key="$2" fallback="$3" found
    found="$(value "$file" "$key")"
    if [[ -n "$found" && "$found" != unknown ]]; then
        printf '%s' "$found"
    else
        printf '%s' "$fallback"
    fi
}

KERNEL_STABLE_FINGERPRINT="$(fingerprint_from "$stable_info" KERNEL_FINGERPRINT "$KERNEL_STABLE_FINGERPRINT")"
KERNEL_RC_FINGERPRINT="$(fingerprint_from "$rc_info" KERNEL_FINGERPRINT "$KERNEL_RC_FINGERPRINT")"
KERNEL_BORE_FINGERPRINT="$(fingerprint_from "$bore_info" KERNEL_FINGERPRINT "$KERNEL_BORE_FINGERPRINT")"
MESA_FINGERPRINT="$(fingerprint_from "$mesa_info" MESA_FINGERPRINT "$MESA_FINGERPRINT")"
LIB32_MESA_FINGERPRINT="$(fingerprint_from "$lib32_info" LIB32_MESA_FINGERPRINT "$LIB32_MESA_FINGERPRINT")"
MESA_GIT_FINGERPRINT="$(fingerprint_from "$mesa_git_info" MESA_GIT_FINGERPRINT "$MESA_GIT_FINGERPRINT")"
BC250_DUAL_AUDIO_FINGERPRINT="$(fingerprint_from "$bc250_dual_audio_info" BC250_DUAL_AUDIO_FINGERPRINT "$BC250_DUAL_AUDIO_FINGERPRINT")"
BC250_CEC_FINGERPRINT="$(fingerprint_from "$bc250_cec_info" BC250_CEC_FINGERPRINT "$BC250_CEC_FINGERPRINT")"
BC250_PACCACHE_CLEANUP_FINGERPRINT="$(fingerprint_from "$bc250_paccache_cleanup_info" BC250_PACCACHE_CLEANUP_FINGERPRINT "$BC250_PACCACHE_CLEANUP_FINGERPRINT")"
BC250_CH7218_FW_FINGERPRINT="$(fingerprint_from "$bc250_ch7218_fw_info" BC250_CH7218_FW_FINGERPRINT "$BC250_CH7218_FW_FINGERPRINT")"
LINUX_CACHYOS_BC250_META_FINGERPRINT="$(fingerprint_from "$linux_cachyos_bc250_meta_info" LINUX_CACHYOS_BC250_META_FINGERPRINT "$LINUX_CACHYOS_BC250_META_FINGERPRINT")"
PROTONGE_LATEST_BC250_FINGERPRINT="$(fingerprint_from "$protonge_info" PROTONGE_LATEST_BC250_FINGERPRINT "$PROTONGE_LATEST_BC250_FINGERPRINT")"
PROTON_CACHYOS_NATIVE_BC250_FINGERPRINT="$(fingerprint_from "$proton_native_info" PROTON_CACHYOS_NATIVE_BC250_FINGERPRINT "$PROTON_CACHYOS_NATIVE_BC250_FINGERPRINT")"

SOURCE_FINGERPRINT="$(printf '%s\n' \
    "$KERNEL_STABLE_FINGERPRINT" "$KERNEL_RC_FINGERPRINT" "$KERNEL_BORE_FINGERPRINT" \
    "$MESA_FINGERPRINT" "$LIB32_MESA_FINGERPRINT" "$MESA_GIT_FINGERPRINT" \
    "$BC250_DUAL_AUDIO_FINGERPRINT" "$BC250_CEC_FINGERPRINT" "$BC250_PACCACHE_CLEANUP_FINGERPRINT" "$BC250_CH7218_FW_FINGERPRINT" "$LINUX_CACHYOS_BC250_META_FINGERPRINT" \
    "$PROTONGE_LATEST_BC250_FINGERPRINT" "$PROTON_CACHYOS_NATIVE_BC250_FINGERPRINT" | \
    sha256sum | awk '{print $1}')"

cat > build-info.env <<EOF_INFO
SOURCE_FINGERPRINT=${SOURCE_FINGERPRINT}
KERNEL_STABLE_FINGERPRINT=${KERNEL_STABLE_FINGERPRINT}
KERNEL_RC_FINGERPRINT=${KERNEL_RC_FINGERPRINT}
KERNEL_BORE_FINGERPRINT=${KERNEL_BORE_FINGERPRINT}
MESA_FINGERPRINT=${MESA_FINGERPRINT}
LIB32_MESA_FINGERPRINT=${LIB32_MESA_FINGERPRINT}
MESA_GIT_FINGERPRINT=${MESA_GIT_FINGERPRINT}
BC250_DUAL_AUDIO_FINGERPRINT=${BC250_DUAL_AUDIO_FINGERPRINT}
BC250_CEC_FINGERPRINT=${BC250_CEC_FINGERPRINT}
BC250_PACCACHE_CLEANUP_FINGERPRINT=${BC250_PACCACHE_CLEANUP_FINGERPRINT}
BC250_CH7218_FW_FINGERPRINT=${BC250_CH7218_FW_FINGERPRINT}
LINUX_CACHYOS_BC250_META_FINGERPRINT=${LINUX_CACHYOS_BC250_META_FINGERPRINT}
PROTONGE_LATEST_BC250_FINGERPRINT=${PROTONGE_LATEST_BC250_FINGERPRINT}
PROTON_CACHYOS_NATIVE_BC250_FINGERPRINT=${PROTON_CACHYOS_NATIVE_BC250_FINGERPRINT}
LAST_RUN_KERNEL_STABLE_BUILD=${BUILD_KERNEL_STABLE}
LAST_RUN_KERNEL_RC_BUILD=${BUILD_KERNEL_RC}
LAST_RUN_KERNEL_BORE_BUILD=${BUILD_KERNEL_BORE}
LAST_RUN_MESA_BUILD=${BUILD_MESA}
LAST_RUN_LIB32_MESA_BUILD=${BUILD_LIB32_MESA}
LAST_RUN_MESA_GIT_BUILD=${BUILD_MESA_GIT}
LAST_RUN_BC250_DUAL_AUDIO_BUILD=${BUILD_BC250_DUAL_AUDIO}
LAST_RUN_BC250_CEC_BUILD=${BUILD_BC250_CEC}
LAST_RUN_BC250_PACCACHE_CLEANUP_BUILD=${BUILD_BC250_PACCACHE_CLEANUP}
LAST_RUN_BC250_CH7218_FW_BUILD=${BUILD_BC250_CH7218_FW}
LAST_RUN_LINUX_CACHYOS_BC250_META_BUILD=${BUILD_LINUX_CACHYOS_BC250_META}
LAST_RUN_PROTONGE_LATEST_BC250_BUILD=${BUILD_PROTONGE_LATEST_BC250}
LAST_RUN_PROTON_CACHYOS_NATIVE_BC250_BUILD=${BUILD_PROTON_CACHYOS_NATIVE_BC250}
KERNEL_STABLE_PKGBASE=${stable_pkgbase}
KERNEL_STABLE_PKGVER=${stable_pkgver}
KERNEL_STABLE_PKGREL=${stable_pkgrel}
KERNEL_RC_PKGBASE=${rc_pkgbase}
KERNEL_RC_PKGVER=${rc_pkgver}
KERNEL_RC_PKGREL=${rc_pkgrel}
KERNEL_BORE_PKGBASE=${bore_pkgbase}
KERNEL_BORE_PKGVER=${bore_pkgver}
KERNEL_BORE_PKGREL=${bore_pkgrel}
MESA_CACHYOS_COMMIT=${mesa_cachyos_commit}
LIB32_MESA_CACHYOS_COMMIT=${lib32_cachyos_commit}
MESA_GIT_CACHYOS_COMMIT=${mesa_git_cachyos_commit}
MESA_PKGVER=${mesa_pkgver}
MESA_PKGREL=${mesa_pkgrel}
MESA_EPOCH=${mesa_epoch}
LIB32_MESA_PKGVER=${lib32_pkgver}
LIB32_MESA_PKGREL=${lib32_pkgrel}
LIB32_MESA_EPOCH=${lib32_epoch}
MESA_GIT_COMMIT=${mesa_git_commit}
MESA_GIT_PKGVER=${mesa_git_pkgver}
MESA_GIT_PKGREL=${mesa_git_pkgrel}
MESA_GIT_LIB32=${mesa_git_lib32}
BC250_DUAL_AUDIO_PKGVER=${bc250_dual_audio_pkgver}
BC250_DUAL_AUDIO_PKGREL=${bc250_dual_audio_pkgrel}
BC250_CEC_PKGVER=${bc250_cec_pkgver}
BC250_PACCACHE_CLEANUP_PKGVER=${bc250_paccache_cleanup_pkgver}
BC250_CH7218_FW_PKGVER=${bc250_ch7218_fw_pkgver}
BC250_CEC_PKGREL=${bc250_cec_pkgrel}
BC250_PACCACHE_CLEANUP_PKGREL=${bc250_paccache_cleanup_pkgrel}
BC250_CH7218_FW_PKGREL=${bc250_ch7218_fw_pkgrel}
LINUX_CACHYOS_BC250_META_PKGVER=${linux_cachyos_bc250_meta_pkgver}
LINUX_CACHYOS_BC250_META_PKGREL=${linux_cachyos_bc250_meta_pkgrel}
PROTONGE_LATEST_BC250_PKGVER=${protonge_pkgver}
PROTONGE_LATEST_BC250_PKGREL=${protonge_pkgrel}
PROTONGE_LATEST_BC250_GE_TAG=${protonge_ge_tag}
PROTONGE_LATEST_BC250_OPTISCALER=${protonge_optiscaler}
PROTON_CACHYOS_NATIVE_BC250_PKGVER=${proton_native_pkgver}
PROTON_CACHYOS_NATIVE_BC250_PKGREL=${proton_native_pkgrel}
PROTON_CACHYOS_NATIVE_BC250_OPTISCALER=${proton_native_optiscaler}
GITHUB_SHA=${GITHUB_SHA:-local}
BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF_INFO

# Built before the notes rather than appended after them, so it sits with the
# other Proton packages instead of trailing the file. Empty until this package
# has published once: a section full of blank versions is worse than no section.
slr_section=""
if [[ "$proton_slr_present" == true ]]; then
    slr_section="$(cat <<EOF_SLR_NOTES
## proton-cachyos-slr-bc250 (opt-in)

- Package version: \`${proton_slr_pkgver}-${proton_slr_pkgrel}\` (\`${proton_slr_srctag}\`)
- The same CachyOS Proton as \`proton-cachyos-native-bc250\`, from the same
  release, but built as a **Steam Linux Runtime** tool — so games that need the
  runtime work with it, including the ones with EasyAntiCheat or BattlEye that
  will not run on the native build at all.
- Compiled from source for this hardware rather than repacked:
  \`-O3 -march=x86-64-v3 -mtune=znver2\` through every component, in Valve's
  Steam Runtime SDK image, by \`scripts/build-proton-runtime-dist.sh\`.
- Same pinned FSR4 payload as the other two: the AMD provider, OptiScaler
  \`${proton_slr_optiscaler}\`, OptiPatcher, fakenvapi \`${proton_slr_fakenvapi}\`
  and the shared preset, all verified by SHA256 before they reach a prefix.
- Installs **alongside** the official \`proton-cachyos-slr\`, not over it. Both
  appear in Steam; this one as **proton-cachyos-… (BC-250 FSR4)**.
- Same launch options as the other two. Note that FSR4 and OptiScaler disable
  themselves when a game is detected as using EasyAntiCheat or BattlEye —
  injecting into those games risks a ban. That detection is a safety net rather
  than a guarantee: set \`PROTON_FSR4_UPGRADE=0 %command%\` yourself when in
  doubt.

\`\`\`bash
sudo pacman -S proton-cachyos-slr-bc250
\`\`\`
EOF_SLR_NOTES
)"
fi

cat > RELEASE_NOTES.md <<EOF_NOTES

# BC-250 CachyOS kernels + Mesa repository

## Kernels

### Stable: \`${stable_pkgbase}\`

- Upstream source: \`${stable_source}\`
- Version: \`${stable_pkgver}-${stable_pkgrel}\`
- Patch set: \`${stable_patch_set}\`
- The Cyan Skillfish DP-audio spread-spectrum fix is omitted: it has been upstream since Linux 7.2.

### Release candidate: \`${rc_pkgbase}\`

- Upstream source: \`${rc_source}\`
- Version: \`${rc_pkgver}-${rc_pkgrel}\`
- Patch set: \`${rc_patch_set}\`
- Built from the \`patches/linux-cachyos-rc\` set, which is maintained against the Linux 7.3-rc series independently of the 7.2 stable set.
- The \`hdmi21-vtem-on-tmds.patch\` carry ("Emit VTEM for HF-VSDB VRR on TMDS links", upstream \`640fd039dc8b\`) has been **dropped**. It is queued for Linux 7.4 -- it landed in \`drm-next\` on 2026-09-02, one day after 7.3-rc1 was tagged -- so it arrives on its own with the next series. It also only ever applied through a passive DP++ adapter; through an active DP->HDMI converter the GPU speaks DisplayPort and the code never ran. The other seven patches of the original backport arrived in \`cachyos-7.3-rc2-1\` via CachyOS's \`7.3/hdmi\` merge and were dropped earlier.
- **\`ch7218-vrr-allowlist.patch\` (RC only)** -- FreeSync passthrough on a Chrontel CH7218 DP-to-HDMI 2.1 adapter (DPCD branch OUI \`2B:02:F0\`, UGREEN DP134 and most compact "8K" plugs). CachyOS's 7.2 kernel lists this converter in the FreeSync PCON allowlist; its 7.3 HDMI branch was rebuilt on a different VRR series and does not, so with the same adapter VRR worked on \`linux-cachyos-bc250\` and was silently absent on \`linux-cachyos-rc-bc250\`. One static table entry, unconditional (it cannot be gated and only states the chip may carry VRR, which it does). Unrelated to the opt-in CH7218 quirk above.
- **\`pcon-vrr-hf-vsdb.patch\` (RC only)** -- the allowlist entry above was necessary but not sufficient. On 7.3 a DP-to-HDMI PCON gets its VRR range only from the AMD FreeSync EDID block, parsed by DMUB/DMCU firmware that DCN201 does not have, so the parse always fails on a BC-250 and the range stays 0/0 even when every DPCD gate passes. This adds what 7.2 already does: fall back to the HDMI Forum VRR range the DRM core parses in software. Covers TVs without an AMD block too. \`drm.debug=0x2\` logs the decision as \`VRR: PCON HF-VSDB fallback\`.
- Also carries \`gud-bound-tv-mode-count.patch\` ("drm/gud: bound the TV mode count"), which rejects a firmware-reported mode count larger than the array it is read into. Only reachable with a GUD USB display attached. Dropped from the stable/BORE set: upstream reverted the commit that causes the underlying FORTIFY_SOURCE trap on the 7.2 branch, confirmed by reading the reverted state directly and not just assuming a version bump fixed it. The 7.3-rc branch still carries the vulnerable code, confirmed by a real \`-O3\`/ThinLTO build that reproduces the failure without this patch.

### BORE: \`${bore_pkgbase}\`

- Upstream source: \`${bore_source}\`
- Version: \`${bore_pkgver}-${bore_pkgrel}\`
- Patch set: \`${bore_patch_set}\`
- Uses the same BC-250 patch set as the stable kernel (\`patches/linux-cachyos\`).

All three kernels use:

- ISA baseline: **x86-64-v3** (CachyOS \`${processor_opt}\`)
- CPU tuning: **Zen 2** (\`KCFLAGS=-mtune=${cpu_tune}\`)
- BC-250 telemetry/GPU-activity fixes, with 8-core SMU metrics decoding matched to the patched SMU firmware in the current community BIOS. **8-core boards must run patched SMU firmware -- there is no supported fallback for stock/unpatched SMU firmware on 8 cores.** Patch it via https://github.com/Forbidden-Darkness/AMD-BC-250-UEFI-v2.2-Firmware-Menu-Script/releases (prebuilt flashable UEFI) or https://github.com/rw-r-r-0644/bc250-smu-unlock (userspace patcher)
- GFX1013 PASID TLB invalidation fix and compute GFXOFF guard
- Opt-in KFD/HWS runlist TLB workaround (\`amdgpu.bc250_flush_by_runlist=1\`)
- AMDGPU TTM NULL-page cleanup guard for partially populated BOs
- Widened Cyan Skillfish SMU SCLK range (350-2230 MHz) for userspace SMU governors
- 4K120 at 4:4:4 over HDMI 2.1, on by default: HDMI 2.1 PCON negotiation (\`dcn201-hdmi21-pcon.patch\`) and the two on-die DCN201 DSC engines (\`dcn201-enable-dsc.patch\`) through an active DP 1.4 -> HDMI 2.1 FRL adapter. Verified on a BC-250 into an LG G5 via a UGREEN 8K adapter: FRL PCON negotiated, DSC at 12 bpp, 3840x2160@120 RGB with HDR. A native DisplayPort monitor or a passive adapter is untouched either way. \`amdgpu.bc250_hdmi21=0\` switches it off and gives an unpatched kernel back. Not upstream -- the work of TeleBooth (https://gist.github.com/TeleBooth/d88ef745895d444a401d0e621de9818e).
- **Opt-in: CH7218 adapter quirk for a black screen at 4K120** (found, diagnosed and originally written by **@dejan_994**). Some DP-to-HDMI 2.1 adapters built on a Chrontel CH7218 -- UGREEN units among them, DPCD branch OUI \`2B:02:F0\`, branch name \`CH7218\` -- ship firmware that reports no HDMI downstream port, or reports it as DisplayPort, when the adapter is in fact a DP-to-HDMI 2.1 converter. The driver believes it, never negotiates FRL, and sends 4K90/4K120 as plain DisplayPort video the adapter cannot emit over TMDS: black screen, while 4K60 keeps working. \`ch7218-pcon-quirk.patch\` forces the converter identity and restores the 12 bpc / FRL 48 Gbps / YCbCr 4:2:2 and 4:2:0 ceilings. **Off by default -- enable with \`amdgpu.bc250_ch7218_quirk=1\`** alongside the default \`amdgpu.bc250_hdmi21=1\`, then confirm with \`cat /sys/module/amdgpu/parameters/bc250_ch7218_quirk\` (the \`CH7218 quirk\` dmesg lines appear only in a detection where the firmware actually misreported; a correctly-reporting adapter is left untouched and silent, and since this build the final ceiling re-assert is also limited to those detections). It stays opt-in because plenty of CH7218 adapters work correctly and nothing in the DPCD tells a broken unit from a healthy one, so enabling it for everyone would override correct information from working hardware. With the parameter unset the kernel behaves exactly as it would without the patch: every part of this workaround checks the switch before touching anything. If 4K120 is still absent afterwards, check the sink EDID for CTA VIC 118 -- that is a display limitation, not a kernel one. Details in docs/PATCHES.md.
- **Experimental, opt-in: \`pcon-force-dsc.patch\`** -- for DP-to-HDMI 2.1 adapters that advertise no DSC decoder although the chip has one. A Cable Matters 102101 (Synaptics VMM7100, fw 7.02.120) reports no DSC and no FEC on this board, so 4K120 is built as YCbCr 4:2:2 10-bit instead of RGB 12-bit with DSC. \`amdgpu.bc250_pcon_force_dsc=1\` advertises a DSC 1.2a decoder and FEC on behalf of an adapter whose DSC block is entirely zero (the block a known-good CH7218 reports is used as the template) and drives it accordingly. It is a probe of the adapter's firmware, not a fix: if it really cannot decode, 4K120 comes up black or corrupted and the parameter must be removed. Adapters that advertise any DSC capability are never touched. Logs what it overrode at warning level. Off by default; with the parameter unset the helper returns before touching anything.
- **Always on: a CH7218 that denies its own DSC decoder is corrected.** Split out of the opt-in quirk above into \`ch7218-dsc-restore.patch\`, and deliberately not behind a parameter. Some CH7218 firmware clears DP_DSC_SUPPORT while still reporting the decoder's revision, slice capabilities and maximum bits per pixel -- a combination that cannot describe real hardware. DC believed the bit, and since a DP 1.4 HBR3 x4 link cannot carry 4K120 RGB uncompressed, the stream came back as YCbCr 4:2:2 10-bit instead: picture unaffected, colour detail quietly worse, nothing logged. Seen on an adapter that reports everything else correctly, after the display returned from standby. Unlike the identity quirk this cannot override a correct report -- if the bit is set there is nothing to do, and if the capability block is empty the adapter really has no decoder -- so it needs no opt-in. \`amdgpu.bc250_hdmi21=0\` switches it off with the rest of the PCON path; \`dmesg | grep 'restored cleared DSC_SUPPORT'\` shows when it stepped in.
- **Fixed: the display going dark on a mode change.** The BC-250 reaches HDMI through a DP-to-HDMI 2.1 converter; when the display stream stays off longer than a few seconds -- a slow session handover -- the converter drops its HDMI side, and the driver brings the picture back from cached link state without re-detecting, reporting success into a dead link. \`cs-relink-after-long-blank.patch\` now times the blank and forces a full re-detect (the same thing a cable re-plug does) when the stream returns after more than \`amdgpu.cs_relink_ms\` milliseconds, default 3000, a quarter second after the mode is set. Short switches are untouched: a normal handover blanks for about 0.1 s. Runtime-writable knobs: \`cs_relink_ms\` (3000; 0 disables), \`cs_relink_delay_ms\` (250), \`cs_relink_cooldown_ms\` (10000, a hard loop breaker), \`cs_relink_at_boot\` (0), \`cs_relink_debug\` (on; \`dmesg | grep 'bc250 relink'\`). **\`cs_relink_at_boot\` is new and OFF by default**: the blank timer only sees blanks that happen while the driver is running, so a machine that boots with the adapter already stuck gets no help -- reported surviving several reboots before clearing on its own. Set \`amdgpu.cs_relink_at_boot=1\` to also re-detect once on the first screen of a boot, then read \`dmesg | grep 'bc250 relink'\` to see what it decided. It stays off because the benefit is unproven -- the driver already runs a full detect about three seconds earlier, and nothing can tell a stuck adapter from a healthy one -- while the cost is a real mode change and hotplug event rather than a quiet probe. Bounded to the first 60 s of uptime, and it does not start the cooldown timer, so it cannot swallow the first genuine long blank of the boot. **Not a DSC problem** -- reproduced with \`amdgpu.bc250_hdmi21=0\` on an uncompressed 4-lane HBR2 link. A GPU governor is not the cause but makes it far more likely, because it lengthens session handovers (0.09 s without, 4.4 s with, same switch); \`temp-read = \"sysfs\"\` avoids that. Verified to arm on every blank over the threshold and recover each time, without looping; not verified that every recovery was necessary, since long blanks sometimes survived unaided before the patch. Details and the measurements in docs/PATCHES.md.
- Opt-in 40 CU unlock (\`amdgpu.bc250_cc_write_mode=3\`), off by default; cap clocks to ~1500 MHz before enabling
- **the BC-250 secure processor (PCI \`1022:143e\`) is bound by the \`ccp\` driver** -- a carry of Mattia Tadini's 3-patch series (LKML, 2026-09-19, unmerged): two generic PSP init fixes plus the board's register layout. Platform access only (no SEV, no TEE, no crypto engine); the device stops being \`(no driver)\` and its firmware version is readable from sysfs. Nothing user-facing depends on it.
- \`nct6687.ko\` from Fred78290/nct6687d commit \`${nct_commit}\`
- upstream \`nct6683\` disabled to avoid claiming the same Super-I/O IDs
- **BC-250 VRM and GDDR6 temperature drivers** -- \`bc250_vrm.ko\` (Hexxeh/bc250-vrm-dkms \`${bc250_vrm_tag:-untagged}\`, \`${bc250_vrm_commit:-unknown}\`) and \`bc250_memory.ko\` (Hexxeh/bc250-memory-dkms \`${bc250_memory_tag:-untagged}\`, \`${bc250_memory_commit:-unknown}\`), built into all three kernels. \`bc250_vrm\` loads automatically and reads CPU/GPU rail voltage, current, temperature and power from the VRM controller; it needs a small hardware modification that wires its SMBus lines, and without it binds to nothing. \`bc250_memory\` is opt-in: it is built without its automatic-load alias, so it loads only when you add it to \`/etc/modules-load.d/\` (or run \`sudo modprobe bc250_memory\`). \`bc250_memory\` reads per-chip GDDR6 temperatures through the SMU; on load it patches SMU firmware memory (\`auto_patch=1\`) and needs a BIOS with SMU debug access, otherwise it refuses to load. Details in the README.

## Patched stable CachyOS Mesa

- CachyOS packaging commit: \`${mesa_cachyos_commit}\`
- Version: \`${mesa_pkgver}-${mesa_pkgrel}\`${mesa_epoch:+ (epoch ${mesa_epoch})}
- Applied patches: \`0001\` compute-queue fix, \`0002\` DirectMesh v1.3 mesh/task shaders, \`0003\` BC-250 FSR4 EXP-042B (V3) deferred SDot lowering, \`0004\` FSR4 combined-unroll selection, \`0005\` FSR4 image-preparation and texture candidates, \`0006\` FSR4 resolution-variant coverage and 8K masked-store guard, \`0007\` FSR4 production defaults.
- **Mesh and task shaders (DirectMesh v1.3 by lonewolf0622)**: \`VK_EXT_mesh_shader\` (Mesh and Task), \`VK_KHR_fragment_shader_barycentric\`, and since v1.2 D3D12 \`ExecuteIndirect\` with mesh draws (device-generated commands) and multiview with mesh shaders, and since v1.3 indexed mesh draws (meshlets of 96+ vertices about 1.5-1.9x faster than v1.2, per the author) on the BC-250, opt-in per game with \`RADV_DIRECTMESH=1 %command%\`. The value must be exactly \`1\`; the same switch also enables fragment shader barycentrics and a no-op variable-rate-shading extension for DirectX 12 Ultimate. Without it none of this is exposed (unlike upstream, which exposes mesh on every BC-250 by default), and other GPUs are never affected. Mesh is drawn on a safe direct path that rules out the index patterns that hang this chip, and anything that cannot be proven safe is refused rather than drawn unprotected. The author reports 3,558/3,558 mesh-shader CTS cases passing on hardware with no hangs (v1.3: 1,902/1,902 \`dEQP-VK.mesh_shader.*\` including multiview), and Final Fantasy VII Rebirth, Control, Hellblade 2, Alan Wake 2 and Crimson Desert running; not yet re-tested on hardware with this build. Replaces the old \`RADV_GFX103=1\` override, which no longer does anything. While enabled, D3D12 games do not get graphics pipeline libraries or shader objects (DXVK games keep them); mesh pipeline-statistics queries and per-primitive shading rate from mesh shaders are not supported. The switch also turns on wider NGG culling and 32-byte render-target compression blocks for everything the game draws. \`RADV_DEBUG=nomeshshader\` hides mesh shaders for comparison, and \`RADV_BC250_MESH_IDXPASS=0\` keeps v1.3 on its older Mesh route.
- \`0004\`-\`0007\` are all active by default: \`0007\` flips the \`0005\`/\`0006\` candidates on, so \`BC250_FSR4_IMAGEPREP\`, \`BC250_FSR4_TEXTURE\` and \`BC250_FSR4_RESOLUTION_VARIANTS\` default to enabled and are set to \`0\` to turn them off, not to \`1\` to turn them on. \`BC250_FSR4_DISABLE=1\` switches off the profile-specific rewrites entirely. Every FSR4 rewrite is gated on exact shader identity, so an unmatched shader is left untouched.
- \`0004\`-\`0006\` are the work of fish / @iamastrangeloop, \`0007\` of daniel-h-0, rebased onto this tree. Their reported figure for \`0004\` is 8.015 ms to 5.843 ms per FSR4.1.1 INT8 upscale at 1440p Balanced (27.1%); the opt-in candidates measure around 1% each and are not independently verified here.
- \`0001\` and \`0003\` are always active. \`0003\`'s multiply-chain \`SDot\` lowering is restricted to RADV/ACO on GFX1013 (upstream applied it to every driver without hardware dot product, including ones that cannot compile the opcode it emits). The FSR4 shader-cache separation is likewise limited to the BC-250, so other AMD GPUs keep upstream's cache UUID.
- Every LLVM-linked Mesa package is pinned to the LLVM it was built with, so pacman refuses an LLVM update that would leave no working driver, until a Mesa built for the new LLVM is published.
- CPU target: \`-march=x86-64-v3 -mtune=znver2\`

## Patched stable CachyOS lib32-mesa

- CachyOS packaging commit: \`${lib32_cachyos_commit}\`
- Version: \`${lib32_pkgver}-${lib32_pkgrel}\`${lib32_epoch:+ (epoch ${lib32_epoch})}
- Uses the same patch series and runtime gating as stable 64-bit Mesa.
- CPU target: \`-march=x86-64-v3 -mtune=znver2\`

## Patched CachyOS mesa-git

- CachyOS packaging commit: \`${mesa_git_cachyos_commit}\`
- Mesa main commit: \`${mesa_git_commit}\`
- Package version: \`${mesa_git_pkgver}-${mesa_git_pkgrel}\`
- Builds both \`mesa-git\` and \`lib32-mesa-git\` from the same pinned Mesa commit.
- Applies the same separately rebased \`0001\`-\`0007\` series, in order, as the stable Mesa packages.
- \`0001\` and the FSR4 patches \`0003\`-\`0007\` are active; DirectMesh mesh/task shaders are opt-in with \`RADV_DIRECTMESH=1\`. The mesa-git DirectMesh is a port onto Mesa main (it targets 26.2): it carries a taskmesh firmware-bug workaround main deleted, which the BC-250 still needs.
- CPU target: \`-march=x86-64-v3 -mtune=znver2\`

## BC-250 dual-output audio

- Package version: \`${bc250_dual_audio_pkgver}-${bc250_dual_audio_pkgrel}\`
- Packages [MastaG/bc250-dual-audio](https://github.com/MastaG/bc250-dual-audio):
  a WirePlumber policy giving the BC-250 two permanent, mutually-exclusive
  outputs — native HDMI/DP (untouched, EDID/ELD-driven) and a switchable
  Dolby Digital 5.1 (AC3) virtual sink, selectable like any other output in
  Steam or KDE.
- Installed by \`linux-cachyos-bc250-meta\`; otherwise install with \`sudo pacman -S bc250-dual-audio\`.

\`\`\`bash
sudo pacman -S bc250-dual-audio
systemctl --user restart pipewire pipewire-pulse wireplumber
/usr/share/bc250-dual-audio/check.sh
\`\`\`

## BC-250 CEC

- Package version: \`${bc250_cec_pkgver}-${bc250_cec_pkgrel}\`
- Identifies this board to the HDMI CEC bus as \`SteamOS\`, and replugs the
  HDMI link (the same re-detect a physical cable pull triggers) when the
  display reports powering on over CEC -- catching cases the kernel's own
  blank-duration relink heuristic does not, since it reacts to the display's
  actual power state instead of a timer. Detection only: it never sends a
  power command to the display.
- Needs a CEC-capable link -- most DP-to-HDMI adapters do not tunnel CEC
  (check with \`cec-ctl --list-devices\`). Enabled automatically on install
  and pulled in by \`linux-cachyos-bc250-meta\`; without a CEC adapter it
  waits for one to appear and otherwise sits idle.

## Older builds

- The three previous builds of every package stay on this release for
  downgrades; the pacman database lists only the current one. The list is in
  \`archive-index.txt\`; install one with
  \`sudo pacman -U https://github.com/MastaG/linux-cachyos-bc250/releases/download/repo/<file>\`.

## BC-250 pacman cache cleanup (opt-in)

- Package version: \`${bc250_paccache_cleanup_pkgver}-${bc250_paccache_cleanup_pkgrel}\`
- A pacman hook that empties the package cache after every install, upgrade
  or removal (\`paccache -rk0\` and \`paccache -ruk0\`), so updates stop
  filling the BC-250's small disk with old packages. Downgrades come from this
  repository, which keeps older builds, instead of the local cache.
- Not part of \`linux-cachyos-bc250-meta\`; install it if you want it:
  \`sudo pacman -S bc250-paccache-cleanup\`.

## BC-250 CH7218 adapter firmware flasher (opt-in)

- Package version: \`${bc250_ch7218_fw_pkgver}-${bc250_ch7218_fw_pkgrel}\`
- For the UGREEN DisplayPort to HDMI 2.1 adapter (Chrontel CH7218A): UGREEN's
  own Linux updater, UGREEN's 07.00.54 firmware unchanged, and two copies of it
  with the HDMI scrambling watchdog (one byte) and the HDMI 2.1 link monitor
  (a second byte) kept running. The first fixed image is what the author runs;
  the second is untested.
- Nothing runs on its own: flashing is \`sudo bc250-ch7218-flash flash
  original|tmds|tmds-frl\`, run by hand, and only on an adapter on firmware
  07.00.xx (54 or older). Read \`/usr/share/doc/bc250-ch7218-fw/README.md\` first.
- Not part of \`linux-cachyos-bc250-meta\`:
  \`sudo pacman -S bc250-ch7218-fw\`.

## aic8800d80-dkms -- removed

- This repository no longer builds the AIC8800D80 USB WiFi driver: upstream
  merged our Linux 7.3 fix ([shenmintao/aic8800d80#91](https://github.com/shenmintao/aic8800d80/pull/91))
  on 2026-09-24, and the AUR \`aic8800d80-dkms\` package builds from upstream
  \`main\`, so it is now correct on every kernel here. Ours has been removed from
  the repository database.
- If you installed ours, \`pacman -Syu\` will not replace it: it is no longer in
  this repository's database, so pacman treats it as foreign, and AUR helpers
  will not downgrade it to the AUR's lower release number. Swap it once by
  building the AUR package and installing it in one transaction, which keeps a
  driver present throughout: \`git clone https://aur.archlinux.org/aic8800d80-dkms.git
  && cd aic8800d80-dkms && makepkg -si\`. DKMS rebuilds the modules for every
  installed kernel that has its headers package.

## protonge-latest-bc250 (opt-in)

- Package version: \`${protonge_pkgver}-${protonge_pkgrel}\` (\`${protonge_ge_tag}\`)
- GE-Proton, installed system-wide as a Steam compatibility tool with everything
  FSR 4.1.1 needs on this hardware already pinned inside it: the AMD provider,
  OptiScaler \`${protonge_optiscaler}\`, OptiPatcher, fakenvapi
  \`${protonge_fakenvapi}\` and a known-good OptiScaler configuration. Nothing is
  downloaded when a game starts, and every artifact is SHA256-verified before it
  reaches a prefix.
- [fakenvapi](https://github.com/optiscaler/fakenvapi) is bundled and always
  active, with no variable to enable it: it stands in for \`nvapi64.dll\` so
  OptiScaler can reach AntiLag 2, Vulkan AntiLag+, XeLL or LatencyFlex in games
  that would otherwise require NVIDIA Reflex. It is tracked live rather than
  pinned, so a new upstream release rebuilds this package.
- Installs alongside the distro's own Proton packages rather than replacing them.
  It appears in Steam as **GE-Proton ${protonge_ge_tag#GE-Proton} (BC-250 FSR4)**;
  pick it per game under Properties -> Compatibility, or as the global default.
- Needs the \`vulkan-radeon\` package from this repository: the FSR4 support the
  provider calls into lives in our patched RADV, not in stock Mesa.
- FSR4 and OptiScaler are on by default. They remain launch options, so
  \`PROTON_FSR4_UPGRADE=0 %command%\` turns FSR4 off for one game, and
  \`BC250_FSR4_DEBUG=1 %command%\` adds the OptiScaler watermark plus logging.
- The default upscaler is now HelixSR (see below). The BC-250 FSR4 fork's
  [RC11](https://github.com/daniel-h-0/bc250-fsr4-fork/releases/tag/v4.0.0-rc11)
  bridge (\`4.1.1r11\`, by daniel-h-0), the previous default, stays one launch
  option away: \`PROTON_USE_OPTISCALER=fsr411f %command%\`. Two more
  alternatives swap only that file, per game, each pinned by SHA256:
  \`PROTON_USE_OPTISCALER=signed %command%\` for AMD's signed 4.0.2 bridge, and
  \`PROTON_USE_OPTISCALER=fsr411b %command%\` for the third-party
  [4.1.1b](https://github.com/the3rdparty1917/fsr4xyz/releases/tag/4.1.1b)
  rebuild aimed at RDNA2 ghosting. Neither 4.1.1r11 nor 4.1.1b is a provider
  bump: each carries its own embedded model, and both are unsigned.
- **Changed: HelixSR is the default** ([1.3.0](https://github.com/lonewolf0622/HelixSR/releases/tag/v1.3.0)
  by lonewolf0622), replacing the FSR4 fork's bridge. It is an FSR 3.1 upscaler that runs NVIDIA's DLSS network (Model E) as D3D12 compute,
  so DLSS-quality reconstruction without an NVIDIA GPU. Direct3D 12 games only.
  1.3.0 is faster than 1.2.0 on the BC-250 by its author's measurements (about 30% less
  GPU time in Ultra Performance, and roughly a quarter less at several 1440p and 4K
  sizes) with the same image; the new \`NetworkResolution\` key in \`helixsr.ini\` defaults to \`auto\`.
  It replaces FSR4 for the game; its log is switched off. Per its author, the
  DLSS weights and kernels it runs remain NVIDIA's property. If a game looks
  wrong, \`PROTON_USE_OPTISCALER=fsr411f %command%\` goes back to the old default.

\`\`\`bash
sudo pacman -S protonge-latest-bc250
\`\`\`

## proton-cachyos-native-bc250 (opt-in)

- Package version: \`${proton_native_pkgver}-${proton_native_pkgrel}\`
- CachyOS's own Proton, rebuilt for Zen 2 (\`-march=x86-64-v3 -mtune=znver2\`) with
  the same pinned FSR4 payload as \`protonge-latest-bc250\`: the AMD provider,
  OptiScaler \`${proton_native_optiscaler}\`, OptiPatcher, fakenvapi
  \`${proton_native_fakenvapi}\` and a known-good OptiScaler configuration, all
  verified by SHA256 before they reach a prefix.
- [fakenvapi](https://github.com/optiscaler/fakenvapi) is bundled and always
  active, with no variable to enable it, and tracked live rather than pinned —
  see the GE package above for what it does.
- Installs **alongside** the official \`proton-cachyos-native\`, not over it:
  \`provides\` and \`replaces\` are cleared, and every installed path plus the
  Steam-internal tool name is derived from the package name. Both appear in
  Steam; this one as **proton-cachyos-… (native, BC-250 FSR4)**.
- Needs the \`vulkan-radeon\` package from this repository.
- Same launch options as the GE package: \`PROTON_FSR4_UPGRADE=0 %command%\` to
  turn FSR4 off for one game, \`BC250_FSR4_DEBUG=1 %command%\` for the watermark
  and logs, and the same bridge choice —
  \`PROTON_USE_OPTISCALER=signed\` / \`fsr411b\` — described above.

\`\`\`bash
sudo pacman -S proton-cachyos-native-bc250
\`\`\`

${slr_section}

## linux-cachyos-bc250-meta

- Package version: \`${linux_cachyos_bc250_meta_pkgver}-${linux_cachyos_bc250_meta_pkgrel}\`
- Pure metapackage, no files of its own: installing it pulls in \`linux-cachyos-bc250\`, \`linux-cachyos-bc250-headers\`, \`bc250-dual-audio\`, \`bc250-cec\` and all three FSR4 Proton packages (\`proton-cachyos-native-bc250\`, \`proton-cachyos-slr-bc250\`, \`protonge-latest-bc250\`) together. \`bc250-paccache-cleanup\` is deliberately not included.
- The three Proton packages are alternatives, not complements: the same pinned FSR4 payload over a different Proton. Having all three costs roughly 4.5 GB and puts three entries in Steam's compatibility list, so install them individually instead if you would rather pick one.
- Future BC-250 extras (for example a VCN unlock, once that lands) get added to this package's dependency list rather than requiring a new manual install step: once you have this package installed, \`sudo pacman -Syu\` picks up new extras automatically the next time this package's version is bumped for that.

\`\`\`bash
sudo pacman -S linux-cachyos-bc250-meta
\`\`\`
EOF_NOTES

printf 'BC-250 kernels — stable %s, RC %s, BORE %s' \
    "$stable_pkgver" "$rc_pkgver" "$bore_pkgver" > release-title.txt

# SHA256SUMS is regenerated by update-repo-db.sh, but the aggregate files
# written above (build-info.env, RELEASE_NOTES.md, release-title.txt) came after
# it, so refresh it once more to cover them.
"${ROOT_DIR}/scripts/update-repo-db.sh" >/dev/null

printf '==> Final repository contains %d packages\n' "${#packages[@]}"
printf '    stable kernel: %s-%s\n' "$stable_pkgver" "$stable_pkgrel"
printf '    RC kernel:     %s-%s\n' "$rc_pkgver" "$rc_pkgrel"
printf '    BORE kernel:   %s-%s\n' "$bore_pkgver" "$bore_pkgrel"
printf '    mesa:          %s-%s\n' "$mesa_pkgver" "$mesa_pkgrel"
printf '    lib32-mesa:    %s-%s\n' "$lib32_pkgver" "$lib32_pkgrel"
printf '    mesa-git:      %s-%s (64-bit + lib32)\n' "$mesa_git_pkgver" "$mesa_git_pkgrel"
printf '    bc250-dual-audio: %s-%s\n' "$bc250_dual_audio_pkgver" "$bc250_dual_audio_pkgrel"
printf '    bc250-cec: %s-%s\n' "$bc250_cec_pkgver" "$bc250_cec_pkgrel"
printf '    bc250-paccache-cleanup: %s-%s\n' "$bc250_paccache_cleanup_pkgver" "$bc250_paccache_cleanup_pkgrel"
printf '    bc250-ch7218-fw: %s-%s\n' "$bc250_ch7218_fw_pkgver" "$bc250_ch7218_fw_pkgrel"
printf '    linux-cachyos-bc250-meta: %s-%s\n' "$linux_cachyos_bc250_meta_pkgver" "$linux_cachyos_bc250_meta_pkgrel"
printf '    protonge-latest-bc250: %s-%s (%s, OptiScaler %s)\n' \
    "$protonge_pkgver" "$protonge_pkgrel" "$protonge_ge_tag" "$protonge_optiscaler"
printf '    proton-cachyos-native-bc250: %s-%s (OptiScaler %s)\n' \
    "$proton_native_pkgver" "$proton_native_pkgrel" "$proton_native_optiscaler"
