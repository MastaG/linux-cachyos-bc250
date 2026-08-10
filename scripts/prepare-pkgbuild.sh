#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CACHYOS_SOURCE_VARIANT="${CACHYOS_SOURCE_VARIANT:-linux-cachyos-rc}"
BC250_PKGREL="${BC250_PKGREL:-1}"
CUSTOM_SUFFIX="${CUSTOM_SUFFIX:-cachyos-bc250}"
BUILD_DIR="${BUILD_DIR:-${ROOT_DIR}/build/${CACHYOS_SOURCE_VARIANT}}"
NCT6687D_COMMIT="${NCT6687D_COMMIT:-}"
REPO_NAME="bc250-cachyos"
RELEASE_TAG="repo"
OUT_CHANNEL="repo"
PROCESSOR_OPT="generic_v3"
CPU_TUNE="znver2"

case "$CACHYOS_SOURCE_VARIANT" in
    linux-cachyos|linux-cachyos-rc) ;;
    *)
        printf 'ERROR: unsupported CACHYOS_SOURCE_VARIANT: %s\n' "$CACHYOS_SOURCE_VARIANT" >&2
        exit 1
        ;;
esac

[[ "$CUSTOM_SUFFIX" =~ ^[A-Za-z0-9._+-]+$ ]] || {
    printf 'ERROR: invalid CUSTOM_SUFFIX: %s\n' "$CUSTOM_SUFFIX" >&2
    exit 1
}
[[ "$BC250_PKGREL" =~ ^[0-9]+$ ]] || {
    printf 'ERROR: BC250_PKGREL must be numeric: %s\n' "$BC250_PKGREL" >&2
    exit 1
}

for cmd in curl b2sum python3 git; do
    command -v "$cmd" >/dev/null 2>&1 || {
        printf 'ERROR: required command not found: %s\n' "$cmd" >&2
        exit 1
    }
done

if [[ -z "$NCT6687D_COMMIT" ]]; then
    NCT6687D_COMMIT="$("$ROOT_DIR/scripts/resolve-nct6687d.sh")"
fi
[[ "$NCT6687D_COMMIT" =~ ^[0-9a-f]{40}$ ]] || {
    printf 'ERROR: invalid NCT6687D_COMMIT: %s\n' "$NCT6687D_COMMIT" >&2
    exit 1
}

UPSTREAM_BASE="https://raw.githubusercontent.com/CachyOS/linux-cachyos/master/${CACHYOS_SOURCE_VARIANT}"
NCT6687D_SOURCE_URL="https://raw.githubusercontent.com/Fred78290/nct6687d/${NCT6687D_COMMIT}/nct6687.c"
TELEMETRY_PATCH="${ROOT_DIR}/patches/0001-bc250-8core-telemetry-gpu-activity.patch"
NCT6687D_PATCH="${ROOT_DIR}/patches/0003-nct6687d-hwmon.patch"
GFX1013_PASID_TLB_PATCH="${ROOT_DIR}/patches/0004-gfx1013-pasid-tlb-invalidation.patch"
GFX1013_GFXOFF_GUARD_PATCH="${ROOT_DIR}/patches/0005-gfx1013-compute-gfxoff-guard.patch"

for file in "$TELEMETRY_PATCH" "$NCT6687D_PATCH" \
    "$GFX1013_PASID_TLB_PATCH" "$GFX1013_GFXOFF_GUARD_PATCH"; do
    [[ -f "$file" ]] || {
        printf 'ERROR: missing patch: %s\n' "$file" >&2
        exit 1
    }
done

rm -rf -- "$BUILD_DIR"
mkdir -p -- "$BUILD_DIR"

printf '==> Downloading upstream %s PKGBUILD and config\n' "$CACHYOS_SOURCE_VARIANT"
curl -fL --retry 5 --retry-all-errors -o "$BUILD_DIR/PKGBUILD" "${UPSTREAM_BASE}/PKGBUILD"
curl -fL --retry 5 --retry-all-errors -o "$BUILD_DIR/config"   "${UPSTREAM_BASE}/config"

printf '==> Downloading nct6687d source at %s\n' "$NCT6687D_COMMIT"
curl -fL --retry 5 --retry-all-errors -o "$BUILD_DIR/nct6687.c" "$NCT6687D_SOURCE_URL"

cp -- "$TELEMETRY_PATCH"              "$BUILD_DIR/$(basename "$TELEMETRY_PATCH")"
cp -- "$NCT6687D_PATCH"               "$BUILD_DIR/$(basename "$NCT6687D_PATCH")"
cp -- "$GFX1013_PASID_TLB_PATCH"      "$BUILD_DIR/$(basename "$GFX1013_PASID_TLB_PATCH")"
cp -- "$GFX1013_GFXOFF_GUARD_PATCH"   "$BUILD_DIR/$(basename "$GFX1013_GFXOFF_GUARD_PATCH")"

TELEMETRY_NAME="$(basename "$TELEMETRY_PATCH")"
NCT6687D_PATCH_NAME="$(basename "$NCT6687D_PATCH")"
GFX1013_PASID_TLB_NAME="$(basename "$GFX1013_PASID_TLB_PATCH")"
GFX1013_GFXOFF_GUARD_NAME="$(basename "$GFX1013_GFXOFF_GUARD_PATCH")"
NCT6687D_SOURCE_NAME="nct6687.c"
TELEMETRY_B2SUM="$(b2sum "$TELEMETRY_PATCH" | awk '{print $1}')"
NCT6687D_PATCH_B2SUM="$(b2sum "$NCT6687D_PATCH" | awk '{print $1}')"
GFX1013_PASID_TLB_B2SUM="$(b2sum "$GFX1013_PASID_TLB_PATCH" | awk '{print $1}')"
GFX1013_GFXOFF_GUARD_B2SUM="$(b2sum "$GFX1013_GFXOFF_GUARD_PATCH" | awk '{print $1}')"
NCT6687D_SOURCE_B2SUM="$(b2sum "$BUILD_DIR/nct6687.c" | awk '{print $1}')"

