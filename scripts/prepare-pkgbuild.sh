#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CACHYOS_VARIANT="${CACHYOS_VARIANT:-linux-cachyos-rc}"
BC250_PKGREL="${BC250_PKGREL:-1}"
BUILD_DIR="${BUILD_DIR:-${ROOT_DIR}/build/${CACHYOS_VARIANT}}"

case "$CACHYOS_VARIANT" in
    linux-cachyos)
        CUSTOM_SUFFIX="${CUSTOM_SUFFIX:-cachyos-bc250}"
        CHANNEL="stable"
        REPO_NAME="bc250-cachyos-v3"
        RELEASE_TAG="repo-stable"
        ;;
    linux-cachyos-rc)
        CUSTOM_SUFFIX="${CUSTOM_SUFFIX:-cachyos-rc-bc250}"
        CHANNEL="rc"
        REPO_NAME="bc250-cachyos-v3-rc"
        RELEASE_TAG="repo-rc"
        ;;
    *)
        printf 'ERROR: unsupported CACHYOS_VARIANT: %s\n' "$CACHYOS_VARIANT" >&2
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

for cmd in curl b2sum python3; do
    command -v "$cmd" >/dev/null 2>&1 || {
        printf 'ERROR: required command not found: %s\n' "$cmd" >&2
        exit 1
    }
done

UPSTREAM_BASE="https://raw.githubusercontent.com/CachyOS/linux-cachyos/master/${CACHYOS_VARIANT}"
TELEMETRY_PATCH="${ROOT_DIR}/patches/0001-bc250-8core-telemetry-gpu-activity.patch"
AUDIO_PATCH="${ROOT_DIR}/patches/0002-bc250-audio.patch"

for file in "$TELEMETRY_PATCH" "$AUDIO_PATCH"; do
    [[ -f "$file" ]] || {
        printf 'ERROR: missing patch: %s\n' "$file" >&2
        exit 1
    }
done

rm -rf -- "$BUILD_DIR"
mkdir -p -- "$BUILD_DIR"

printf '==> Downloading upstream %s PKGBUILD and config\n' "$CACHYOS_VARIANT"
curl -fL --retry 5 --retry-all-errors -o "$BUILD_DIR/PKGBUILD" "${UPSTREAM_BASE}/PKGBUILD"
curl -fL --retry 5 --retry-all-errors -o "$BUILD_DIR/config"   "${UPSTREAM_BASE}/config"

cp -- "$TELEMETRY_PATCH" "$BUILD_DIR/$(basename "$TELEMETRY_PATCH")"
cp -- "$AUDIO_PATCH"     "$BUILD_DIR/$(basename "$AUDIO_PATCH")"

TELEMETRY_NAME="$(basename "$TELEMETRY_PATCH")"
AUDIO_NAME="$(basename "$AUDIO_PATCH")"
TELEMETRY_B2SUM="$(b2sum "$TELEMETRY_PATCH" | awk '{print $1}')"
AUDIO_B2SUM="$(b2sum "$AUDIO_PATCH" | awk '{print $1}')"

python3 - "$BUILD_DIR/PKGBUILD" "$CUSTOM_SUFFIX" "$BC250_PKGREL" \
    "$TELEMETRY_NAME" "$TELEMETRY_B2SUM" "$AUDIO_NAME" "$AUDIO_B2SUM" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
custom_suffix = sys.argv[2]
patch_rel = sys.argv[3]
telemetry_name, telemetry_sum = sys.argv[4], sys.argv[5]
audio_name, audio_sum = sys.argv[6], sys.argv[7]
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
text = text.replace(
    'source=(\n',
    f'source=(\n  "{telemetry_name}"\n  "{audio_name}"\n',
    1,
)
text = text.replace(
    'b2sums=(',
    f"b2sums=('{telemetry_sum}'\n         '{audio_sum}'\n         ",
    1,
)

path.write_text(text, encoding="utf-8", newline="\n")
PY

cat > "$BUILD_DIR/bc250-build.env" <<EOF_META
CACHYOS_VARIANT=${CACHYOS_VARIANT}
CUSTOM_SUFFIX=${CUSTOM_SUFFIX}
CHANNEL=${CHANNEL}
REPO_NAME=${REPO_NAME}
RELEASE_TAG=${RELEASE_TAG}
ARCH_LEVEL=x86-64-v3
BC250_PKGREL=${BC250_PKGREL}
EOF_META

printf '==> Prepared %s\n' "$BUILD_DIR"
printf '    variant:       %s\n' "$CACHYOS_VARIANT"
printf '    package base:  linux-%s\n' "$CUSTOM_SUFFIX"
printf '    target:        x86-64-v3 (generic_v3)\n'
printf '    repository:    %s\n' "$REPO_NAME"
printf '    release tag:   %s\n' "$RELEASE_TAG"
