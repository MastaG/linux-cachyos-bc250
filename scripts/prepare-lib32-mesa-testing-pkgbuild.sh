#!/usr/bin/env bash
set -Eeuo pipefail

# Build a swappable RADV-only testing driver from the stable CachyOS Mesa
# packaging, carrying patches/lib32-mesa-testing instead of patches/mesa.
#
# Only vulkan-radeon is emitted, renamed to lib32-vulkan-radeon-testing. That is the
# package holding libvulkan_radeon.so, which is where every BC-250 FSR4 change
# lives; the other seventeen split packages this PKGBUILD normally produces are
# irrelevant to the comparison and would add roughly a gigabyte of assets.
#
# The result provides/conflicts the real vulkan-radeon, so testers swap with a
# single pacman command and swap back the same way.

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
LIB32_MESA_TESTING_PKGREL="${LIB32_MESA_TESTING_PKGREL:-${BC250_PKGREL:-1}}"
LIB32_MESA_TESTING_BUILD_DIR="${LIB32_MESA_TESTING_BUILD_DIR:-${ROOT_DIR}/build/lib32-mesa-testing}"
CACHYOS_MESA_COMMIT="${CACHYOS_MESA_COMMIT:-}"
PATCH_DIR="${ROOT_DIR}/patches/mesa-testing"
LIB32_MESA_TESTING_MARCH="x86-64-v3"
LIB32_MESA_TESTING_MTUNE="znver2"

[[ "$LIB32_MESA_TESTING_PKGREL" =~ ^[0-9]+$ ]] || {
    printf 'ERROR: LIB32_MESA_TESTING_PKGREL must be numeric: %s\n' "$LIB32_MESA_TESTING_PKGREL" >&2
    exit 1
}

for cmd in curl sha256sum b2sum python3 git; do
    command -v "$cmd" >/dev/null 2>&1 || {
        printf 'ERROR: required command not found: %s\n' "$cmd" >&2
        exit 1
    }
done

