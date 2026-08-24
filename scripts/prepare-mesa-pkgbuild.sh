#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
MESA_PKGREL="${MESA_PKGREL:-${BC250_PKGREL:-1}}"
MESA_BUILD_DIR="${MESA_BUILD_DIR:-${ROOT_DIR}/build/mesa}"
CACHYOS_MESA_COMMIT="${CACHYOS_MESA_COMMIT:-}"
MESA_PATCH_DIR="${ROOT_DIR}/patches/mesa"
MESA_PATCHES=(
    "${MESA_PATCH_DIR}/0001-gfx1013-compute-queue-fix.patch"
    "${MESA_PATCH_DIR}/0002-gfx1013-mesh-task-shaders.patch"
    "${MESA_PATCH_DIR}/0003-gfx1013-taskmesh-queries.patch"
    "${MESA_PATCH_DIR}/0004-radv-gfx103.patch"
    "${MESA_PATCH_DIR}/0005-bc250-fsr4-v3.patch"
)
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

UPSTREAM_BASE="https://raw.githubusercontent.com/CachyOS/CachyOS-PKGBUILDS/${CACHYOS_MESA_COMMIT}/mesa/mesa"

rm -rf -- "$MESA_BUILD_DIR"
mkdir -p -- "$MESA_BUILD_DIR"

printf '==> Downloading CachyOS Mesa PKGBUILD at %s\n' "$CACHYOS_MESA_COMMIT"
curl -fL --retry 5 --retry-all-errors -o "$MESA_BUILD_DIR/PKGBUILD" "${UPSTREAM_BASE}/PKGBUILD"
curl -fL --retry 5 --retry-all-errors -o "$MESA_BUILD_DIR/gamescope-fps-limiter.patch" \
    "${UPSTREAM_BASE}/gamescope-fps-limiter.patch"

patch_args=()
patch_names=()
for patch in "${MESA_PATCHES[@]}"; do
    name="$(basename "$patch")"
    sha256="$(sha256sum "$patch" | awk '{print $1}')"
    b2="$(b2sum "$patch" | awk '{print $1}')"
    cp -- "$patch" "$MESA_BUILD_DIR/$name"
    patch_names+=("$name")
    patch_args+=("$name" "$sha256" "$b2")
done

python3 - "$MESA_BUILD_DIR/PKGBUILD" "$MESA_PKGREL" "$MESA_MARCH" "$MESA_MTUNE" "${patch_args[@]}" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
patch_rel = sys.argv[2]
march = sys.argv[3]
mtune = sys.argv[4]
raw = sys.argv[5:]
if not raw or len(raw) % 3:
    raise SystemExit('ERROR: invalid Mesa patch metadata arguments')
patches = [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]
text = path.read_text(encoding='utf-8')

pkgrel_pattern = r'^pkgrel=([0-9]+(?:\.[0-9]+)*)$'
if len(re.findall(pkgrel_pattern, text, flags=re.M)) != 1:
    raise SystemExit('ERROR: expected one numeric pkgrel assignment in Mesa PKGBUILD')
for token in ('sha256sums=(', 'b2sums=(', 'prepare() {', 'build() {'):
    if text.count(token) != 1:
        raise SystemExit(f'ERROR: expected {token!r} exactly once in Mesa PKGBUILD')
for name, _, _ in patches:
    if name in text:
        raise SystemExit(f'ERROR: Mesa PKGBUILD already references {name}')

text = re.sub(
    pkgrel_pattern,
    lambda m: f'pkgrel={m.group(1)}.{patch_rel}',
    text,
    count=1,
    flags=re.M,
)

names = '\n'.join(f'  "{name}"' for name, _, _ in patches)
sha256s = '\n'.join(f"  '{sha}'" for _, sha, _ in patches)
b2s = '\n'.join(f"  '{b2}'" for _, _, b2 in patches)
inject = (
    '# BC-250 / GFX1013 patch set. 0001 and 0005 are always active; 0002/0003\n'
    '# are runtime-gated on GFX1013 by the RADV_GFX103 override added by 0004.\n'
    f'source+=(\n{names}\n)\n'
    f'sha256sums+=(\n{sha256s}\n)\n'
    f'b2sums+=(\n{b2s}\n)\n\n'
)
text = text.replace('prepare() {', inject + 'prepare() {', 1)

cpu_tuning = (
    '  # BC-250 CPU target: x86-64-v3 baseline, tuned for Zen 2.\n'
    f'  export CFLAGS="${{CFLAGS:-}} -march={march} -mtune={mtune}"\n'
    f'  export CXXFLAGS="${{CXXFLAGS:-}} -march={march} -mtune={mtune}"\n\n'
)
text = text.replace('build() {\n', 'build() {\n' + cpu_tuning, 1)
path.write_text(text, encoding='utf-8', newline='\n')
PY

# Fetch the release tarball ourselves; archive.mesa3d.org is unreliable and
# makepkg's own retry budget is too small to ride out its outages.
"${ROOT_DIR}/scripts/fetch-mesa-tarball.sh" "$MESA_BUILD_DIR"

applied_patches="$(IFS=,; printf '%s' "${patch_names[*]}")"
cat > "$MESA_BUILD_DIR/bc250-mesa-build.env" <<EOF_META
CACHYOS_MESA_COMMIT=${CACHYOS_MESA_COMMIT}
CACHYOS_MESA_PKGBUILD_URL=${UPSTREAM_BASE}/PKGBUILD
MESA_PKGREL=${MESA_PKGREL}
MESA_APPLIED_PATCHES=${applied_patches}
MESA_MARCH=${MESA_MARCH}
MESA_MTUNE=${MESA_MTUNE}
EOF_META

printf '==> Prepared Mesa build in %s\n' "$MESA_BUILD_DIR"
printf '    CachyOS Mesa commit: %s\n' "$CACHYOS_MESA_COMMIT"
printf '    applied patches:     %s\n' "$applied_patches"
printf '    pkgrel suffix:       %s\n' "$MESA_PKGREL"
printf '    Mesa CPU target:     -march=%s -mtune=%s\n' "$MESA_MARCH" "$MESA_MTUNE"
