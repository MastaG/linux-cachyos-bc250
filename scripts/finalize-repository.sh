#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${ROOT_DIR}/out/repo"
REPO_NAME="bc250-cachyos"

: "${KERNEL_STABLE_FINGERPRINT:?KERNEL_STABLE_FINGERPRINT is required}"
: "${KERNEL_RC_FINGERPRINT:?KERNEL_RC_FINGERPRINT is required}"
: "${KERNEL_BORE_FINGERPRINT:?KERNEL_BORE_FINGERPRINT is required}"
: "${MESA_FINGERPRINT:?MESA_FINGERPRINT is required}"
: "${LIB32_MESA_FINGERPRINT:?LIB32_MESA_FINGERPRINT is required}"
: "${MESA_GIT_FINGERPRINT:?MESA_GIT_FINGERPRINT is required}"

BUILD_KERNEL_STABLE="${BUILD_KERNEL_STABLE:-false}"
BUILD_KERNEL_RC="${BUILD_KERNEL_RC:-false}"
BUILD_KERNEL_BORE="${BUILD_KERNEL_BORE:-false}"
BUILD_MESA="${BUILD_MESA:-false}"
BUILD_LIB32_MESA="${BUILD_LIB32_MESA:-false}"
BUILD_MESA_GIT="${BUILD_MESA_GIT:-false}"

