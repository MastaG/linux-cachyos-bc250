#!/usr/bin/env bash
set -Eeuo pipefail

# Invoked several times against one long-lived container, so that the runner can
# publish each component as soon as it builds:
#
#   ci-build.sh setup                 root-side container preparation, once
#   ci-build.sh component <name>      build exactly one component
#   ci-build.sh finalize              validate and write the aggregate files
#
# Splitting it this way is what lets a cancelled or crashed run keep the
# components that already finished: the runner uploads after each `component`
# call rather than only after everything has built.
MODE="${1:?mode is required: setup, component or finalize}"
COMPONENT="${2:-}"
case "$MODE" in
    setup|finalize) ;;
    component) : "${COMPONENT:?component name is required}" ;;
    *) printf 'ERROR: unknown mode: %s\n' "$MODE" >&2; exit 1 ;;
esac

: "${BC250_PKGREL:?BC250_PKGREL is required}"
: "${CACHYOS_MESA_COMMIT:?CACHYOS_MESA_COMMIT is required}"
: "${MESA_GIT_COMMIT:?MESA_GIT_COMMIT is required}"
: "${KERNEL_STABLE_FINGERPRINT:?KERNEL_STABLE_FINGERPRINT is required}"
: "${KERNEL_RC_FINGERPRINT:?KERNEL_RC_FINGERPRINT is required}"
: "${KERNEL_BORE_FINGERPRINT:?KERNEL_BORE_FINGERPRINT is required}"
: "${MESA_FINGERPRINT:?MESA_FINGERPRINT is required}"
: "${LIB32_MESA_FINGERPRINT:?LIB32_MESA_FINGERPRINT is required}"
: "${MESA_GIT_FINGERPRINT:?MESA_GIT_FINGERPRINT is required}"
: "${MESA_TESTING_FINGERPRINT:?MESA_TESTING_FINGERPRINT is required}"
: "${LIB32_MESA_TESTING_FINGERPRINT:?LIB32_MESA_TESTING_FINGERPRINT is required}"
: "${BC250_DUAL_AUDIO_FINGERPRINT:?BC250_DUAL_AUDIO_FINGERPRINT is required}"
: "${LINUX_CACHYOS_BC250_META_FINGERPRINT:?LINUX_CACHYOS_BC250_META_FINGERPRINT is required}"
: "${PROTONGE_LATEST_BC250_FINGERPRINT:?PROTONGE_LATEST_BC250_FINGERPRINT is required}"
: "${PROTON_CACHYOS_NATIVE_BC250_FINGERPRINT:?PROTON_CACHYOS_NATIVE_BC250_FINGERPRINT is required}"

BUILD_KERNEL_STABLE="${BUILD_KERNEL_STABLE:-false}"
BUILD_KERNEL_RC="${BUILD_KERNEL_RC:-false}"
BUILD_KERNEL_BORE="${BUILD_KERNEL_BORE:-false}"
BUILD_MESA="${BUILD_MESA:-false}"
BUILD_LIB32_MESA="${BUILD_LIB32_MESA:-false}"
BUILD_MESA_GIT="${BUILD_MESA_GIT:-false}"
BUILD_MESA_TESTING="${BUILD_MESA_TESTING:-false}"
BUILD_LIB32_MESA_TESTING="${BUILD_LIB32_MESA_TESTING:-false}"
BUILD_BC250_DUAL_AUDIO="${BUILD_BC250_DUAL_AUDIO:-false}"
BUILD_LINUX_CACHYOS_BC250_META="${BUILD_LINUX_CACHYOS_BC250_META:-false}"
BUILD_PROTONGE_LATEST_BC250="${BUILD_PROTONGE_LATEST_BC250:-false}"
BUILD_PROTON_CACHYOS_NATIVE_BC250="${BUILD_PROTON_CACHYOS_NATIVE_BC250:-false}"
NCT6687D_COMMIT="${NCT6687D_COMMIT:-}"
PROTONGE_TAG="${PROTONGE_TAG:-}"

for var in BUILD_KERNEL_STABLE BUILD_KERNEL_RC BUILD_KERNEL_BORE BUILD_MESA BUILD_LIB32_MESA \
           BUILD_MESA_GIT BUILD_MESA_TESTING BUILD_LIB32_MESA_TESTING BUILD_BC250_DUAL_AUDIO \
           BUILD_LINUX_CACHYOS_BC250_META BUILD_PROTONGE_LATEST_BC250 \
           BUILD_PROTON_CACHYOS_NATIVE_BC250; do
    value="${!var}"
    [[ "$value" == true || "$value" == false ]] || {
        printf 'ERROR: %s must be true or false: %s\n' "$var" "$value" >&2
        exit 1
    }
