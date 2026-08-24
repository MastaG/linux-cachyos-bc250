#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
MESA_GIT_PKGREL="${MESA_GIT_PKGREL:-${BC250_PKGREL:-1}}"
MESA_GIT_BUILD_DIR="${MESA_GIT_BUILD_DIR:-${ROOT_DIR}/build/mesa-git}"
CACHYOS_MESA_COMMIT="${CACHYOS_MESA_COMMIT:-}"
MESA_GIT_COMMIT="${MESA_GIT_COMMIT:-}"
MESA_GIT_MARCH="x86-64-v3"
MESA_GIT_MTUNE="znver2"
PATCH_DIR="${ROOT_DIR}/patches/mesa-git"
MESA_GIT_PATCHES=(
    "${PATCH_DIR}/0001-gfx1013-compute-queue-fix.patch"
    "${PATCH_DIR}/0002-gfx1013-mesh-task-shaders.patch"
    "${PATCH_DIR}/0003-gfx1013-taskmesh-queries.patch"
    "${PATCH_DIR}/0004-radv-gfx103.patch"
    "${PATCH_DIR}/0005-bc250-fsr4-v3.patch"
)

[[ "$MESA_GIT_PKGREL" =~ ^[0-9]+$ ]] || {
    printf 'ERROR: MESA_GIT_PKGREL must be numeric: %s\n' "$MESA_GIT_PKGREL" >&2
    exit 1
}

for cmd in curl python3 git sha256sum; do
    command -v "$cmd" >/dev/null 2>&1 || {
        printf 'ERROR: required command not found: %s\n' "$cmd" >&2
        exit 1
    }
done
for patch in "${MESA_GIT_PATCHES[@]}"; do
    [[ -f "$patch" ]] || {
        printf 'ERROR: missing Mesa-Git patch: %s\n' "$patch" >&2
        exit 1
    }
done

if [[ -z "$CACHYOS_MESA_COMMIT" ]]; then
    CACHYOS_MESA_COMMIT="$("$ROOT_DIR/scripts/resolve-cachyos-mesa.sh")"
fi
if [[ -z "$MESA_GIT_COMMIT" ]]; then
    MESA_GIT_COMMIT="$("$ROOT_DIR/scripts/resolve-mesa-git.sh")"
fi
[[ "$CACHYOS_MESA_COMMIT" =~ ^[0-9a-f]{40}$ ]] || {
    printf 'ERROR: invalid CACHYOS_MESA_COMMIT: %s\n' "$CACHYOS_MESA_COMMIT" >&2
    exit 1
}
[[ "$MESA_GIT_COMMIT" =~ ^[0-9a-f]{40}$ ]] || {
    printf 'ERROR: invalid MESA_GIT_COMMIT: %s\n' "$MESA_GIT_COMMIT" >&2
    exit 1
}

UPSTREAM_BASE="https://raw.githubusercontent.com/CachyOS/CachyOS-PKGBUILDS/${CACHYOS_MESA_COMMIT}/mesa/mesa-git"
rm -rf -- "$MESA_GIT_BUILD_DIR"
mkdir -p -- "$MESA_GIT_BUILD_DIR/mesa-userpatches"

printf '==> Downloading CachyOS mesa-git packaging at %s\n' "$CACHYOS_MESA_COMMIT"
for file in PKGBUILD customization.cfg LICENSE llvm32.native; do
    curl -fL --retry 5 --retry-all-errors -o "$MESA_GIT_BUILD_DIR/$file" "${UPSTREAM_BASE}/${file}"
done

# Keep CachyOS' customization.cfg unchanged. Its current defaults build both
# mesa-git and lib32-mesa-git and enable non-interactive user patches.
python3 - "$MESA_GIT_BUILD_DIR/customization.cfg" <<'PY'
from pathlib import Path
import re
import sys

cfg = Path(sys.argv[1]).read_text(encoding='utf-8')
expected = {
    '_lib32': 'true',
    '_user_patches': '"true"',
    '_user_patches_no_confirm': '"true"',
}
for key, value in expected.items():
    pattern = rf'^{re.escape(key)}={re.escape(value)}[ \t]*$'
    if not re.search(pattern, cfg, flags=re.M):
        raise SystemExit(
            f'ERROR: upstream mesa-git customization.cfg no longer has {key}={value}; review the package before building'
        )
PY

# Apply the complete BC-250 Mesa series through CachyOS' native user-patch
# mechanism. 0001 and 0005 apply unconditionally. 0002/0003 contain the
# experimental mesh/task path, but their GFX1013 feature exposure remains
# dormant unless 0004 sees RADV_GFX103=1 at runtime.
patch_names=()
for patch in "${MESA_GIT_PATCHES[@]}"; do
    name="$(basename "$patch")"
    patch_names+=("$name")
    cp -- "$patch" "$MESA_GIT_BUILD_DIR/mesa-userpatches/${name%.patch}.mymesapatch"
