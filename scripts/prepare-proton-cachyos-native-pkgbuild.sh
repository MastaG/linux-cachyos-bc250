#!/usr/bin/env bash
set -Eeuo pipefail

# Fetch CachyOS's proton-cachyos-native PKGBUILD and rewrite it into
# proton-cachyos-native-bc250: same Proton, tuned for this hardware, with the
# pinned FSR4 payload built into the compatibility tool.
#
# Rewriting rather than carrying a .patch of the PKGBUILD, for the same reason
# the Mesa packages do it: every edit below asserts on its anchor, so upstream
# moving a line fails the build with a message naming what moved, instead of a
# patch applying at an offset and quietly meaning something else.

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PKGREL="${PROTON_CACHYOS_NATIVE_PKGREL:-${BC250_PKGREL:-1}}"
BUILD_DIR="${PROTON_CACHYOS_NATIVE_BUILD_DIR:-${ROOT_DIR}/build/proton-cachyos-native-bc250}"
CACHYOS_MESA_COMMIT="${CACHYOS_MESA_COMMIT:-}"
MARCH="x86-64-v3"
MTUNE="znver2"

# shellcheck disable=SC1091
source "${ROOT_DIR}/scripts/fsr4-payload-sources.sh"

[[ "$PKGREL" =~ ^[0-9]+$ ]] || {
    printf 'ERROR: PKGREL must be numeric: %s\n' "$PKGREL" >&2
    exit 1
}

for cmd in curl sha256sum python3 bash; do
    command -v "$cmd" >/dev/null 2>&1 || {
        printf 'ERROR: required command not found: %s\n' "$cmd" >&2
        exit 1
    }
done

# proton-cachyos-native lives in the same repository as the Mesa PKGBUILDs, so
# it is pinned to the same commit by the same resolver.
if [[ -z "$CACHYOS_MESA_COMMIT" ]]; then
    CACHYOS_MESA_COMMIT="$("$ROOT_DIR/scripts/resolve-cachyos-mesa.sh")"
fi
[[ "$CACHYOS_MESA_COMMIT" =~ ^[0-9a-f]{40}$ ]] || {
    printf 'ERROR: invalid CACHYOS_MESA_COMMIT: %s\n' "$CACHYOS_MESA_COMMIT" >&2
    exit 1
}

UPSTREAM_BASE="https://raw.githubusercontent.com/CachyOS/CachyOS-PKGBUILDS/${CACHYOS_MESA_COMMIT}/proton-cachyos-native"

rm -rf -- "$BUILD_DIR"
mkdir -p -- "$BUILD_DIR"

printf '==> Downloading proton-cachyos-native PKGBUILD at %s\n' "$CACHYOS_MESA_COMMIT"
for file in PKGBUILD compatibilitytool.vdf.template ntsync.conf proton-cachyos-native.install; do
    curl -fL --retry 5 --retry-all-errors -o "$BUILD_DIR/$file" "${UPSTREAM_BASE}/${file}"
done

# install= is ${pkgname}-derived, so renaming the package renames the file it
# looks for. Same content, new name.
mv -- "$BUILD_DIR/proton-cachyos-native.install" \
      "$BUILD_DIR/proton-cachyos-native-bc250.install"

printf '==> Selecting the OptiScaler build\n'
select_args=(--preset "${ROOT_DIR}/packages/bc250-fsr4-common/optiscaler-preset.json")
if [[ "${BC250_FSR4_TRACK_OPTISCALER:-0}" != 1 ]]; then
    select_args+=(--force-fallback)
fi
optiscaler_env="$(python3 "${ROOT_DIR}/scripts/select-optiscaler.py" "${select_args[@]}")"
eval "$optiscaler_env"

