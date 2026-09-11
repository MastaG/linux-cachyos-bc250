#!/usr/bin/env bash
# Container side of scripts/build-proton-tarball.sh. Not meant to be run by hand.
#
# Deliberately not ci-build.sh: that entry point exists to decide what changed
# and to publish it, so it wants a fingerprint for every component and a release
# to compare against. A local build wants neither -- it builds what it was asked
# for, every time. What it does copy from ci-build.sh is the environment the
# packages are built in, so the tool that comes out is the one CI would have
# produced, plus whatever is in local-patches/.
set -Eeuo pipefail

COMPONENTS=("$@")
(( ${#COMPONENTS[@]} )) || { printf 'ERROR: no components given\n' >&2; exit 1; }

want() { [[ " ${COMPONENTS[*]} " == *" $1 "* ]]; }

# proton-cachyos-native links 32-bit libraries, so its makedepends cannot be
# resolved without multilib. GE ships prebuilt and does not care, but enabling
# it unconditionally keeps this identical to the CI container.
if ! grep -Eq '^[[:space:]]*\[multilib\][[:space:]]*$' /etc/pacman.conf; then
    cat >> /etc/pacman.conf <<'EOF_MULTILIB'

[multilib]
Include = /etc/pacman.d/mirrorlist
EOF_MULTILIB
fi

printf '==> installing build dependencies\n'
pacman -Syy --noconfirm >/dev/null
# The base image's keyring is as old as the image, which is what breaks a
# container that has sat unused for a few months.
pacman -S --noconfirm --needed archlinux-keyring >/dev/null
pacman -Syu --noconfirm --needed base-devel ccache curl git libarchive python sudo >/dev/null

# The checkout is a bind mount of the user's own repository, so it has to come
# out of this build owned by the user, exactly as it went in. Rather than
# chowning it -- which under rootless podman would hand it to a subuid and lock
# the user out of their own files -- the build user is created with the uid the
# mount already has. Everything makepkg writes into out/ and build/ then lands
# with the right owner on the host.
owner_uid="$(stat -c %u /workspace)"
owner_gid="$(stat -c %g /workspace)"
if [[ "$owner_uid" == 0 ]]; then
    printf 'ERROR: /workspace is owned by root inside the container, and makepkg\n' >&2
    printf '       refuses to run as root. Rootless podman needs --userns=keep-id,\n' >&2
    printf '       which scripts/build-proton-tarball.sh passes for you.\n' >&2
    exit 1
fi

if ! getent group "$owner_gid" >/dev/null; then
    groupadd --gid "$owner_gid" builder
fi
if ! id -u "$owner_uid" >/dev/null 2>&1; then
    useradd --uid "$owner_uid" --gid "$owner_gid" --create-home --shell /bin/bash builder
fi
BUILDER="$(id -nu "$owner_uid")"
BUILDER_HOME="$(getent passwd "$owner_uid" | cut -d: -f6)"
printf '%s ALL=(ALL:ALL) NOPASSWD: ALL\n' "$BUILDER" > /etc/sudoers.d/builder
chmod 0440 /etc/sudoers.d/builder

if want proton-cachyos-native-bc250; then
    # afdko and mingw-w64-tools are AUR-only. This is the same fetch CI does;
    # unlike CI it is fatal here, because a local build was asked for exactly
    # one thing and silently failing later wastes an hour of compiling.
    printf '==> fetching the AUR-only Proton build dependencies\n'
    /workspace/scripts/install-proton-build-deps.sh
fi

# ccache is the difference between minutes and hours on a second native build.
: "${CCACHE_DIR:=/ccache}"
: "${CCACHE_COMPILERCHECK:=content}"
CCACHE_WRAPPER_DIR=/usr/lib/ccache/bin
mkdir -p -- "$CCACHE_DIR"
chown "$owner_uid:$owner_gid" "$CCACHE_DIR"
sed -i 's/!ccache/ccache/g' /etc/makepkg.conf
if ! grep -Eq '^[[:space:]]*BUILDENV=.*[([:space:]]ccache([[:space:]]|\))' /etc/makepkg.conf; then
    printf 'ERROR: failed to enable ccache in /etc/makepkg.conf BUILDENV\n' >&2
    exit 1
fi
[[ -x "$CCACHE_WRAPPER_DIR/gcc" ]] || {
    printf 'ERROR: ccache compiler wrappers not found in %s\n' "$CCACHE_WRAPPER_DIR" >&2
    exit 1
}

for component in "${COMPONENTS[@]}"; do
    case "$component" in
        protonge-latest-bc250)
            script=/workspace/scripts/build-protonge-latest-bc250-package.sh ;;
        proton-cachyos-native-bc250)
            script=/workspace/scripts/build-proton-cachyos-native-bc250-package.sh ;;
        *) printf 'ERROR: unknown component: %s\n' "$component" >&2; exit 1 ;;
    esac

    printf '==> building %s\n' "$component"
    # An explicit environment rather than the caller's: CI deliberately keeps CI
    # and GITHUB_RUN_ID away from makepkg, and the same reasoning applies to
    # whatever a developer happens to have exported.
    runuser -u "$BUILDER" -- env \
        HOME="$BUILDER_HOME" \
        PATH="$CCACHE_WRAPPER_DIR:/usr/local/sbin:/usr/local/bin:/usr/bin" \
        CCACHE_DIR="$CCACHE_DIR" \
        CCACHE_COMPILERCHECK="$CCACHE_COMPILERCHECK" \
        BC250_PKGREL="${BC250_PKGREL:-1}" \
        BC250_LOCAL_PATCHES="${BC250_LOCAL_PATCHES:-0}" \
        BC250_LOCAL_PATCHES_DIR="${BC250_LOCAL_PATCHES_DIR:-/workspace/local-patches}" \
        bash "$script"
done

printf '==> local build finished\n'