python3 - "$BUILD_DIR/PKGBUILD" "$CUSTOM_SUFFIX" "$BC250_PKGREL" \
    "$TELEMETRY_NAME" "$TELEMETRY_B2SUM" \
    "$NCT6687D_PATCH_NAME" "$NCT6687D_PATCH_B2SUM" \
    "$GFX1013_PASID_TLB_NAME" "$GFX1013_PASID_TLB_B2SUM" \
    "$GFX1013_GFXOFF_GUARD_NAME" "$GFX1013_GFXOFF_GUARD_B2SUM" \
    "$NCT6687D_SOURCE_NAME" "$NCT6687D_SOURCE_B2SUM" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
custom_suffix = sys.argv[2]
patch_rel = sys.argv[3]
extra_sources = list(zip(sys.argv[4::2], sys.argv[5::2]))
text = path.read_text(encoding="utf-8")

pkgbase_pattern = r'^pkgbase="linux-\$_pkgsuffix"$'
if len(re.findall(pkgbase_pattern, text, flags=re.M)) != 1:
    raise SystemExit('ERROR: expected pkgbase="linux-$_pkgsuffix" exactly once')

pkgrel_pattern = r'^pkgrel=([0-9]+(?:\.[0-9]+)*)$'
matches = re.findall(pkgrel_pattern, text, flags=re.M)
if len(matches) != 1:
    raise SystemExit('ERROR: expected one numeric pkgrel assignment')

if text.count('source=(\n') != 1:
    raise SystemExit('ERROR: expected source=( exactly once')
if text.count('b2sums=(') != 1:
    raise SystemExit('ERROR: expected b2sums=( exactly once')

# Keep the package name stable regardless of whether the source is the RC or
# stable CachyOS PKGBUILD.
text = re.sub(
    pkgbase_pattern,
    f'_pkgsuffix="{custom_suffix}"\npkgbase="linux-$_pkgsuffix"',
    text,
    count=1,
    flags=re.M,
)
text = re.sub(
    pkgrel_pattern,
    lambda m: f'pkgrel={m.group(1)}.{patch_rel}',
    text,
    count=1,
    flags=re.M,
)

source_lines = ''.join(f'  "{name}"\n' for name, _ in extra_sources)
sum_lines = ''.join(f"'{checksum}'\n         " for _, checksum in extra_sources)
text = text.replace('source=(\n', f'source=(\n{source_lines}', 1)
text = text.replace('b2sums=(', f'b2sums=({sum_lines}', 1)

# nct6687.c is fetched independently from the external driver repository. The
# small kernel patch adds its Kconfig and Makefile entries; copy the pinned
# source into the kernel tree after all patches have been applied.
prepare_anchor = '    done\n\n    echo "Setting config..."\n'
prepare_replacement = '''    done

    echo "Installing pinned nct6687 hwmon source..."
    install -Dm644 ../nct6687.c drivers/hwmon/nct6687.c

    echo "Setting config..."
'''
if text.count(prepare_anchor) != 1:
    raise SystemExit('ERROR: expected prepare() patch-loop anchor exactly once')
text = text.replace(prepare_anchor, prepare_replacement, 1)

# The upstream nct6683 module claims the same NCT6683/6686/6687 Super-I/O IDs.
# Build only the extended nct6687 implementation in this BC-250 kernel.
config_anchor = '    cp ../config .config\n'
config_replacement = '''    cp ../config .config
    echo "Selecting the extended nct6687 hwmon module..."
    scripts/config -d SENSORS_NCT6683 -m SENSORS_NCT6687
'''
if text.count(config_anchor) != 1:
    raise SystemExit('ERROR: expected config copy anchor exactly once')
text = text.replace(config_anchor, config_replacement, 1)

path.write_text(text, encoding="utf-8", newline="\n")
PY

cat > "$BUILD_DIR/bc250-build.env" <<EOF_META
CACHYOS_SOURCE_VARIANT=${CACHYOS_SOURCE_VARIANT}
CUSTOM_SUFFIX=${CUSTOM_SUFFIX}
REPO_NAME=${REPO_NAME}
RELEASE_TAG=${RELEASE_TAG}
OUT_CHANNEL=${OUT_CHANNEL}
PROCESSOR_OPT=${PROCESSOR_OPT}
CPU_TUNE=${CPU_TUNE}
BC250_PKGREL=${BC250_PKGREL}
NCT6687D_COMMIT=${NCT6687D_COMMIT}
NCT6687D_SOURCE_URL=${NCT6687D_SOURCE_URL}
EOF_META

printf '==> Prepared %s\n' "$BUILD_DIR"
printf '    source:        %s\n' "$CACHYOS_SOURCE_VARIANT"
printf '    package base:  linux-%s\n' "$CUSTOM_SUFFIX"
printf '    ISA baseline:  x86-64-v3 (%s)\n' "$PROCESSOR_OPT"
printf '    CPU tuning:    %s (-mtune=%s)\n' "$CPU_TUNE" "$CPU_TUNE"
printf '    nct6687d:       %s\n' "$NCT6687D_COMMIT"
printf '    repository:    %s\n' "$REPO_NAME"
printf '    release tag:   %s\n' "$RELEASE_TAG"
