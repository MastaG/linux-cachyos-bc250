#!/usr/bin/env bash
# Compile a Proton fork from source inside Valve's Steam Runtime SDK image.
#
# This is stage one of the two Steam Linux Runtime packages. It produces the
# `dist/` tree a Proton build normally ships, tuned for this hardware, which the
# matching PKGBUILD then packages with the FSR4 payload. Two stages because the
# compile has to happen in Valve's SDK image (Debian) while the packaging has to
# happen under makepkg (Arch), and makepkg cannot start a container of its own.
#
#   scripts/build-proton-runtime-dist.sh \
#       --repo https://github.com/GloriousEggroll/proton-ge-custom.git \
#       --tag GE-Proton11-6 --name protonge-latest-bc250 \
#       --out out/dist/protonge-latest-bc250.tar.xz
#
# Why not the container engine the build wants to start itself: Proton's
# Makefile re-enters the SDK image for every target, which would mean running a
# container inside the container CI already builds in. Makefile.in has a
# CONTAINER=1 branch that builds directly instead, so this runs the SDK image
# once and builds inside it.
#
# Tuning matches proton-cachyos-native-bc250 and goes in the way the fork's own
# release workflow does it: CFLAGS and RUSTFLAGS in the environment, which
# configure bakes into HOST_CFLAGS. The Makefile derives the per-arch flags from
# that -- including the -mno-avx DXVK insists on -- so they are never overridden
# here. Overriding them at make time also drops each component's include paths,
# which is what cost a vrclient build its Vulkan headers.
set -Eeuo pipefail

trap 'status=$?; printf "\nERROR: %s failed at line %s (exit %s): %s\n" \
    "${BASH_SOURCE[0]:-$0}" "$LINENO" "$status" "$BASH_COMMAND" >&2' ERR

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
ENGINE_SPEC="${BC250_CONTAINER_ENGINE:-podman}"
read -r -a ENGINE <<< "$ENGINE_SPEC"
MARCH="${BC250_PROTON_MARCH:-x86-64-v3}"
# Which compiler builds the Windows (PE) side. Proton's Makefile picks it from
# whatever `cc` is, which in the SDK image is GCC -- and mingw-gcc then rejects
# Valve's own wine on --enable-werror:
#
#   process.c:807: error: assignment discards 'const' qualifier
#
# in the EAC bootstrapper block, which is Valve's code, not GE's. Valve build
# the PE side with clang, and the image ships clang plus the llvm binutils the
# clang branch expects, so this selects that half explicitly. The unix side
# stays on the image's GCC, which is what SteamRT's own comments assume.
# Which compiler the whole build uses. Proton's Makefile decides this once, by
# asking what `cc` is, and then derives a matched set from it: MINGW_TYPE for
# wine's configure, TOOLCHAIN_PREFIX for objcopy and strip, OBJCOPY_FLAGS, and
# the cross files meson builds its PE components with.
#
# So it is selected the way the Makefile expects -- by putting the compiler on
# PATH as `cc` -- rather than by overriding those variables one at a time.
# Overriding a subset produces a build no one ships: taking llvm- without
# clearing OBJCOPY_FLAGS gives `llvm-objcopy: option is not supported for COFF`,
# and pointing wine at clang while meson still uses mingw-gcc gives
# `llvm-strip: invalid SymbolTableIndex` on a GCC-built DLL.
#
# The image's own GCC by default, which is what the Makefile's SteamRT comments
# assume and what a fork building without --enable-werror wants. Overridable,
# because a fork that does pass --enable-werror will reject Valve's own wine on
# a const discard in the EAC bootstrapper block (process.c) and want clang --
# though note that the PE compiler is hardcoded to mingw-gcc in
# make/rules-common.mk while STRIP follows the compiler branch, so clang there
# strips GCC output with llvm-strip and fails. That combination is why
# GE-Proton is not built from source here.
BUILD_CC="${BC250_PROTON_CC:-gcc}"
MTUNE="${BC250_PROTON_MTUNE:-znver2}"
JOBS="${BC250_PROTON_JOBS:-$(nproc)}"
REPO="" TAG="" NAME="" OUT="" SRC="" KEEP_BUILD=false
# A named volume, not a host path. $HOME is not a safe assumption where this
# runs: on the CI runner the container engine could not create /root/.cache and
# the whole build died before it started. A volume is the engine's to create,
# survives between runs the way the rest of CI's caches do, and needs no
# permissions on the host at all. Override with a path only if you want one.
CCACHE_VOLUME="${BC250_PROTON_CCACHE:-bc250-proton-ccache}"

usage() {
    awk 'NR > 1 { if (!/^#/) exit; sub(/^# ?/, ""); print }' "${BASH_SOURCE[0]}"
    exit "${1:-0}"
}