required_metadata=(
    kernel-stable-info.env
    kernel-rc-info.env
    kernel-bore-info.env
    mesa-info.env
    lib32-mesa-info.env
    mesa-git-info.env
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

for field in \
    stable_pkgbase stable_pkgver stable_pkgrel \
    rc_pkgbase rc_pkgver rc_pkgrel \
    bore_pkgbase bore_pkgver bore_pkgrel \
    mesa_pkgver mesa_pkgrel lib32_pkgver lib32_pkgrel \
    mesa_git_commit mesa_git_pkgver mesa_git_pkgrel mesa_git_lib32; do
    [[ -n "${!field}" ]] || {
        printf 'ERROR: missing metadata field %s\n' "$field" >&2
        exit 1
    }
done

[[ "$stable_pkgbase" == linux-cachyos-bc250 ]] || { printf 'ERROR: unexpected stable pkgbase: %s\n' "$stable_pkgbase" >&2; exit 1; }
[[ "$rc_pkgbase" == linux-cachyos-rc-bc250 ]] || { printf 'ERROR: unexpected RC pkgbase: %s\n' "$rc_pkgbase" >&2; exit 1; }
[[ "$bore_pkgbase" == linux-cachyos-bore-bc250 ]] || { printf 'ERROR: unexpected BORE pkgbase: %s\n' "$bore_pkgbase" >&2; exit 1; }
[[ "$stable_patch_set" == kernel-7.1 && "$bore_patch_set" == kernel-7.1 ]] || {
    printf 'ERROR: stable and BORE kernels must use kernel-7.1 patch set\n' >&2
    exit 1
}
[[ "$rc_patch_set" == kernel-7.2 ]] || {
    printf 'ERROR: RC kernel must use kernel-7.2 patch set\n' >&2
    exit 1
}

cd -- "$OUT_DIR"
shopt -s nullglob
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

(( stable_count >= 2 )) || { printf 'ERROR: expected stable kernel + headers; found %d package(s)\n' "$stable_count" >&2; exit 1; }
(( rc_count >= 2 )) || { printf 'ERROR: expected RC kernel + headers; found %d package(s)\n' "$rc_count" >&2; exit 1; }
(( bore_count >= 2 )) || { printf 'ERROR: expected BORE kernel + headers; found %d package(s)\n' "$bore_count" >&2; exit 1; }
(( mesa_count >= 1 )) || { printf 'ERROR: stable Mesa packages are missing\n' >&2; exit 1; }
(( lib32_count >= 1 )) || { printf 'ERROR: lib32-mesa packages are missing\n' >&2; exit 1; }
(( mesa_git_count == 2 )) || { printf 'ERROR: expected mesa-git + lib32-mesa-git; found %d package(s)\n' "$mesa_git_count" >&2; exit 1; }

rm -f -- "${REPO_NAME}.db" "${REPO_NAME}.db.tar.zst" \
          "${REPO_NAME}.files" "${REPO_NAME}.files.tar.zst"
repo-add "${REPO_NAME}.db.tar.zst" "${packages[@]}"
cp -L --remove-destination "${REPO_NAME}.db.tar.zst" "${REPO_NAME}.db"
cp -L --remove-destination "${REPO_NAME}.files.tar.zst" "${REPO_NAME}.files"

SOURCE_FINGERPRINT="$(printf '%s\n' \
    "$KERNEL_STABLE_FINGERPRINT" "$KERNEL_RC_FINGERPRINT" "$KERNEL_BORE_FINGERPRINT" \
    "$MESA_FINGERPRINT" "$LIB32_MESA_FINGERPRINT" "$MESA_GIT_FINGERPRINT" | \
    sha256sum | awk '{print $1}')"

cat > build-info.env <<EOF_INFO
SOURCE_FINGERPRINT=${SOURCE_FINGERPRINT}
KERNEL_STABLE_FINGERPRINT=${KERNEL_STABLE_FINGERPRINT}
KERNEL_RC_FINGERPRINT=${KERNEL_RC_FINGERPRINT}
KERNEL_BORE_FINGERPRINT=${KERNEL_BORE_FINGERPRINT}
MESA_FINGERPRINT=${MESA_FINGERPRINT}
LIB32_MESA_FINGERPRINT=${LIB32_MESA_FINGERPRINT}
MESA_GIT_FINGERPRINT=${MESA_GIT_FINGERPRINT}
LAST_RUN_KERNEL_STABLE_BUILD=${BUILD_KERNEL_STABLE}
LAST_RUN_KERNEL_RC_BUILD=${BUILD_KERNEL_RC}
LAST_RUN_KERNEL_BORE_BUILD=${BUILD_KERNEL_BORE}
LAST_RUN_MESA_BUILD=${BUILD_MESA}
LAST_RUN_LIB32_MESA_BUILD=${BUILD_LIB32_MESA}
LAST_RUN_MESA_GIT_BUILD=${BUILD_MESA_GIT}
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
GITHUB_SHA=${GITHUB_SHA:-local}
BUILD_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
EOF_INFO

cat > RELEASE_NOTES.md <<EOF_NOTES
# BC-250 CachyOS kernels + Mesa repository

## Kernels

### Stable: \`${stable_pkgbase}\`

- Upstream source: \`${stable_source}\`
- Version: \`${stable_pkgver}-${stable_pkgrel}\`
- Patch set: \`${stable_patch_set}\`
- Includes the Cyan Skillfish DP-audio spread-spectrum fix required by Linux 7.1.

### Release candidate: \`${rc_pkgbase}\`

- Upstream source: \`${rc_source}\`
- Version: \`${rc_pkgver}-${rc_pkgrel}\`
- Patch set: \`${rc_patch_set}\`
- The separate audio patch is intentionally omitted because the fix is already upstream in the current 7.2 RC source.

### BORE: \`${bore_pkgbase}\`

- Upstream source: \`${bore_source}\`
- Version: \`${bore_pkgver}-${bore_pkgrel}\`
- Patch set: \`${bore_patch_set}\`
- Uses the same Linux 7.1 BC-250 patch set as the stable kernel, including the audio fix.

All three kernels use:

- ISA baseline: **x86-64-v3** (CachyOS \`${processor_opt}\`)
- CPU tuning: **Zen 2** (\`KCFLAGS=-mtune=${cpu_tune}\`)
- BC-250 telemetry/GPU-activity fixes
- GFX1013 PASID TLB invalidation fix and compute GFXOFF guard
- \`nct6687.ko\` from Fred78290/nct6687d commit \`${nct_commit}\`
- upstream \`nct6683\` disabled to avoid claiming the same Super-I/O IDs

## Patched stable CachyOS Mesa

- CachyOS packaging commit: \`${mesa_cachyos_commit}\`
- Version: \`${mesa_pkgver}-${mesa_pkgrel}\`${mesa_epoch:+ (epoch ${mesa_epoch})}
- Applied patch: \`0001-gfx1013-compute-queue-fix.patch\`
- CPU target: \`-march=x86-64-v3 -mtune=znver2\`
- Mesh/task patches remain disabled.

## Patched stable CachyOS lib32-mesa

- CachyOS packaging commit: \`${lib32_cachyos_commit}\`
- Version: \`${lib32_pkgver}-${lib32_pkgrel}\`${lib32_epoch:+ (epoch ${lib32_epoch})}
- Uses the same Mesa release and active GFX1013 compute-queue patch as stable 64-bit Mesa.
- CPU target: \`-march=x86-64-v3 -mtune=znver2\`

## Patched CachyOS mesa-git

- CachyOS packaging commit: \`${mesa_git_cachyos_commit}\`
- Mesa main commit: \`${mesa_git_commit}\`
- Package version: \`${mesa_git_pkgver}-${mesa_git_pkgrel}\`
- Builds both \`mesa-git\` and \`lib32-mesa-git\` from the same pinned Mesa commit.
- Applied Git-rebased patch: \`mesa-git-0001-gfx1013-compute-queue-fix.patch\`
- CPU target: \`-march=x86-64-v3 -mtune=znver2\`
- Rebased mesh/task patches are published but remain disabled because they can hard-hang GFX1013.
EOF_NOTES

printf 'BC-250 kernels — stable %s, RC %s, BORE %s' \
    "$stable_pkgver" "$rc_pkgver" "$bore_pkgver" > release-title.txt

rm -f -- SHA256SUMS
while IFS= read -r -d '' file; do
    sha256sum "${file#./}"
done < <(find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 | sort -z) > SHA256SUMS

printf '==> Final repository contains %d packages\n' "${#packages[@]}"
printf '    stable kernel: %s-%s\n' "$stable_pkgver" "$stable_pkgrel"
printf '    RC kernel:     %s-%s\n' "$rc_pkgver" "$rc_pkgrel"
printf '    BORE kernel:   %s-%s\n' "$bore_pkgver" "$bore_pkgrel"
printf '    mesa:          %s-%s\n' "$mesa_pkgver" "$mesa_pkgrel"
printf '    lib32-mesa:    %s-%s\n' "$lib32_pkgver" "$lib32_pkgrel"
printf '    mesa-git:      %s-%s (64-bit + lib32)\n' "$mesa_git_pkgver" "$mesa_git_pkgrel"
