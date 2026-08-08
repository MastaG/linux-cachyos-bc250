#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
MESA_BUILD_DIR="${MESA_BUILD_DIR:-${ROOT_DIR}/build/mesa}"
OUT_DIR="${ROOT_DIR}/out/repo"
REPO_NAME="bc250-cachyos"
BUILD_KERNEL="${BUILD_KERNEL:-true}"
KERNEL_GUARD_REASON="${KERNEL_GUARD_REASON:-none}"

: "${SOURCE_FINGERPRINT:?SOURCE_FINGERPRINT is required}"

case "$BUILD_KERNEL" in
    true|false) ;;
    *) printf 'ERROR: BUILD_KERNEL must be true or false: %s\n' "$BUILD_KERNEL" >&2; exit 1 ;;
esac

"${ROOT_DIR}/scripts/prepare-mesa-pkgbuild.sh"
# shellcheck disable=SC1091
source "$MESA_BUILD_DIR/bc250-mesa-build.env"

cd -- "$MESA_BUILD_DIR"
export MAKEFLAGS="${MAKEFLAGS:--j$(nproc)}"

# Use CachyOS' Mesa PKGBUILD with only the BC-250-specific pkgrel, CPU target,
# and compute-queue patch injected by prepare-mesa-pkgbuild.sh. The optional
# mesh/task patches are intentionally not present in source= and therefore are
# not applied or built.
makepkg --syncdeps --noconfirm --cleanbuild --clean --skippgpcheck
makepkg --printsrcinfo > .SRCINFO