while (( $# )); do
    case "$1" in
        --repo) REPO="${2:?--repo needs a value}"; shift 2 ;;
        --tag)  TAG="${2:?--tag needs a value}"; shift 2 ;;
        --name) NAME="${2:?--name needs a value}"; shift 2 ;;
        --out)  OUT="${2:?--out needs a value}"; shift 2 ;;
        --src)  SRC="${2:?--src needs a value}"; shift 2 ;;
        --keep-build) KEEP_BUILD=true; shift ;;
        -h|--help) usage 0 ;;
        *) printf 'ERROR: unexpected argument: %s\n\n' "$1" >&2; usage 1 ;;
    esac
done
for required in REPO TAG NAME OUT; do
    [[ -n "${!required}" ]] || { printf 'ERROR: --%s is required\n' "${required,,}" >&2; exit 1; }
done

SRC="${SRC:-${ROOT_DIR}/build/proton-src/${NAME}}"
OUT="$(cd -- "$(dirname -- "$OUT")" 2>/dev/null && pwd)/$(basename -- "$OUT")" || {
    mkdir -p -- "$(dirname -- "$OUT")"
    OUT="$(cd -- "$(dirname -- "$OUT")" && pwd)/$(basename -- "$OUT")"
}

command -v "${ENGINE[0]}" >/dev/null 2>&1 || {
    printf 'ERROR: %s is not installed\n' "${ENGINE[0]}" >&2
    exit 1
}

# --- source ----------------------------------------------------------------
#
# Shallow, and shallow in the submodules too: this tree is wine, dxvk,
# vkd3d-proton, ffmpeg and a dozen more, and none of their history is used.
if [[ ! -d "$SRC/.git" ]]; then
    printf '==> cloning %s at %s\n' "$REPO" "$TAG"
    mkdir -p -- "$(dirname -- "$SRC")"
    git clone --depth 1 --branch "$TAG" --recurse-submodules --shallow-submodules \
        "$REPO" "$SRC"
else
    printf '==> updating %s to %s\n' "$SRC" "$TAG"
    git -C "$SRC" fetch --depth 1 origin "refs/tags/$TAG:refs/tags/$TAG" --force
    git -C "$SRC" checkout --force "$TAG"
    git -C "$SRC" submodule update --init --recursive --depth 1 --force
fi
git -C "$SRC" clean -xdf --quiet -e .ccache

# --- the prep step make does not run -----------------------------------------
#
# GE applies wine-staging and its own patch set through this script, by hand,
# before building. Nothing in the Makefile calls it, so a plain `make dist` on a
# fresh checkout compiles unpatched wine -- which fails an hour in, on
# --enable-werror, in code that staging rewrites:
#
#   process.c:804: error: assignment discards 'const' qualifier [-Werror=...]
#
# It resets and cleans each submodule itself, so it wants the pristine tree it
# gets here, and it is versioned with the tag, so it applies to the tag it
# shipped with. Forks that carry their patches in-tree (CachyOS) have no such
# script and skip this.
PREP="$SRC/patches/protonprep-valve-staging.sh"
if [[ -x "$PREP" ]]; then
    printf '==> applying %s\n' "$(basename "$PREP")"
    ( cd "$SRC" && ./patches/protonprep-valve-staging.sh )
else
    printf '==> no prep script in this tree; patches are carried in-tree\n'
fi

# --- the one patch ---------------------------------------------------------
#
# configure.sh insists on finding a container engine so it can start the SDK
# image itself. We are already inside that image, so the check has nothing to
# find. CachyOS's fork carries exactly this guard, which is why its own native
# build works; upstream GE does not, so it is added here when missing rather
# than carried as a patch file that would rot on every release.
if grep -q 'arg_container_engine" != "none"' "$SRC/configure.sh"; then
    printf '==> configure.sh already supports --container-engine=none\n'
else
    printf '==> teaching configure.sh --container-engine=none\n'
    python3 - "$SRC/configure.sh" <<'EOF_PATCH'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text()
anchor = '''  if [[ -n "$arg_container_engine" ]]; then
    check_container_engine "$arg_container_engine" "$steamrt_image" || die "Specified container engine \\"$arg_container_engine\\" doesn't work"
'''
if text.count(anchor) != 1:
    raise SystemExit(
        "ERROR: configure.sh no longer has the container-engine check this "
        "patches; it has moved or changed, so rebase it rather than guessing.")
guarded = '''  if [ "$arg_container_engine" != "none" ]; then
''' + anchor
text = text.replace(anchor, guarded, 1)

# Close the guard after the discovery block it wraps.
tail = '''        die "${arg_container_engine:-Container engine discovery} has failed. Please fix your setup."
    fi
  fi
'''
if text.count(tail) != 1:
    raise SystemExit("ERROR: configure.sh engine discovery block has changed shape")
text = text.replace(tail, tail + "  fi\n", 1)
path.write_text(text)
EOF_PATCH
fi