done

if [[ "$BUILD_KERNEL_STABLE" == true || "$BUILD_KERNEL_RC" == true || "$BUILD_KERNEL_BORE" == true ]]; then
    : "${NCT6687D_COMMIT:?NCT6687D_COMMIT is required when a kernel is built}"
fi

if [[ "$MODE" == setup ]]; then

# Stable lib32-mesa and mesa-git's lib32-mesa-git output need Arch multilib.
if ! grep -Eq '^[[:space:]]*\[multilib\][[:space:]]*$' /etc/pacman.conf; then
    cat >> /etc/pacman.conf <<'EOF_MULTILIB'

[multilib]
Include = /etc/pacman.d/mirrorlist
EOF_MULTILIB
fi

pacman -Syy --noconfirm
if ! pacman-conf --repo-list | grep -qx multilib; then
    printf 'ERROR: Arch multilib repository is not enabled in /etc/pacman.conf\n' >&2
    exit 1
fi
if ! pacman -Si lib32-clang >/dev/null 2>&1; then
    printf 'ERROR: multilib is enabled but lib32-clang cannot be resolved\n' >&2
    exit 1
fi

pacman -S --noconfirm --needed archlinux-keyring
pacman -Syu --noconfirm --needed base-devel ccache curl git libarchive sudo

if ! id builder >/dev/null 2>&1; then
    useradd --create-home --shell /bin/bash builder
fi
printf 'builder ALL=(ALL:ALL) NOPASSWD: ALL\n' > /etc/sudoers.d/builder
chmod 0440 /etc/sudoers.d/builder
chown -R builder:builder /workspace

# TEMPORARY: shadow rust-bindgen with 0.72.1 on PATH.
#
# rust-bindgen 0.73.x generates Rust that does not compile for Mesa's rusticl
# frontend. Mesa asks bindgen to render pipe_map_flags and pipe_resource_usage
# as --bitfield-enum, so they become newtypes, and those enums are also C
# bitfield members in p_state.h. 0.73.x emits "let val: u32 = val as _;" in the
# generated bitfield accessors, which is E0605: you cannot "as"-cast a newtype.
# 0.72.1 emitted a transmute there and compiles. Both stable mesa and mesa-git
# enable rusticl, so without this every Mesa component fails to build.
#
# This shadows the binary on PATH rather than pinning the package, because
# pinning cannot survive makepkg. mesa-git names rust-bindgen explicitly in
# makedepends, so --syncdeps runs pacman -S on it by name: IgnorePkg only
# produces an "install anyway?" prompt that --noconfirm answers yes to, and an
# epoch-bumped local package is simply downgraded back to the repo version.
# Both were tried and both failed. Meson resolves bindgen through PATH, so
# putting 0.72.1 ahead of /usr/bin works regardless of what pacman installs.
#
# REMOVE THIS once bindgen or Mesa fixes it upstream: drop this block and the
# BINDGEN_PIN_DIR entry from the PATH below. Leaving it in place indefinitely
# means silently building Mesa against an increasingly stale bindgen.
BINDGEN_PIN_VERSION="0.72.1-3"
BINDGEN_PIN_DIR=/opt/bindgen-pin
BINDGEN_PIN_URL="https://archive.archlinux.org/packages/r/rust-bindgen/rust-bindgen-${BINDGEN_PIN_VERSION}-x86_64.pkg.tar.zst"
if curl -fsSL --retry 3 -o /tmp/rust-bindgen-pin.pkg.tar.zst "$BINDGEN_PIN_URL" &&
   mkdir -p "$BINDGEN_PIN_DIR" &&
   tar -C "$BINDGEN_PIN_DIR" -xf /tmp/rust-bindgen-pin.pkg.tar.zst usr/bin/bindgen &&
   [[ -x "$BINDGEN_PIN_DIR/usr/bin/bindgen" ]]; then
    chmod -R a+rX "$BINDGEN_PIN_DIR"
    printf '==> rust-bindgen %s shadowed on PATH (0.73.x breaks rusticl; see ci-build.sh): %s\n' \
        "$BINDGEN_PIN_VERSION" "$("$BINDGEN_PIN_DIR/usr/bin/bindgen" --version 2>&1)"
else
    BINDGEN_PIN_DIR=""
    printf '::warning title=bindgen shadow failed::could not stage rust-bindgen %s; Mesa components will likely fail to build on rusticl\n' \
        "$BINDGEN_PIN_VERSION"