mapfile -t LIB32_MESA_TESTING_PATCHES < <(find "$PATCH_DIR" -maxdepth 1 -type f -name '*.patch' -print | sort)
(( ${#LIB32_MESA_TESTING_PATCHES[@]} > 0 )) || {
    printf 'ERROR: no patches found in %s\n' "$PATCH_DIR" >&2
    exit 1
}

if [[ -z "$CACHYOS_MESA_COMMIT" ]]; then
    CACHYOS_MESA_COMMIT="$("$ROOT_DIR/scripts/resolve-cachyos-mesa.sh")"
fi
[[ "$CACHYOS_MESA_COMMIT" =~ ^[0-9a-f]{40}$ ]] || {
    printf 'ERROR: invalid CACHYOS_MESA_COMMIT: %s\n' "$CACHYOS_MESA_COMMIT" >&2
    exit 1
}

UPSTREAM_BASE="https://raw.githubusercontent.com/CachyOS/CachyOS-PKGBUILDS/${CACHYOS_MESA_COMMIT}/mesa/lib32-mesa"

rm -rf -- "$LIB32_MESA_TESTING_BUILD_DIR"
mkdir -p -- "$LIB32_MESA_TESTING_BUILD_DIR"

printf '==> Downloading CachyOS Mesa PKGBUILD at %s\n' "$CACHYOS_MESA_COMMIT"
curl -fL --retry 5 --retry-all-errors -o "$LIB32_MESA_TESTING_BUILD_DIR/PKGBUILD" "${UPSTREAM_BASE}/PKGBUILD"
curl -fL --retry 5 --retry-all-errors -o "$LIB32_MESA_TESTING_BUILD_DIR/gamescope-fps-limiter.patch" \
    "${UPSTREAM_BASE}/gamescope-fps-limiter.patch"

patch_args=()
patch_names=()
for patch in "${LIB32_MESA_TESTING_PATCHES[@]}"; do
    name="$(basename "$patch")"
    sha256="$(sha256sum "$patch" | awk '{print $1}')"
    b2="$(b2sum "$patch" | awk '{print $1}')"
    cp -- "$patch" "$LIB32_MESA_TESTING_BUILD_DIR/$name"
    patch_names+=("$name")
    patch_args+=("$name" "$sha256" "$b2")
done

python3 - "$LIB32_MESA_TESTING_BUILD_DIR/PKGBUILD" "$LIB32_MESA_TESTING_PKGREL" "$LIB32_MESA_TESTING_MARCH" "$LIB32_MESA_TESTING_MTUNE" "${patch_args[@]}" <<'PY'
from pathlib import Path
import re
import sys

path = Path(sys.argv[1])
patch_rel = sys.argv[2]
march = sys.argv[3]
mtune = sys.argv[4]
raw = sys.argv[5:]
if not raw or len(raw) % 3:
    raise SystemExit('ERROR: invalid Mesa testing patch metadata arguments')
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

text = re.sub(pkgrel_pattern, lambda m: f'pkgrel={m.group(1)}.{patch_rel}',
              text, count=1, flags=re.M)

# Rename the source package and emit only the RADV split package.
if not re.search(r'^pkgbase=lib32-mesa$', text, flags=re.M):
    raise SystemExit('ERROR: expected pkgbase=lib32-mesa in Mesa PKGBUILD')
text = re.sub(r'^pkgbase=lib32-mesa$', 'pkgbase=lib32-mesa-testing', text, count=1, flags=re.M)

pkgname_block = re.compile(r'^pkgname=\((?:[^()]*)\)\n', flags=re.M)
if not pkgname_block.search(text):
    raise SystemExit('ERROR: could not find the pkgname array in Mesa PKGBUILD')
text = pkgname_block.sub('pkgname=(\n  lib32-vulkan-radeon-testing\n)\n', text, count=1)

# Rename the split function and make it a drop-in replacement for the real one.
if text.count('package_lib32-vulkan-radeon()') != 1:
    raise SystemExit('ERROR: expected one package_lib32-vulkan-radeon() in lib32-mesa PKGBUILD')
text = text.replace('package_lib32-vulkan-radeon()', 'package_lib32-vulkan-radeon-testing()', 1)

anchor = "  provides=(lib32-vulkan-driver)\n  replaces=('lib32-amdvlk<=2025.Q2.1-1')\n"
if text.count(anchor) != 1:
    raise SystemExit('ERROR: lib32-vulkan-radeon provides/replaces block changed upstream')
text = text.replace(
    anchor,
    "  provides=(lib32-vulkan-driver lib32-vulkan-radeon=$epoch:$pkgver-$pkgrel)\n"
    "  conflicts=('lib32-vulkan-radeon')\n"
    "  replaces=('lib32-amdvlk<=2025.Q2.1-1')\n",
    1,
)

# package_mesa() is what runs `meson install` and then _pick's each driver out
# into a holding directory for the other split packages. Since we emit only the
# RADV package, package_mesa() never runs and vkradeon/ is never created, so the
# stock `mv vkradeon/* "$pkgdir"` has nothing to move. Install here instead and
# drop everything that is not the RADV driver. The license install that follows
# still runs afterwards and is unaffected.
old_mv = '  mv vkradeon/* "$pkgdir"\n'
if text.count(old_mv) != 1:
    raise SystemExit('ERROR: expected one `mv vkradeon/*` in the RADV package function')
text = text.replace(old_mv,
    '  meson install -C build --destdir "$pkgdir" --no-rebuild\n'
    '  find "$pkgdir" \\( -type f -o -type l \\) \\\n'
    "    ! -name 'libvulkan_radeon.so' \\\n"
    "    ! -name '00-radv-defaults.conf' \\\n"
    "    ! -name 'radeon_icd.json' -delete\n"
    '  find "$pkgdir" -mindepth 1 -depth -type d -empty -delete\n', 1)

names = '\n'.join(f'  "{name}"' for name, _, _ in patches)
sha256s = '\n'.join(f"  '{sha}'" for _, sha, _ in patches)
b2s = '\n'.join(f"  '{b2}'" for _, _, b2 in patches)
inject = (
    '# BC-250 / GFX1013 FSR4 isolation patch set. 0001 and 0005 are always\n'
    '# active; 0002/0003 stay runtime-gated behind RADV_GFX103 added by 0004.\n'
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
"${ROOT_DIR}/scripts/fetch-mesa-tarball.sh" "$LIB32_MESA_TESTING_BUILD_DIR"

applied_patches="$(IFS=,; printf '%s' "${patch_names[*]}")"
cat > "$LIB32_MESA_TESTING_BUILD_DIR/bc250-lib32-mesa-testing-build.env" <<EOF_META
CACHYOS_MESA_COMMIT=${CACHYOS_MESA_COMMIT}
CACHYOS_MESA_PKGBUILD_URL=${UPSTREAM_BASE}/PKGBUILD
LIB32_MESA_TESTING_PKGREL=${LIB32_MESA_TESTING_PKGREL}
LIB32_MESA_TESTING_APPLIED_PATCHES=${applied_patches}
LIB32_MESA_TESTING_MARCH=${LIB32_MESA_TESTING_MARCH}
LIB32_MESA_TESTING_MTUNE=${LIB32_MESA_TESTING_MTUNE}
EOF_META

printf '==> Prepared Mesa testing build in %s\n' "$LIB32_MESA_TESTING_BUILD_DIR"
printf '    CachyOS Mesa commit: %s\n' "$CACHYOS_MESA_COMMIT"
printf '    applied patches:     %s\n' "$applied_patches"
printf '    emits:               lib32-vulkan-radeon-testing\n'
printf '    pkgrel suffix:       %s\n' "$LIB32_MESA_TESTING_PKGREL"
