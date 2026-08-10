#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${ROOT_DIR}/out/repo"
REPO_NAME="bc250-cachyos"

: "${KERNEL_FINGERPRINT:?KERNEL_FINGERPRINT is required}"
: "${MESA_FINGERPRINT:?MESA_FINGERPRINT is required}"
: "${LIB32_MESA_FINGERPRINT:?LIB32_MESA_FINGERPRINT is required}"
: "${MESA_GIT_FINGERPRINT:?MESA_GIT_FINGERPRINT is required}"

BUILD_KERNEL="${BUILD_KERNEL:-false}"
BUILD_MESA="${BUILD_MESA:-false}"
BUILD_LIB32_MESA="${BUILD_LIB32_MESA:-false}"
BUILD_MESA_GIT="${BUILD_MESA_GIT:-false}"
KERNEL_GUARD_REASON="${KERNEL_GUARD_REASON:-none}"

for file in kernel-info.env mesa-info.env lib32-mesa-info.env mesa-git-info.env; do
    [[ -f "$OUT_DIR/$file" ]] || {
        printf 'ERROR: missing component metadata: %s\n' "$OUT_DIR/$file" >&2
        exit 1
    }
done

value() {
    local file="$1" key="$2"
    sed -n "s/^${key}=//p" "$file" | head -n1
}

kernel_info="$OUT_DIR/kernel-info.env"
mesa_info="$OUT_DIR/mesa-info.env"
lib32_info="$OUT_DIR/lib32-mesa-info.env"
mesa_git_info="$OUT_DIR/mesa-git-info.env"

kernel_pkgbase="$(value "$kernel_info" KERNEL_PKGBASE)"
kernel_pkgver="$(value "$kernel_info" KERNEL_PKGVER)"
kernel_pkgrel="$(value "$kernel_info" KERNEL_PKGREL)"
kernel_source="$(value "$kernel_info" CACHYOS_SOURCE_VARIANT)"
processor_opt="$(value "$kernel_info" PROCESSOR_OPT)"
cpu_tune="$(value "$kernel_info" CPU_TUNE)"
nct_commit="$(value "$kernel_info" NCT6687D_COMMIT)"

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

for field in kernel_pkgbase kernel_pkgver kernel_pkgrel mesa_pkgver mesa_pkgrel lib32_pkgver lib32_pkgrel mesa_git_commit mesa_git_pkgver mesa_git_pkgrel mesa_git_lib32; do
    [[ -n "${!field}" ]] || {
        printf 'ERROR: missing metadata field %s\n' "$field" >&2
        exit 1
    }
done

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

kernel_count="$(pkgbase_count "$kernel_pkgbase")"
mesa_count="$(pkgbase_count mesa)"
lib32_count="$(pkgbase_count lib32-mesa)"
mesa_git_count="$(pkgbase_count mesa-git)"

(( kernel_count >= 2 )) || { printf 'ERROR: expected kernel + headers for pkgbase %s; found %d package(s)\n' "$kernel_pkgbase" "$kernel_count" >&2; exit 1; }
(( mesa_count >= 1 )) || { printf 'ERROR: stable Mesa packages are missing from the staged repository\n' >&2; exit 1; }
(( lib32_count >= 1 )) || { printf 'ERROR: lib32-mesa packages are missing from the staged repository\n' >&2; exit 1; }
(( mesa_git_count == 2 )) || { printf 'ERROR: expected mesa-git + lib32-mesa-git; found %d package(s)\n' "$mesa_git_count" >&2; exit 1; }

rm -f -- "${REPO_NAME}.db" "${REPO_NAME}.db.tar.zst" \
          "${REPO_NAME}.files" "${REPO_NAME}.files.tar.zst"
repo-add "${REPO_NAME}.db.tar.zst" "${packages[@]}"
cp -L --remove-destination "${REPO_NAME}.db.tar.zst" "${REPO_NAME}.db"
cp -L --remove-destination "${REPO_NAME}.files.tar.zst" "${REPO_NAME}.files"

SOURCE_FINGERPRINT="$(printf '%s\n' \
    "$KERNEL_FINGERPRINT" "$MESA_FINGERPRINT" \
    "$LIB32_MESA_FINGERPRINT" "$MESA_GIT_FINGERPRINT" | sha256sum | awk '{print $1}')"