# --- build -----------------------------------------------------------------
IMAGE="$(make --silent "SRCDIR=$SRC" --file "$SRC/Makefile.in" TARGET_ARCH=x86_64 \
    get-steamrt-image 2>/dev/null || true)"
if [[ -z "$IMAGE" ]]; then
    printf 'ERROR: could not read STEAMRT_IMAGE out of %s/Makefile.in\n' "$SRC" >&2
    exit 1
fi
# Proton's Makefile passes this inward when it re-enters the container, which is
# the half we skip: MFLAGS carries BASE_SOURCE_DATE_EPOCH, and without it the
# CONTAINER=1 branch computes every per-arch timestamp from an empty string.
# That surfaces as `expr: syntax error` at the top of the log and, much later,
# a spirv-tools generator dying on int('') -- an hour in, for a missing variable.
#
# The tag's commit time rather than `date +%s`: the point of SOURCE_DATE_EPOCH
# is a build that does not change just because the clock did.
EPOCH="$(git -C "$SRC" show -s --format=%ct HEAD 2>/dev/null || date +%s)"

printf '==> building %s in %s\n' "$NAME" "$IMAGE"

userns=()
if [[ "$ENGINE_SPEC" == *podman* ]] \
   && [[ "$("${ENGINE[@]}" info --format '{{.Host.Security.Rootless}}' 2>/dev/null)" == true ]]; then
    userns=(--userns=keep-id)
fi

# A build directory is single-use unless told otherwise. Proton's source rule
# rsyncs each component from its pristine submodule with --delete, so a second
# run through the same directory removes the autoreconf output (configure,
# aclocal.m4, build-aux/missing) while the configure stamps still look
# satisfied, and automake then tries to regenerate through a script that is no
# longer there. Found the hard way; ccache is what makes starting over cheap.
BUILD="$SRC/../build-$NAME"
if [[ "$KEEP_BUILD" != true ]]; then
    rm -rf -- "$BUILD"
fi
mkdir -p -- "$BUILD"
BUILD="$(cd -- "$BUILD" && pwd)"
# A path is mounted as one; a bare name is a volume the engine manages.
if [[ "$CCACHE_VOLUME" == */* ]]; then
    mkdir -p -- "$CCACHE_VOLUME"
    CCACHE_VOLUME="$(cd -- "$CCACHE_VOLUME" && pwd)"
fi

"${ENGINE[@]}" run --rm \
    "${userns[@]}" \
    --security-opt label=disable \
    -v "$SRC:$SRC" \
    -v "$BUILD:$BUILD" \
    -v "$CCACHE_VOLUME:/ccache" \
    -w "$BUILD" \
    -e HOME="$BUILD" \
    -e CCACHE_DIR=/ccache \
    "$IMAGE" bash -euo pipefail -c "
        # Proton's Makefile asks `cc` which compiler this is, once, and derives
        # the whole matched set from the answer. So answer it here.
        # /usr/bin, not whatever is first on PATH: the image puts ccache
        # wrappers ahead of it, and a ccache wrapper dispatches on the name it
        # is invoked as -- so a 'cc' symlink pointing at ccache's 'clang' comes
        # straight back as gcc, and the Makefile picks its GCC branch anyway.
        mkdir -p '$BUILD/toolchain'
        ln -sf '/usr/bin/$BUILD_CC' '$BUILD/toolchain/cc'
        ln -sf '/usr/bin/$BUILD_CC++' '$BUILD/toolchain/c++'
        export PATH='$BUILD/toolchain':\"\$PATH\"
        printf '==> building with %s\\n' \"\$(cc --version | head -1)\"

        # configure.sh runs under set -u and only assigns this while probing a
        # container engine, which --container-engine=none skips. CachyOS's
        # PKGBUILD passes it the same way for the same reason. It feeds
        # DOCKER_OPTS, which a CONTAINER=1 build never uses.
        export CFLAGS='-O3 -march=$MARCH -mtune=$MTUNE'
        export CXXFLAGS=\"\$CFLAGS\"
        export RUSTFLAGS='-C opt-level=3 -C target-cpu=$MARCH'
        export LDFLAGS='-Wl,-O1,--sort-common,--as-needed'
        ROOTLESS_CONTAINER='' \
        '$SRC/configure.sh' \
            --container-engine=none \
            --proton-sdk-image='' \
            --build-name='$NAME'
        make CONTAINER=1 -j'$JOBS' ENABLE_CCACHE=1 \
            BASE_SOURCE_DATE_EPOCH='$EPOCH' \
            dist
    "

[[ -d "$BUILD/dist" ]] || { printf 'ERROR: no dist/ after the build\n' >&2; exit 1; }

printf '==> packing %s\n' "$OUT"
mkdir -p -- "$(dirname -- "$OUT")"
tar -C "$BUILD" -caf "$OUT" dist
printf '    %s (%s)\n' "$OUT" "$(du -h "$OUT" | cut -f1)"
