#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LIB32_MESA_PKGREL="${LIB32_MESA_PKGREL:-${BC250_PKGREL:-1}}"
LIB32_MESA_BUILD_DIR="${LIB32_MESA_BUILD_DIR:-${ROOT_DIR}/build/lib32-mesa}"
CACHYOS_MESA_COMMIT="${CACHYOS_MESA_COMMIT:-}"
MESA_PATCH_DIR="${ROOT_DIR}/patches/mesa"
MESA_PATCHES=(
    "${MESA_PATCH_DIR}/0001-gfx1013-compute-queue-fix.patch"
    "${MESA_PATCH_DIR}/0002-gfx1013-mesh-task-shaders.patch"
    "${MESA_PATCH_DIR}/0003-gfx1013-taskmesh-queries.patch"
    "${MESA_PATCH_DIR}/0004-radv-gfx103.patch"
)
LIB32_MESA_MARCH="x86-64-v3"
LIB32_MESA_MTUNE="znver2"

[[ "$LIB32_MESA_PKGREL" =~ ^[0-9]+$ ]] || {
    printf 'ERROR: LIB32_MESA_PKGREL must be numeric: %s\n' "$LIB32_MESA_PKGREL" >&2
    exit 1
}

for cmd in curl sha256sum b2sum python3 git; do
    command -v "$cmd" >/dev/null 2>&1 || {
        printf 'ERROR: required command not found: %s\n' "$cmd" >&2
        exit 1
    }
done
for patch in "${MESA_PATCHES[@]}"; do
    [[ -f "$patch" ]] || {
        printf 'ERROR: missing Mesa patch: %s\n' "$patch" >&2
        exit 1
    }
done

if [[ -z "$CACHYOS_MESA_COMMIT" ]]; then
    CACHYOS_MESA_COMMIT="$("$ROOT_DIR/scripts/resolve-cachyos-mesa.sh")"
fi
[[ "$CACHYOS_MESA_COMMIT" =~ ^[0-9a-f]{40}$ ]] || {
    printf 'ERROR: invalid CACHYOS_MESA_COMMIT: %s\n' "$CACHYOS_MESA_COMMIT" >&2
    exit 1
}

UPSTREAM_BASE="https://raw.githubusercontent.com/CachyOS/CachyOS-PKGBUILDS/${CACHYOS_MESA_COMMIT}/mesa/lib32-mesa"
rm -rf -- "$LIB32_MESA_BUILD_DIR"
mkdir -p -- "$LIB32_MESA_BUILD_DIR"

printf '==> Downloading CachyOS lib32-mesa PKGBUILD at %s\n' "$CACHYOS_MESA_COMMIT"
curl -fL --retry 5 --retry-all-errors -o "$LIB32_MESA_BUILD_DIR/PKGBUILD" "${UPSTREAM_BASE}/PKGBUILD"
curl -fL --retry 5 --retry-all-errors -o "$LIB32_MESA_BUILD_DIR/gamescope-fps-limiter.patch" \
    "${UPSTREAM_BASE}/gamescope-fps-limiter.patch"

patch_args=()
patch_names=()
for patch in "${MESA_PATCHES[@]}"; do
    name="$(basename "$patch")"
    sha256="$(sha256sum "$patch" | awk '{print $1}')"
    b2="$(b2sum "$patch" | awk '{print $1}')"
    cp -- "$patch" "$LIB32_MESA_BUILD_DIR/$name"
    patch_names+=("$name")
    patch_args+=("$name" "$sha256" "$b2")
done

python3 - "$LIB32_MESA_BUILD_DIR/PKGBUILD" "$LIB32_MESA_PKGREL" "$LIB32_MESA_MARCH" "$LIB32_MESA_MTUNE" "${patch_args[@]}" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
patch_rel = sys.argv[2]
march = sys.argv[3]
mtune = sys.argv[4]
raw = sys.argv[5:]
if not raw or len(raw) % 3:
    raise SystemExit('ERROR: invalid lib32-mesa patch metadata arguments')
patches = [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]
text = path.read_text(encoding='utf-8')

pkgrel_pattern = r'^pkgrel=([0-9]+(?:\.[0-9]+)*)$'
if len(re.findall(pkgrel_pattern, text, flags=re.M)) != 1:
    raise SystemExit('ERROR: expected one numeric pkgrel assignment in lib32-mesa PKGBUILD')
for token in ('sha256sums=(', 'b2sums=(', 'prepare() {', 'build() {'):
    if text.count(token) != 1:
        raise SystemExit(f'ERROR: expected {token!r} exactly once in lib32-mesa PKGBUILD')
for name, _, _ in patches:
    if name in text:
        raise SystemExit(f'ERROR: lib32-mesa PKGBUILD already references {name}')

text = re.sub(pkgrel_pattern, lambda m: f'pkgrel={m.group(1)}.{patch_rel}', text, count=1, flags=re.M)
names = '\n'.join(f'  "{name}"' for name, _, _ in patches)
sha256s = '\n'.join(f"  '{sha}'" for _, sha, _ in patches)
b2s = '\n'.join(f"  '{b2}'" for _, _, b2 in patches)
inject = (
    '# BC-250 / GFX1013 patch set. 0001 is always active; 0002/0003 are\n'
    '# runtime-gated on GFX1013 by the RADV_GFX103 override added by 0004.\n'
    f'source+=(\n{names}\n)\n'
    f'sha256sums+=(\n{sha256s}\n)\n'
    f'b2sums+=(\n{b2s}\n)\n\n'
)
text = text.replace('prepare() {', inject + 'prepare() {', 1)
cpu_tuning = (
    '  # BC-250 CPU target for 32-bit Mesa: x86-64-v3 ISA features, Zen 2 tuning.\n'
    f'  export CFLAGS="${{CFLAGS:-}} -march={march} -mtune={mtune}"\n'
    f'  export CXXFLAGS="${{CXXFLAGS:-}} -march={march} -mtune={mtune}"\n\n'
)
text = text.replace('build() {\n', 'build() {\n' + cpu_tuning, 1)
path.write_text(text, encoding='utf-8', newline='\n')
PY

applied_patches="$(IFS=,; printf '%s' "${patch_names[*]}")"
cat > "$LIB32_MESA_BUILD_DIR/bc250-lib32-mesa-build.env" <<EOF_META
CACHYOS_MESA_COMMIT=${CACHYOS_MESA_COMMIT}
CACHYOS_LIB32_MESA_PKGBUILD_URL=${UPSTREAM_BASE}/PKGBUILD
LIB32_MESA_PKGREL=${LIB32_MESA_PKGREL}
LIB32_MESA_APPLIED_PATCHES=${applied_patches}
LIB32_MESA_MARCH=${LIB32_MESA_MARCH}
LIB32_MESA_MTUNE=${LIB32_MESA_MTUNE}
EOF_META

printf '==> Prepared lib32-mesa build in %s\n' "$LIB32_MESA_BUILD_DIR"
printf '    CachyOS packaging commit: %s\n' "$CACHYOS_MESA_COMMIT"
printf '    applied patches:          %s\n' "$applied_patches"
printf '    pkgrel suffix:            %s\n' "$LIB32_MESA_PKGREL"
printf '    CPU target:               -march=%s -mtune=%s\n' "$LIB32_MESA_MARCH" "$LIB32_MESA_MTUNE"