cat > build-info.env <<EOF_INFO
SOURCE_FINGERPRINT=${SOURCE_FINGERPRINT}
KERNEL_FINGERPRINT=${KERNEL_FINGERPRINT}
MESA_FINGERPRINT=${MESA_FINGERPRINT}
LIB32_MESA_FINGERPRINT=${LIB32_MESA_FINGERPRINT}
MESA_GIT_FINGERPRINT=${MESA_GIT_FINGERPRINT}
LAST_RUN_KERNEL_BUILD=${BUILD_KERNEL}
LAST_RUN_MESA_BUILD=${BUILD_MESA}
LAST_RUN_LIB32_MESA_BUILD=${BUILD_LIB32_MESA}
LAST_RUN_MESA_GIT_BUILD=${BUILD_MESA_GIT}
KERNEL_GUARD_REASON=${KERNEL_GUARD_REASON}
CACHYOS_SOURCE_VARIANT=${kernel_source}
KERNEL_PKGBASE=${kernel_pkgbase}
KERNEL_PKGVER=${kernel_pkgver}
KERNEL_PKGREL=${kernel_pkgrel}
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
# BC-250 CachyOS kernel + Mesa repository

## BC-250 CachyOS kernel

- Upstream source package: \`${kernel_source}\`
- Published package: \`${kernel_pkgbase}\`
- Version: \`${kernel_pkgver}-${kernel_pkgrel}\`
- ISA baseline: **x86-64-v3** (CachyOS \`${processor_opt}\`)
- CPU tuning: **Zen 2** (\`KCFLAGS=-mtune=${cpu_tune}\`)
- Extra hwmon module: \`nct6687.ko\` from Fred78290/nct6687d commit \`${nct_commit}\`
- GFX1013 kernel fixes: merged PASID TLB invalidation handling (MMIO routing + scoped type-0 path) and compute GFXOFF guard

## Patched stable CachyOS Mesa

- CachyOS packaging commit: \`${mesa_cachyos_commit}\`
- Version: \`${mesa_pkgver}-${mesa_pkgrel}\`${mesa_epoch:+ (epoch ${mesa_epoch})}
- Applied patch: \`0001-gfx1013-compute-queue-fix.patch\`
- CPU target: \`-march=x86-64-v3 -mtune=znver2\`
- \`0002-gfx1013-mesh-task-shaders.patch\` and \`0003-gfx1013-taskmesh-queries.patch\` remain disabled.

## Patched stable CachyOS lib32-mesa

- CachyOS packaging commit: \`${lib32_cachyos_commit}\`
- Version: \`${lib32_pkgver}-${lib32_pkgrel}\`${lib32_epoch:+ (epoch ${lib32_epoch})}
- Uses the same Mesa release and active GFX1013 compute-queue patch as the 64-bit stable Mesa build.
- CPU target: \`-march=x86-64-v3 -mtune=znver2\`

## Patched CachyOS mesa-git

- CachyOS packaging commit: \`${mesa_git_cachyos_commit}\`
- Mesa main commit: \`${mesa_git_commit}\`
- Package version: \`${mesa_git_pkgver}-${mesa_git_pkgrel}\`
- Applied Git-rebased patch: \`mesa-git-0001-gfx1013-compute-queue-fix.patch\`
- CPU target: \`-march=x86-64-v3 -mtune=znver2\`
- The GFX1013 IP-minor correction from the stable patch is already upstream in current Mesa main and is therefore omitted from the Git patch.
- The rebased mesh/task patches are published as assets but remain disabled because they can hard-hang GFX1013.
- Upstream CachyOS \`customization.cfg\` keeps \`_lib32=true\`, so the same build publishes both \`mesa-git\` and \`lib32-mesa-git\` from the same Mesa commit.
- \`mesa-git\`/\`lib32-mesa-git\` are optional alternatives to the stable Mesa packages; they are not installed automatically.
EOF_NOTES

if [[ "$KERNEL_GUARD_REASON" != none ]]; then
    cat >> RELEASE_NOTES.md <<EOF_GUARD

> **Kernel build paused:** ${KERNEL_GUARD_REASON}. The last published BC-250 kernel and headers were retained while Mesa packages can continue updating.
EOF_GUARD
fi

printf '%s — %s-%s' "$kernel_pkgbase" "$kernel_pkgver" "$kernel_pkgrel" > release-title.txt

rm -f -- SHA256SUMS
while IFS= read -r -d '' file; do
    sha256sum "${file#./}"
done < <(find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 | sort -z) > SHA256SUMS

printf '==> Final repository contains %d packages\n' "${#packages[@]}"
printf '    kernel:     %s-%s\n' "$kernel_pkgver" "$kernel_pkgrel"
printf '    mesa:       %s-%s\n' "$mesa_pkgver" "$mesa_pkgrel"
printf '    lib32-mesa: %s-%s\n' "$lib32_pkgver" "$lib32_pkgrel"
printf '    mesa-git:   %s-%s (64-bit + lib32)\n' "$mesa_git_pkgver" "$mesa_git_pkgrel"