fi
rm -f /tmp/rust-bindgen-pin.pkg.tar.zst

# proton-cachyos-native's makedepends include two AUR-only packages that a
# vanilla Arch container cannot resolve. Only fetch them when that component is
# actually being built, and treat a failure the way the bindgen shadow is
# treated -- warn and continue, so the other components still build and publish.
if [[ "$BUILD_PROTON_CACHYOS_NATIVE_BC250" == true ]]; then
    if ! /workspace/scripts/install-proton-build-deps.sh; then
        printf '::warning title=Proton build dependencies unavailable::could not install afdko/mingw-w64-tools; proton-cachyos-native-bc250 will fail to build\n'
    fi
fi

# ccache is shared by every makepkg invocation below: all three kernels,
# stable Mesa, stable lib32-mesa and mesa-git/lib32-mesa-git. BUILDENV enables
# makepkg's native integration; prepending the wrapper directory makes the
# compiler routing explicit for Meson and nested build systems as well.
: "${CCACHE_DIR:=/ccache}"
: "${CCACHE_COMPILERCHECK:=content}"
CCACHE_WRAPPER_DIR=/usr/lib/ccache/bin
mkdir -p -- "$CCACHE_DIR"
chown builder:builder "$CCACHE_DIR"

# Size the cache to the machine rather than pinning a number.
#
# The runners do not have the same disk, and the cache volume is per-machine, so
# one hardcoded value is either too small on the big runner or too large on the
# small one. It was 30G, and that was far too small for what shares it: three
# kernels, five Mesa variants and a full Wine/Proton build. Measured on run
# 34263985704 the cache sat at 30.0/30.0 GB with a **0.95% hit rate** -- 25639
# misses out of 25886 cacheable calls -- because every component evicted the
# previous one before it could ever be reused. Every build was effectively cold.
#
# Take a share of what the volume can actually hold (its free space plus what
# the cache already occupies, since that is reclaimable), clamped so a huge disk
# does not hand ccache everything and a small one still gets a usable cache.
# CCACHE_MAXSIZE in the environment overrides this entirely.
if [[ -z "${CCACHE_MAXSIZE:-}" ]]; then
    mkdir -p -- "$CCACHE_DIR"
    _free_gb=$(( $(df -B1G --output=avail "$CCACHE_DIR" | tail -1) ))
    _used_gb=$(( $(du -sBG "$CCACHE_DIR" 2>/dev/null | awk '{print $1+0}') ))
    _usable=$(( _free_gb + _used_gb ))
    CCACHE_MAXSIZE=$(( _usable * 60 / 100 ))
    (( CCACHE_MAXSIZE < 20 )) && CCACHE_MAXSIZE=20
    (( CCACHE_MAXSIZE > 150 )) && CCACHE_MAXSIZE=150
    CCACHE_MAXSIZE="${CCACHE_MAXSIZE}G"
    printf '==> ccache sized to %s (%dG usable on %s: %dG free + %dG already cached)\n' \
        "$CCACHE_MAXSIZE" "$_usable" "$CCACHE_DIR" "$_free_gb" "$_used_gb"
fi
export CCACHE_MAXSIZE

# ccache records max_size in its own config, so setting it once here is enough
# for every component invocation that follows.
runuser -u builder -- ccache -M "$CCACHE_MAXSIZE" >/dev/null
sed -i 's/!ccache/ccache/g' /etc/makepkg.conf
if ! grep -Eq '^[[:space:]]*BUILDENV=.*[([:space:]]ccache([[:space:]]|\))' /etc/makepkg.conf; then
    printf 'ERROR: failed to enable ccache in /etc/makepkg.conf BUILDENV\n' >&2
    grep -n '^[[:space:]]*BUILDENV=' /etc/makepkg.conf >&2 || true
    exit 1
fi
[[ -x "$CCACHE_WRAPPER_DIR/gcc" ]] || {
    printf 'ERROR: ccache compiler wrappers not found in %s\n' "$CCACHE_WRAPPER_DIR" >&2
    exit 1
}

# Self-hosted runners keep the workspace between runs, so clear any marker left
# by a previous run before it can be mistaken for this one.
rm -f /workspace/out/.publish-ready
printf '==> build container prepared\n'
exit 0
fi

# --- component and finalize modes -------------------------------------------
#
# These run against the container `setup` already prepared, so they recompute
# the few paths they need rather than redoing any of that work.
: "${CCACHE_DIR:=/ccache}"
: "${CCACHE_COMPILERCHECK:=content}"