shopt -s nullglob
mesa_packages=("$MESA_BUILD_DIR"/*.pkg.tar.zst)
(( ${#mesa_packages[@]} > 0 )) || {
    printf 'ERROR: Mesa makepkg produced no .pkg.tar.zst files\n' >&2
    exit 1
}

mkdir -p -- "$OUT_DIR"

# In Mesa-only mode OUT_DIR is seeded from the previous fixed release so the
# last known-good 7.2 kernel stays available. Remove every package from the
# previous Mesa pkgbase before copying the newly built split packages.
for existing_package in "$OUT_DIR"/*.pkg.tar.zst; do
    [[ -e "$existing_package" ]] || continue
    existing_pkgbase="$(
        bsdtar -xOf "$existing_package" .PKGINFO 2>/dev/null |
            awk -F ' = ' '$1 == "pkgbase" { print $2; exit }'
    )"
    if [[ "$existing_pkgbase" == mesa ]]; then
        printf '==> Removing previous Mesa package: %s\n' "$(basename -- "$existing_package")"
        rm -f -- "$existing_package"
    fi
done

cp -- "${mesa_packages[@]}" "$OUT_DIR/"

# Pacman/makepkg may include the package epoch in the archive filename, e.g.
# mesa-3:26.1.6-1.10-x86_64.pkg.tar.zst. The epoch must remain in the
# package metadata for version comparison, but ':' is unsuitable for GitHub
# Actions artifacts and GitHub Releases may sanitize special asset names.
# Normalize only the repository filename before the final repo-add; .PKGINFO
# inside the package remains untouched.
normalize_repo_package_filenames() {
    local package pkginfo package_name package_version package_arch
    local filename_version target

    shopt -s nullglob
    for package in "$OUT_DIR"/*.pkg.tar.zst; do
        [[ "$(basename -- "$package")" == *:* ]] || continue

        pkginfo="$(bsdtar -xOf "$package" .PKGINFO)"
        package_name="$(awk -F ' = ' '$1 == "pkgname" { print $2; exit }' <<<"$pkginfo")"
        package_version="$(awk -F ' = ' '$1 == "pkgver" { print $2; exit }' <<<"$pkginfo")"
        package_arch="$(awk -F ' = ' '$1 == "arch" { print $2; exit }' <<<"$pkginfo")"

        if [[ -z "$package_name" || -z "$package_version" || -z "$package_arch" ]]; then
            printf 'ERROR: could not read package metadata from %s\n' "$package" >&2
            exit 1
        fi

        filename_version="${package_version#*:}"
        target="$OUT_DIR/${package_name}-${filename_version}-${package_arch}.pkg.tar.zst"

        if [[ -e "$target" && "$target" != "$package" ]]; then
            printf 'ERROR: normalized package filename already exists: %s\n' "$target" >&2
            exit 1
        fi

        printf '==> Normalizing package filename: %s -> %s\n' \
            "$(basename -- "$package")" "$(basename -- "$target")"
        mv -- "$package" "$target"
    done
}

normalize_repo_package_filenames

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

# Recreate the repository database from every package currently staged in the
# fixed release. In Mesa-only mode this includes the retained 7.2 kernel plus
# the newly built Mesa split packages.
cd -- "$OUT_DIR"
rm -f -- "${REPO_NAME}.db" "${REPO_NAME}.db.tar.zst" \
          "${REPO_NAME}.files" "${REPO_NAME}.files.tar.zst"
repo-add "${REPO_NAME}.db.tar.zst" ./*.pkg.tar.zst
cp -L --remove-destination "${REPO_NAME}.db.tar.zst" "${REPO_NAME}.db"
cp -L --remove-destination "${REPO_NAME}.files.tar.zst" "${REPO_NAME}.files"

if [[ ! -f "$OUT_DIR/build-info.env" ]]; then
    printf 'ERROR: missing kernel build metadata: %s\n' "$OUT_DIR/build-info.env" >&2
    exit 1
fi

# Replace the previous run/Mesa fields instead of appending duplicates when a
# Mesa-only run starts from the previous release.
build_info_tmp="$(mktemp)"
awk -F '=' '
    $1 == "SOURCE_FINGERPRINT" { next }
    $1 == "LAST_RUN_KERNEL_BUILD" { next }
    $1 == "KERNEL_GUARD_REASON" { next }
    $1 == "CACHYOS_MESA_COMMIT" { next }
    $1 == "CACHYOS_MESA_PKGBUILD_URL" { next }
    $1 ~ /^MESA_/ { next }
    { print }
' "$OUT_DIR/build-info.env" > "$build_info_tmp"

{
    printf 'SOURCE_FINGERPRINT=%s\n' "$SOURCE_FINGERPRINT"
    cat "$build_info_tmp"
    printf 'LAST_RUN_KERNEL_BUILD=%s\n' "$BUILD_KERNEL"
    printf 'KERNEL_GUARD_REASON=%s\n' "$KERNEL_GUARD_REASON"
    cat <<EOF_INFO
CACHYOS_MESA_COMMIT=${CACHYOS_MESA_COMMIT}
CACHYOS_MESA_PKGBUILD_URL=${CACHYOS_MESA_PKGBUILD_URL}
MESA_PKGBASE=${mesa_pkgbase}
MESA_EPOCH=${mesa_epoch}
MESA_PKGVER=${mesa_pkgver}
MESA_PKGREL=${mesa_pkgrel}
MESA_APPLIED_PATCH=${MESA_APPLIED_PATCH}
MESA_MARCH=${MESA_MARCH}
MESA_MTUNE=${MESA_MTUNE}
EOF_INFO
} > "$OUT_DIR/build-info.env"
rm -f -- "$build_info_tmp"

if [[ ! -f "$OUT_DIR/RELEASE_NOTES.md" ]]; then
    printf 'ERROR: missing release notes: %s\n' "$OUT_DIR/RELEASE_NOTES.md" >&2
    exit 1
fi

# Mesa is the final section of the generated release notes. Drop an older Mesa
# section when a Mesa-only run reuses the previous release metadata.
release_notes_tmp="$(mktemp)"
awk '/^## Patched CachyOS Mesa$/ { exit } { print }' \
    "$OUT_DIR/RELEASE_NOTES.md" > "$release_notes_tmp"
mv -- "$release_notes_tmp" "$OUT_DIR/RELEASE_NOTES.md"

cat >> "$OUT_DIR/RELEASE_NOTES.md" <<EOF_NOTES

## Patched CachyOS Mesa

- CachyOS PKGBUILD commit: \`${CACHYOS_MESA_COMMIT}\`
- Published Mesa version: \`${mesa_pkgver}-${mesa_pkgrel}\`${mesa_epoch:+ (epoch ${mesa_epoch})}
- Applied Mesa patch: \`0001-gfx1013-compute-queue-fix.patch\`
- Mesa CPU target: \`-march=${MESA_MARCH} -mtune=${MESA_MTUNE}\`
- The rebased \`0002-gfx1013-mesh-task-shaders.patch\` and
  \`0003-gfx1013-taskmesh-queries.patch\` are included as release assets but are
  **not applied** to the packages yet.
- The GFX1013 compute-queue Mesa patch is intended to be used together with
  this repository's GFX1013 kernel compute/PASID fixes.
EOF_NOTES

if [[ "$BUILD_KERNEL" == false ]]; then
    cat >> "$OUT_DIR/RELEASE_NOTES.md" <<EOF_GUARD

> **Kernel build paused:** ${KERNEL_GUARD_REASON}. The previous BC-250 kernel
> and headers were retained in this release while Mesa was rebuilt normally.
EOF_GUARD
fi

# Mesa was added after the kernel build generated its first checksum file.
# Recalculate over the complete fixed-release payload.
rm -f -- SHA256SUMS
while IFS= read -r -d '' file; do
    sha256sum "${file#./}"
done < <(find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 | sort -z) > SHA256SUMS

printf '==> Mesa packages added to %s\n' "$OUT_DIR"
printf '    Mesa: %s-%s\n' "$mesa_pkgver" "$mesa_pkgrel"
printf '    Packages built: %d\n' "${#mesa_packages[@]}"