done

# Pin the already-resolved Mesa commit through the PKGBUILD's supported
# user.cfg override. This leaves upstream customization.cfg byte-for-byte
# untouched while preventing Mesa main from moving during a workflow run.
cat > "$MESA_GIT_BUILD_DIR/mesa-userpatches/user.cfg" <<EOF_USERCFG
_mesa_commit="${MESA_GIT_COMMIT}"
EOF_USERCFG

python3 - "$MESA_GIT_BUILD_DIR/PKGBUILD" "$MESA_GIT_PKGREL" "$MESA_GIT_MARCH" "$MESA_GIT_MTUNE" <<'PY'
from pathlib import Path
import re
import sys

pkgbuild = Path(sys.argv[1])
patch_rel, march, mtune = sys.argv[2:]
text = pkgbuild.read_text(encoding='utf-8')
pkgrel_pattern = r'^pkgrel=([0-9]+(?:\.[0-9]+)*)$'
if len(re.findall(pkgrel_pattern, text, flags=re.M)) != 1:
    raise SystemExit('ERROR: expected one numeric pkgrel assignment in mesa-git PKGBUILD')
text = re.sub(pkgrel_pattern, lambda m: f'pkgrel={m.group(1)}.{patch_rel}', text, count=1, flags=re.M)

# Arch has removed lib32-libvdpau from [multilib], so pacman aborts the build
# with "target not found: lib32-libvdpau" before anything is compiled. Nothing
# actually needs it: Mesa deleted VDPAU in commit 4b54277d ("Remove VDPAU",
# 2025-08-07), and this PKGBUILD's own merge-base guard therefore never sets
# _gallium_vdpau, so gallium-vdpau is not built at all. The 64-bit libvdpau
# makedepend is left alone; that package still exists.
#
# This is tolerant on purpose: once CachyOS drops the stale entry the
# substitution matches nothing and this becomes a no-op.
stale_vdpau = len(re.findall(r"'lib32-libvdpau'", text))
if stale_vdpau:
    text = re.sub(r"'lib32-libvdpau'[ \t]*", '', text)
    print(f'==> Dropped {stale_vdpau} stale lib32-libvdpau makedepend(s); '
          'Arch removed the package and Mesa no longer builds VDPAU')

# The upstream PKGBUILD can replace all CFLAGS when _custom_opt_flags is set.
# Keep that behaviour untouched, then append the BC-250 target after the block.
pattern = re.compile(
    r'(build \(\) \{\n'
    r'    if \[ -n "\$_custom_opt_flags" \]; then\n'
    r'      export CFLAGS="\$\{_custom_opt_flags\}"\n'
    r'      export CPPFLAGS="\$\{_custom_opt_flags\}"\n'
    r'      export CXXFLAGS="\$\{_custom_opt_flags\}"\n'
    r'    fi\n)'
)
match = pattern.search(text)
if not match:
    raise SystemExit('ERROR: mesa-git build() custom optimization block changed upstream')
insert = (
    match.group(1)
    + '    # BC-250 CPU target: x86-64-v3 baseline, tuned for Zen 2.\n'
    + f'    export CFLAGS="${{CFLAGS:-}} -march={march} -mtune={mtune}"\n'
    + f'    export CXXFLAGS="${{CXXFLAGS:-}} -march={march} -mtune={mtune}"\n\n'
)
text = text[:match.start()] + insert + text[match.end():]
pkgbuild.write_text(text, encoding='utf-8', newline='\n')
PY

applied_patches="$(IFS=,; printf '%s' "${patch_names[*]}")"
cat > "$MESA_GIT_BUILD_DIR/bc250-mesa-git-build.env" <<EOF_META
CACHYOS_MESA_COMMIT=${CACHYOS_MESA_COMMIT}
CACHYOS_MESA_GIT_PKGBUILD_URL=${UPSTREAM_BASE}/PKGBUILD
MESA_GIT_COMMIT=${MESA_GIT_COMMIT}
MESA_GIT_PKGREL=${MESA_GIT_PKGREL}
MESA_GIT_APPLIED_PATCHES=${applied_patches}
MESA_GIT_MARCH=${MESA_GIT_MARCH}
MESA_GIT_MTUNE=${MESA_GIT_MTUNE}
MESA_GIT_LIB32=true
EOF_META

printf '==> Prepared mesa-git build in %s\n' "$MESA_GIT_BUILD_DIR"
printf '    CachyOS packaging commit: %s\n' "$CACHYOS_MESA_COMMIT"
printf '    Mesa Git commit:          %s\n' "$MESA_GIT_COMMIT"
printf '    upstream lib32 build:     enabled (mesa-git + lib32-mesa-git)\n'
printf '    applied patches:          %s\n' "$applied_patches"
printf '    CPU target:               -march=%s -mtune=%s\n' "$MESA_GIT_MARCH" "$MESA_GIT_MTUNE"