# Which fakenvapi release to bundle. Tracked live rather than pinned, unlike
# the OptiScaler build: fakenvapi releases rarely, and the point of shipping
# it is that users get the current one without anyone editing a pin.
printf '==> resolving the fakenvapi release\n'
fakenvapi_env="$("$ROOT_DIR/scripts/resolve-fakenvapi.sh")"
eval "$fakenvapi_env"
printf '    %s (%s)\n' "$FAKENVAPI_TAG" "$FAKENVAPI_ASSET"

stage_fsr4_payload_sources "$ROOT_DIR" "$BUILD_DIR" proton-cachyos

: "${BC250_FSR4_PAYLOAD_BASE:=https://github.com/MastaG/linux-cachyos-bc250/releases/download/bc250-fsr4-payload}"

# makepkg wants every integrity array to cover every source. Upstream provides
# only b2sums, and we have SHA256 pins rather than BLAKE2 ones for the payload,
# so the upstream entries keep their b2sums and ours get a sha256sums array
# whose leading entries are SKIP. Every source still ends up verified by exactly
# one of the two. The upstream count has to come from bash rather than a regex:
# the wine-gecko line is a brace expansion and is two elements, not one.
upstream_sources="$(bash -c 'source "$1" >/dev/null 2>&1; printf "%s" "${#source[@]}"' _ "$BUILD_DIR/PKGBUILD")"
[[ "$upstream_sources" =~ ^[0-9]+$ ]] && (( upstream_sources > 0 )) || {
    printf 'ERROR: could not count the upstream source array (got %s)\n' "$upstream_sources" >&2
    exit 1
}
printf '    upstream source entries: %s\n' "$upstream_sources"

python3 - \
    "$BUILD_DIR/PKGBUILD" "$PKGREL" "$MARCH" "$MTUNE" "$upstream_sources" \
    "$OPTISCALER_ASSET" "$OPTISCALER_URL" "$OPTISCALER_SHA256" "$OPTISCALER_VERSION" \
    "$FAKENVAPI_ASSET" "$FAKENVAPI_URL" "$FAKENVAPI_SHA256" \
    "$BC250_FSR4_PAYLOAD_BASE" \
    "${FSR4_PAYLOAD_SHA256[SHA_PATCH]}" "${FSR4_PAYLOAD_SHA256[SHA_LAUNCH]}" \
    "${FSR4_PAYLOAD_SHA256[SHA_PAYLOAD_BUILDER]}" "${FSR4_PAYLOAD_SHA256[SHA_PRESET]}" \
    "${FSR4_PAYLOAD_SHA256[SHA_SHIM]}" <<'PY'
from pathlib import Path
import sys

(path, pkgrel, march, mtune, upstream_n, opti_asset, opti_url, opti_sha,
 opti_version, fakenvapi_asset, fakenvapi_url, fakenvapi_sha, payload_base,
 sha_patch, sha_launch, sha_builder, sha_preset, sha_shim) = sys.argv[1:19]
upstream_n = int(upstream_n)

path = Path(path)
text = path.read_text(encoding="utf-8")


def sub(old, new, what):
    global text
    if text.count(old) != 1:
        raise SystemExit(
            f"ERROR: expected {what} exactly once in proton-cachyos-native PKGBUILD"
        )
    text = text.replace(old, new, 1)


sub("pkgname=proton-cachyos-native\n",
    "pkgname=proton-cachyos-native-bc250\n", "the pkgname assignment")

# The two lines that decide whether this coexists with the official package.
#
# Inherited as-is, replaces= makes pacman REMOVE proton-cachyos when this is
# installed, which is the exact opposite of the intent, and provides= would let
# it satisfy another package's dependency on Proton. Both are cleared. No
# conflicts= is added either: nothing here collides, since every installed path
# and the Steam-internal tool name are all ${pkgname}-derived.
sub("provides=('proton-cachyos' 'proton')\n", "provides=()\n", "the provides array")
sub("replaces=('proton-cachyos')\n", "replaces=()\n", "the replaces array")

sub("\npkgrel=3\n", f"\npkgrel=3.{pkgrel}\n", "pkgrel=3")

# Upstream targets a portable baseline. The BC-250 is a fixed Zen 2 part and
# this matches what the kernel and Mesa packages here are built with.
sub('    local march="nocona"\n    local mtune="core-avx2"\n',
    f'    local march="{march}"\n    local mtune="{mtune}"\n',
    "the march/mtune pair")

sub('-e "s|##DISPLAY_NAME##|proton-cachyos-${_srctag} (native)|" \\\n',
    '-e "s|##DISPLAY_NAME##|proton-cachyos-${_srctag} (native, BC-250 FSR4)|" \\\n',
    "the display-name substitution")

# Teach protonfixes to read our pinned manifest. The Makefile globs
# patches/protonfixes/**.patch, sorts, and applies each with
# `patch -d $(PROTONFIXES_SRC) -Np1`, so dropping a later-sorting directory in
# is the whole integration -- no Makefile or configure change.
sub("    cd proton-cachyos\n",
    "    cd proton-cachyos\n"
    "\n"
    "    # Local private builds only (scripts/build-proton-tarball.sh). Never set in\n"
    "    # CI, so the published package cannot pick up anything from here. The path\n"
    "    # points outside srcdir because these are the user's own files rather than\n"
    "    # a pinned source, which is also why it is gated instead of always on.\n"
    "    if [[ \"${BC250_LOCAL_PATCHES:-0}\" == 1 && -d \"${BC250_LOCAL_PATCHES_DIR:-/workspace/local-patches}/proton-cachyos-native\" ]]; then\n"
    "        for _local_patch in \"${BC250_LOCAL_PATCHES_DIR:-/workspace/local-patches}/proton-cachyos-native\"/*.patch; do\n"
    "            [[ -e \"$_local_patch\" ]] || continue\n"
    "            printf '==> applying local patch %s\\n' \"$(basename \"$_local_patch\")\"\n"
    "            patch --batch -Np1 -i \"$_local_patch\" || return 1\n"
    "        done\n"
    "    fi\n"
    "\n"
    "    # BC-250: pinned FSR4 upscaler manifest, applied by the Makefile's own\n"
    "    # sorted patches/protonfixes glob after upstream's 0002-upscalers set.\n"
    "    install -Dm644 \"$srcdir/0001-pinned-upscaler-manifest.patch\" \\\n"
    "        patches/protonfixes/0003-bc250-fsr4/0001-pinned-upscaler-manifest.patch\n",
    "the `cd proton-cachyos` in prepare()")

# Lay the payload into dist/ so package()'s existing rsync carries it, and point
# Steam at our shim instead of Proton's own launcher.
sub('      "${srcdir}/compatibilitytool.vdf.template" > compatibilitytool.vdf\n}\n',
    '      "${srcdir}/compatibilitytool.vdf.template" > compatibilitytool.vdf\n'
    "\n"
    "    # BC-250 FSR4 payload. Written into dist/, which package() rsyncs whole.\n"
    '    python3 "${srcdir}/build-fsr4-payload.py" \\\n'
    f'        --optiscaler "${{srcdir}}/{opti_asset}" \\\n'
    f'        --optiscaler-version "{opti_version}" \\\n'
    '        --optipatcher "${srcdir}/OptiPatcher_v0.41.asi" \\\n'
    f'        --fakenvapi "${{srcdir}}/{fakenvapi_asset}" \\\n'
    '        --provider "${srcdir}/amdxcffx64_v4.1.1.xz" \\\n'
    '        --ffx-sdk "${srcdir}/amd_fidelityfx_upscaler_dx12.dll" \\\n'
    '        --ffx-sdk-alt fsr411b \\\n'
    '            "${srcdir}/amd_fidelityfx_upscaler_dx12_v4.1.1b.dll" \\\n'
    '            "https://github.com/the3rdparty1917/fsr4xyz/releases/tag/4.1.1b" \\\n'
    '        --ffx-sdk-alt fsr411f \\\n'
    '            "${srcdir}/bc250-fsr4-dll-4.0.0-rc8.tar.xz" \\\n'
    '            "https://github.com/daniel-h-0/bc250-fsr4-fork/releases/tag/v4.0.0-rc8" \\\n'
    '        --dlss "${srcdir}/nvngx_dlss.dll" \\\n'
    '        --licenses "${srcdir}" \\\n'
    '        --preset "${srcdir}/optiscaler-preset.json" \\\n'
    '        --manifest-rel "upscaler-manifest.json" \\\n'
    '        --proton-rel "proton" \\\n'
    "        --output . \\\n"
    "        --config bc250-fsr4-config.json || return 1\n"
    "\n"
    '    install -Dm755 "${srcdir}/proton-shim.sh" bc250-fsr4-proton\n'
    '    install -Dm644 "${srcdir}/bc250-fsr4-launch.py" bc250-fsr4-launch.py\n'
    "\n"
    "    # Steam runs whatever toolmanifest.vdf names. Point it at the shim so the\n"
    "    # pinned payload is selected before Proton starts; upstream's launcher is\n"
    "    # left untouched at ./proton, which is what the shim goes on to run.\n"
    '    if ! grep -q \'"commandline" "/proton \' toolmanifest.vdf; then\n'
    "        printf 'ERROR: dist/toolmanifest.vdf no longer runs /proton\\n' >&2\n"
    "        cat toolmanifest.vdf >&2\n"
    "        return 1\n"
    "    fi\n"
    "    sed -i 's|\"commandline\" \"/proton |\"commandline\" \"/bc250-fsr4-proton |' \\\n"
    "        toolmanifest.vdf\n"
    "}\n",
    "the end of build()")

payload_sources = [
    (opti_asset, opti_url, opti_sha, True),
    ("OptiPatcher_v0.41.asi", f"{payload_base}/OptiPatcher_v0.41.asi",
     "fb12735bfcc0d47f534f2206d57ec34129dc3d22b6405a1c2ef86745ab48b2eb", False),
    ("amdxcffx64_v4.1.1.xz", f"{payload_base}/amdxcffx64_v4.1.1.xz",
     "5de9b6d9f5475a0f2622e4cbce88cde46c68929d9bd0bbc353c70056997bb771", True),
    ("amd_fidelityfx_upscaler_dx12.dll",
     "https://raw.githubusercontent.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK/"
     "f4c1da8e92f3fe563b5c28c44e6267ce6b6b8eb2/Kits/FidelityFX/signedbin/"
     "amd_fidelityfx_upscaler_dx12.dll",
     "241e6e5e4d848424eb8ec9a6b22c43fe34cf0cf52d30002ca435ba42e53a9ca0", False),
    # Opt-in only, never the default: an unsigned third-party rebuild of the
    # FidelityFX bridge, mirrored so a deleted upstream release cannot change
    # what a rebuild produces. Selected with PROTON_USE_OPTISCALER=fsr411b.
    ("amd_fidelityfx_upscaler_dx12_v4.1.1b.dll", f"{payload_base}/amd_fidelityfx_upscaler_dx12_v4.1.1b.dll",
     "0dd77d9c78d1ef9bc330cf4697ab3ffe24bc1aa7850e4130263dc922107fbd75", False),
    # Opt-in only: the BC-250 FSR4 fork's RC8 bridge, mirrored from its
    # release. Taken as the published archive rather than a bare DLL -- 10 MB
    # against 112 MB, and it carries the notices that release asks be kept.
    ("bc250-fsr4-dll-4.0.0-rc8.tar.xz", f"{payload_base}/bc250-fsr4-dll-4.0.0-rc8.tar.xz",
     "805a3df9cef931decd42d02eaffb375f95844afce2e13d78bad757a27c806da2", True),
    # Tracked live, not pinned: resolve-fakenvapi.sh takes the newest release, so
    # a new upstream version changes this package's fingerprint and rebuilds it.
    (fakenvapi_asset, fakenvapi_url, fakenvapi_sha, True),
    ("nvngx_dlss.dll",
     "https://raw.githubusercontent.com/NVIDIA/DLSS/"
     "a291cc7d2cc642a51566f3dfd5376f635cd1b284/lib/Windows_x86_64/rel/nvngx_dlss.dll",
     "be6e434a94ca32499515eb62ca0e6c274526055d568d0426e4c652dcdfb6ee6e", False),
]
local_sources = [
    ("0001-pinned-upscaler-manifest.patch", sha_patch),
    ("bc250-fsr4-launch.py", sha_launch),
    ("build-fsr4-payload.py", sha_builder),
    ("optiscaler-preset.json", sha_preset),
    ("proton-shim.sh", sha_shim),
    ("FidelityFX-SDK-4.0.2.txt",
     "be05d8cd5489deff924dbe91e0c5b8c0ff034d43cd11749bf9a67a0c38252b7b"),
    ("NVIDIA-DLSS.txt",
     "21b5daec892b12bea692e66bc8fe45cf5902ccaf3a7b831e78050d8859881c37"),
]

added = [f'  "{name}::{url}"' for name, url, _, _ in payload_sources]
added += [f"  '{name}'" for name, _ in local_sources]
noextract = [f'  "{name}"' for name, _, _, skip in payload_sources if skip]
sums = [f"  '{sha}'" for _, _, sha, _ in payload_sources]
sums += [f"  '{sha}'" for _, sha in local_sources]
skips = "\n".join("  'SKIP'" for _ in range(upstream_n))

newline = "\n"
text += (
    "\n"
    "# --- BC-250 FSR4 ----------------------------------------------------------\n"
    "#\n"
    "# The archives are handed to build-fsr4-payload.py as-is, so makepkg must not\n"
    "# unpack them. Everything above keeps its upstream b2sum; these carry SHA256\n"
    "# pins instead, so the two arrays together cover every source exactly once.\n"
    f"source+=({newline}{newline.join(added)}{newline})\n"
    f"noextract+=({newline}{newline.join(noextract)}{newline})\n"
    f"b2sums+=({newline}{newline.join('  ' + chr(39) + 'SKIP' + chr(39) for _ in added)}{newline})\n"
    f"sha256sums=({newline}{skips}{newline}{newline.join(sums)}{newline})\n"
)

path.write_text(text, encoding="utf-8", newline="\n")
PY

cat > "$BUILD_DIR/bc250-proton-build.env" <<EOF_META
CACHYOS_MESA_COMMIT=${CACHYOS_MESA_COMMIT}
CACHYOS_PROTON_PKGBUILD_URL=${UPSTREAM_BASE}/PKGBUILD
PROTON_CACHYOS_NATIVE_PKGREL=${PKGREL}
PROTON_MARCH=${MARCH}
PROTON_MTUNE=${MTUNE}
OPTISCALER_VERSION=${OPTISCALER_VERSION}
OPTISCALER_TAG=${OPTISCALER_TAG}
FAKENVAPI_VERSION=${FAKENVAPI_VERSION}
FAKENVAPI_TAG=${FAKENVAPI_TAG}
EOF_META

printf '==> Prepared proton-cachyos-native-bc250 in %s\n' "$BUILD_DIR"
printf '    CachyOS PKGBUILDS commit: %s\n' "$CACHYOS_MESA_COMMIT"
printf '    CPU target:               -march=%s -mtune=%s\n' "$MARCH" "$MTUNE"
printf '    OptiScaler:               %s (%s)\n' "$OPTISCALER_VERSION" "$OPTISCALER_TAG"
printf '    pkgrel suffix:            %s\n' "$PKGREL"
