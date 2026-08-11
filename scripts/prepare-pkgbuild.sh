#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CACHYOS_SOURCE_VARIANT="${CACHYOS_SOURCE_VARIANT:-linux-cachyos}"
BC250_PKGREL="${BC250_PKGREL:-1}"
BUILD_DIR="${BUILD_DIR:-${ROOT_DIR}/build/${CACHYOS_SOURCE_VARIANT}}"
NCT6687D_COMMIT="${NCT6687D_COMMIT:-}"
REPO_NAME="bc250-cachyos"
RELEASE_TAG="repo"
OUT_CHANNEL="repo"
PROCESSOR_OPT="generic_v3"
CPU_TUNE="znver2"

case "$CACHYOS_SOURCE_VARIANT" in
    linux-cachyos)
        KERNEL_ID="stable"
        CUSTOM_SUFFIX="cachyos-bc250"
        EXPECTED_PKGBASE="linux-cachyos-bc250"
        PATCH_SET="kernel-7.1"
        ;;
    linux-cachyos-rc)
        KERNEL_ID="rc"
        CUSTOM_SUFFIX="cachyos-rc-bc250"
        EXPECTED_PKGBASE="linux-cachyos-rc-bc250"
        PATCH_SET="kernel-7.2"
        ;;
    linux-cachyos-bore)
        KERNEL_ID="bore"
        CUSTOM_SUFFIX="cachyos-bore-bc250"
        EXPECTED_PKGBASE="linux-cachyos-bore-bc250"
        PATCH_SET="kernel-7.1"
        ;;
    *)
        printf 'ERROR: unsupported CACHYOS_SOURCE_VARIANT: %s\n' "$CACHYOS_SOURCE_VARIANT" >&2
        exit 1
        ;;
esac

PATCH_DIR="${ROOT_DIR}/patches/${PATCH_SET}"
[[ -d "$PATCH_DIR" ]] || {
    printf 'ERROR: missing kernel patch set: %s\n' "$PATCH_DIR" >&2
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

mapfile -t KERNEL_PATCHES < <(find "$PATCH_DIR" -maxdepth 1 -type f -name '*.patch' -print | sort)
(( ${#KERNEL_PATCHES[@]} > 0 )) || {
    printf 'ERROR: no kernel patches found in %s\n' "$PATCH_DIR" >&2
    exit 1
}

if [[ "$PATCH_SET" == kernel-7.1 ]]; then
    [[ -f "$PATCH_DIR/0002-bc250-audio.patch" ]] || {
        printf 'ERROR: %s must contain the BC-250 audio patch\n' "$PATCH_SET" >&2
        exit 1
    }
else
    [[ ! -f "$PATCH_DIR/0002-bc250-audio.patch" ]] || {
        printf 'ERROR: %s must not contain the audio patch because it is upstream there\n' "$PATCH_SET" >&2
        exit 1
    }
fi

UPSTREAM_BASE="https://raw.githubusercontent.com/CachyOS/linux-cachyos/master/${CACHYOS_SOURCE_VARIANT}"
NCT6687D_SOURCE_URL="https://raw.githubusercontent.com/Fred78290/nct6687d/${NCT6687D_COMMIT}/nct6687.c"

rm -rf -- "$BUILD_DIR"
mkdir -p -- "$BUILD_DIR"

printf '==> Downloading upstream %s PKGBUILD and config\n' "$CACHYOS_SOURCE_VARIANT"
curl -fL --retry 5 --retry-all-errors -o "$BUILD_DIR/PKGBUILD" "${UPSTREAM_BASE}/PKGBUILD"
curl -fL --retry 5 --retry-all-errors -o "$BUILD_DIR/config"   "${UPSTREAM_BASE}/config"

printf '==> Downloading nct6687d source at %s\n' "$NCT6687D_COMMIT"
curl -fL --retry 5 --retry-all-errors -o "$BUILD_DIR/nct6687.c" "$NCT6687D_SOURCE_URL"

extra_args=()
for patch in "${KERNEL_PATCHES[@]}"; do
    name="$(basename "$patch")"
    cp -- "$patch" "$BUILD_DIR/$name"
    extra_args+=("$name" "$(b2sum "$patch" | awk '{print $1}')")
done
extra_args+=("nct6687.c" "$(b2sum "$BUILD_DIR/nct6687.c" | awk '{print $1}')")

python3 - "$BUILD_DIR/PKGBUILD" "$CUSTOM_SUFFIX" "$BC250_PKGREL" "${extra_args[@]}" <<'PY'
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

# Give each upstream kernel its own co-installable BC-250 package name.
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

# nct6687.c is fetched independently. The BC-250 patch adds its Kconfig and
# Makefile entries; install the pinned source after the patch loop.
prepare_anchor = '    done\n\n    echo "Setting config..."\n'
prepare_replacement = '''    done

    echo "Installing pinned nct6687 hwmon source..."
    install -Dm644 ../nct6687.c drivers/hwmon/nct6687.c

    echo "Setting config..."
'''
if text.count(prepare_anchor) != 1:
    raise SystemExit('ERROR: expected prepare() patch-loop anchor exactly once')
text = text.replace(prepare_anchor, prepare_replacement, 1)

# The upstream nct6683 driver claims the same Super-I/O IDs. Build only the
# extended nct6687 implementation in the BC-250 kernels.
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
KERNEL_ID=${KERNEL_ID}
CACHYOS_SOURCE_VARIANT=${CACHYOS_SOURCE_VARIANT}
CUSTOM_SUFFIX=${CUSTOM_SUFFIX}
EXPECTED_PKGBASE=${EXPECTED_PKGBASE}
PATCH_SET=${PATCH_SET}
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
printf '    kernel:        %s\n' "$KERNEL_ID"
printf '    source:        %s\n' "$CACHYOS_SOURCE_VARIANT"
printf '    package base:  %s\n' "$EXPECTED_PKGBASE"
printf '    patch set:     %s\n' "$PATCH_SET"
printf '    ISA baseline:  x86-64-v3 (%s)\n' "$PROCESSOR_OPT"
printf '    CPU tuning:    %s (-mtune=%s)\n' "$CPU_TUNE" "$CPU_TUNE"
printf '    nct6687d:       %s\n' "$NCT6687D_COMMIT"
