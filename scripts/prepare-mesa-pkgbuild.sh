#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
MESA_PKGREL="${MESA_PKGREL:-${BC250_PKGREL:-1}}"
MESA_BUILD_DIR="${MESA_BUILD_DIR:-${ROOT_DIR}/build/mesa}"
CACHYOS_MESA_COMMIT="${CACHYOS_MESA_COMMIT:-}"
MESA_PATCH="${ROOT_DIR}/patches/mesa/0001-gfx1013-compute-queue-fix.patch"
MESA_MARCH="x86-64-v3"
MESA_MTUNE="znver2"

[[ "$MESA_PKGREL" =~ ^[0-9]+$ ]] || {
    printf 'ERROR: MESA_PKGREL must be numeric: %s\n' "$MESA_PKGREL" >&2
    exit 1
}

for cmd in curl sha256sum b2sum python3 git; do
    command -v "$cmd" >/dev/null 2>&1 || {
        printf 'ERROR: required command not found: %s\n' "$cmd" >&2
        exit 1
    }
done

[[ -f "$MESA_PATCH" ]] || {
    printf 'ERROR: missing Mesa patch: %s\n' "$MESA_PATCH" >&2
    exit 1
}

if [[ -z "$CACHYOS_MESA_COMMIT" ]]; then
    CACHYOS_MESA_COMMIT="$("$ROOT_DIR/scripts/resolve-cachyos-mesa.sh")"
fi
[[ "$CACHYOS_MESA_COMMIT" =~ ^[0-9a-f]{40}$ ]] || {
    printf 'ERROR: invalid CACHYOS_MESA_COMMIT: %s\n' "$CACHYOS_MESA_COMMIT" >&2
    exit 1
}

UPSTREAM_BASE="https://raw.githubusercontent.com/CachyOS/CachyOS-PKGBUILDS/${CACHYOS_MESA_COMMIT}/mesa/mesa"

rm -rf -- "$MESA_BUILD_DIR"
mkdir -p -- "$MESA_BUILD_DIR"

printf '==> Downloading CachyOS Mesa PKGBUILD at %s\n' "$CACHYOS_MESA_COMMIT"
curl -fL --retry 5 --retry-all-errors -o "$MESA_BUILD_DIR/PKGBUILD" "${UPSTREAM_BASE}/PKGBUILD"
curl -fL --retry 5 --retry-all-errors -o "$MESA_BUILD_DIR/gamescope-fps-limiter.patch" \
    "${UPSTREAM_BASE}/gamescope-fps-limiter.patch"

cp -- "$MESA_PATCH" "$MESA_BUILD_DIR/$(basename "$MESA_PATCH")"

PATCH_NAME="$(basename "$MESA_PATCH")"
PATCH_SHA256="$(sha256sum "$MESA_PATCH" | awk '{print $1}')"
PATCH_B2SUM="$(b2sum "$MESA_PATCH" | awk '{print $1}')"

python3 - "$MESA_BUILD_DIR/PKGBUILD" "$MESA_PKGREL" "$PATCH_NAME" "$PATCH_SHA256" "$PATCH_B2SUM" "$MESA_MARCH" "$MESA_MTUNE" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
patch_rel = sys.argv[2]
patch_name = sys.argv[3]
patch_sha256 = sys.argv[4]
patch_b2sum = sys.argv[5]
mesa_march = sys.argv[6]
mesa_mtune = sys.argv[7]
text = path.read_text(encoding="utf-8")

pkgrel_pattern = r'^pkgrel=([0-9]+(?:\.[0-9]+)*)$'
matches = re.findall(pkgrel_pattern, text, flags=re.M)
if len(matches) != 1:
    raise SystemExit('ERROR: expected one numeric pkgrel assignment in Mesa PKGBUILD')

if patch_name in text:
    raise SystemExit(f'ERROR: Mesa PKGBUILD already references {patch_name}')

for token in ('sha256sums=(', 'b2sums=(', 'prepare() {', 'build() {'):
    if text.count(token) != 1:
        raise SystemExit(f'ERROR: expected {token!r} exactly once in Mesa PKGBUILD')

# Keep CachyOS' pkgver and epoch untouched. Appending the workflow run number
# to pkgrel makes this patched build newer than the corresponding upstream
# package without pretending to be a different Mesa release.
text = re.sub(
    pkgrel_pattern,
    lambda m: f'pkgrel={m.group(1)}.{patch_rel}',
    text,
    count=1,
    flags=re.M,
)

# Append the BC-250 patch only after CachyOS has finished constructing its
# dynamic crate source/checksum arrays. prepare() already applies every *.patch
# in source order, so no invasive rewrite of the upstream prepare function is
# required.
inject = f'''# BC-250 / GFX1013 compute-queue support.\nsource+=("{patch_name}")\nsha256sums+=(\'{patch_sha256}\')\nb2sums+=(\'{patch_b2sum}\')\n\n'''
text = text.replace('prepare() {', inject + 'prepare() {', 1)

# Force Mesa's C/C++ compilation target to the BC-250 rather than inheriting
# whatever CPU the CI runner happens to use. Appending the flags makes these
# values take precedence over any earlier -march/-mtune from makepkg.conf while
# preserving the rest of CachyOS/Arch's hardening and optimization flags.
cpu_tuning = (
    f'  # BC-250 CPU target: x86-64-v3 baseline, tuned for Zen 2.\n'
    f'  export CFLAGS="${{CFLAGS:-}} -march={mesa_march} -mtune={mesa_mtune}"\n'
    f'  export CXXFLAGS="${{CXXFLAGS:-}} -march={mesa_march} -mtune={mesa_mtune}"\n\n'
)
text = text.replace('build() {\n', 'build() {\n' + cpu_tuning, 1)

path.write_text(text, encoding="utf-8", newline="\n")
PY

cat > "$MESA_BUILD_DIR/bc250-mesa-build.env" <<EOF_META
CACHYOS_MESA_COMMIT=${CACHYOS_MESA_COMMIT}
CACHYOS_MESA_PKGBUILD_URL=${UPSTREAM_BASE}/PKGBUILD
MESA_PKGREL=${MESA_PKGREL}
MESA_APPLIED_PATCH=${PATCH_NAME}
MESA_MARCH=${MESA_MARCH}
MESA_MTUNE=${MESA_MTUNE}
EOF_META

printf '==> Prepared Mesa build in %s\n' "$MESA_BUILD_DIR"
printf '    CachyOS Mesa commit: %s\n' "$CACHYOS_MESA_COMMIT"
printf '    applied patch:       %s\n' "$PATCH_NAME"
printf '    pkgrel suffix:       %s\n' "$MESA_PKGREL"
printf '    Mesa CPU target:     -march=%s -mtune=%s\n' "$MESA_MARCH" "$MESA_MTUNE"