CCACHE_WRAPPER_DIR=/usr/lib/ccache/bin
BINDGEN_PIN_DIR=/opt/bindgen-pin
[[ -x "$BINDGEN_PIN_DIR/usr/bin/bindgen" ]] || BINDGEN_PIN_DIR=""

# Do not pass CI or GITHUB_RUN_ID to makepkg. CachyOS otherwise intentionally
# selects its reduced CI kernel configuration.
runuser -u builder -- env \
    HOME=/home/builder \
    PATH="${BINDGEN_PIN_DIR:+$BINDGEN_PIN_DIR/usr/bin:}$CCACHE_WRAPPER_DIR:$PATH" \
    CCACHE_DIR="$CCACHE_DIR" \
    CCACHE_COMPILERCHECK="$CCACHE_COMPILERCHECK" \
    BUILD_KERNEL_STABLE="$BUILD_KERNEL_STABLE" \
    BUILD_KERNEL_RC="$BUILD_KERNEL_RC" \
    BUILD_KERNEL_BORE="$BUILD_KERNEL_BORE" \
    BUILD_MESA="$BUILD_MESA" \
    BUILD_LIB32_MESA="$BUILD_LIB32_MESA" \
    BUILD_MESA_GIT="$BUILD_MESA_GIT" \
    BUILD_MESA_TESTING="$BUILD_MESA_TESTING" \
    BUILD_LIB32_MESA_TESTING="$BUILD_LIB32_MESA_TESTING" \
    BUILD_BC250_DUAL_AUDIO="$BUILD_BC250_DUAL_AUDIO" \
    BUILD_LINUX_CACHYOS_BC250_META="$BUILD_LINUX_CACHYOS_BC250_META" \
    BUILD_PROTONGE_LATEST_BC250="$BUILD_PROTONGE_LATEST_BC250" \
    BUILD_PROTON_CACHYOS_NATIVE_BC250="$BUILD_PROTON_CACHYOS_NATIVE_BC250" \
    BC250_PKGREL="$BC250_PKGREL" \
    MESA_PKGREL="$BC250_PKGREL" \
    LIB32_MESA_PKGREL="$BC250_PKGREL" \
    MESA_GIT_PKGREL="$BC250_PKGREL" \
    MESA_TESTING_PKGREL="$BC250_PKGREL" \
    LIB32_MESA_TESTING_PKGREL="$BC250_PKGREL" \
    SOURCE_FINGERPRINT="${SOURCE_FINGERPRINT:-componentized}" \
    KERNEL_STABLE_FINGERPRINT="$KERNEL_STABLE_FINGERPRINT" \
    KERNEL_RC_FINGERPRINT="$KERNEL_RC_FINGERPRINT" \
    KERNEL_BORE_FINGERPRINT="$KERNEL_BORE_FINGERPRINT" \
    MESA_FINGERPRINT="$MESA_FINGERPRINT" \
    LIB32_MESA_FINGERPRINT="$LIB32_MESA_FINGERPRINT" \
    MESA_GIT_FINGERPRINT="$MESA_GIT_FINGERPRINT" \
    MESA_TESTING_FINGERPRINT="$MESA_TESTING_FINGERPRINT" \
    LIB32_MESA_TESTING_FINGERPRINT="$LIB32_MESA_TESTING_FINGERPRINT" \
    BC250_DUAL_AUDIO_FINGERPRINT="$BC250_DUAL_AUDIO_FINGERPRINT" \
    LINUX_CACHYOS_BC250_META_FINGERPRINT="$LINUX_CACHYOS_BC250_META_FINGERPRINT" \
    PROTONGE_LATEST_BC250_FINGERPRINT="$PROTONGE_LATEST_BC250_FINGERPRINT" \
    PROTON_CACHYOS_NATIVE_BC250_FINGERPRINT="$PROTON_CACHYOS_NATIVE_BC250_FINGERPRINT" \
    NCT6687D_COMMIT="$NCT6687D_COMMIT" \
    PROTONGE_TAG="$PROTONGE_TAG" \
    CACHYOS_MESA_COMMIT="$CACHYOS_MESA_COMMIT" \
    MESA_GIT_COMMIT="$MESA_GIT_COMMIT" \
    GITHUB_REPOSITORY="${GITHUB_REPOSITORY:-unknown/unknown}" \
    GITHUB_SHA="${GITHUB_SHA:-unknown}" \
    MODE="$MODE" \
    COMPONENT="$COMPONENT" \
    bash -c '
        set -Eeuo pipefail
        echo "==> ccache: persistent cache at $CCACHE_DIR (max $(ccache --get-config max_size 2>/dev/null || echo unknown))"
        echo "==> ccache compiler wrapper: $(command -v gcc)"
        ccache -z >/dev/null
        _ccache_stats() {
            echo "==> ccache statistics for this build"
            ccache -s || true
        }
        trap _ccache_stats EXIT

        # One component per invocation. The runner publishes after each one
        # returns, which is what makes a cancelled or crashed run keep whatever
        # already finished. Reporting a failure belongs to the runner too: it
        # simply moves on to the next component, exactly as the previous
        # single-invocation loop did.
        if [[ "$MODE" == component ]]; then
            case "$COMPONENT" in
                kernel-stable) env CACHYOS_SOURCE_VARIANT=linux-cachyos /workspace/scripts/build-package.sh ;;
                kernel-rc)     env CACHYOS_SOURCE_VARIANT=linux-cachyos-rc /workspace/scripts/build-package.sh ;;
                kernel-bore)   env CACHYOS_SOURCE_VARIANT=linux-cachyos-bore /workspace/scripts/build-package.sh ;;
                mesa)                        /workspace/scripts/build-mesa-package.sh ;;
                lib32-mesa)                  /workspace/scripts/build-lib32-mesa-package.sh ;;
                mesa-git)                    /workspace/scripts/build-mesa-git-package.sh ;;
                mesa-testing)                /workspace/scripts/build-mesa-testing-package.sh ;;
                lib32-mesa-testing)          /workspace/scripts/build-lib32-mesa-testing-package.sh ;;
                bc250-dual-audio)            /workspace/scripts/build-bc250-dual-audio-package.sh ;;
                linux-cachyos-bc250-meta)    /workspace/scripts/build-linux-cachyos-bc250-meta-package.sh ;;
                protonge-latest-bc250)       /workspace/scripts/build-protonge-latest-bc250-package.sh ;;
                proton-cachyos-native-bc250) /workspace/scripts/build-proton-cachyos-native-bc250-package.sh ;;
                *) printf "ERROR: unknown component: %s\\n" "$COMPONENT" >&2; exit 1 ;;
            esac

            # Leave the database describing what is staged right now, so the
            # runner can upload this component and a database that matches it.
            /workspace/scripts/update-repo-db.sh
            exit 0
        fi

        # Self-expiring trigger for the rust-bindgen shadow staged above.
        # If a Mesa component built, pacman has installed the current
        # rust-bindgen at /usr/bin/bindgen alongside our shadowed 0.72.1. Probe
        # it with the exact pattern that breaks rusticl -- a --bitfield-enum
        # newtype used as a C bitfield member -- and say so in the run summary
        # once it compiles again, so the workaround gets removed instead of
        # quietly pinning Mesa to a stale bindgen forever. Entirely fail-soft.
        if [[ -x /usr/bin/bindgen ]] && command -v rustc >/dev/null 2>&1; then
            printf "enum bc250_probe_e { A = 1, B = 2 };\nstruct bc250_probe_s { enum bc250_probe_e f : 24; };\n" > /tmp/bindgen-probe.h
            if /usr/bin/bindgen --default-enum-style rust --bitfield-enum bc250_probe_e \
                   --allowlist-type bc250_probe_s --allowlist-type bc250_probe_e \
                   /tmp/bindgen-probe.h -o /tmp/bindgen-probe.rs -- -x c >/dev/null 2>&1 &&
               rustc --edition 2021 --crate-type rlib /tmp/bindgen-probe.rs \
                   -o /tmp/bindgen-probe.rlib >/dev/null 2>&1; then
                printf "::warning title=bindgen shadow can now be removed::system %s compiles the rusticl pattern again. Drop the BINDGEN_PIN block and its PATH entry in scripts/ci-build.sh.\n" \
                    "$(/usr/bin/bindgen --version 2>&1)"
            else
                printf "==> rust-bindgen shadow still required (system %s still miscompiles the rusticl pattern)\n" \
                    "$(/usr/bin/bindgen --version 2>&1)"
            fi
            rm -f /tmp/bindgen-probe.h /tmp/bindgen-probe.rs /tmp/bindgen-probe.rlib
        fi

        /workspace/scripts/finalize-repository.sh

        # finalize-repository.sh completed, so out/repo is a complete, valid
        # repository: everything that built this run, plus the previously
        # published packages for everything that did not. It is safe to publish
        # even though some components failed. The workflow gates its final
        # publish on this marker.
        mkdir -p /workspace/out && : > /workspace/out/.publish-ready
    '
