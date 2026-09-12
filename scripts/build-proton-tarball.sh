#!/usr/bin/env bash
# Build the FSR4 Proton tools locally and emit a tarball per tool.
#
# This is the private-distribution path: it produces
#
#     <toolname>.tar.gz
#
# which unpacks straight into ~/.local/share/Steam/compatibilitytools.d/ and
# needs no pacman, no repository and no root. The build itself is the same one
# CI runs -- the same package scripts in the same archlinux container -- so a
# tarball built here contains the same payload as the published package.
#
#   scripts/build-proton-tarball.sh --suffix test1 native
#   scripts/build-proton-tarball.sh --suffix test1 both
#   scripts/build-proton-tarball.sh --suffix test2 --repack-only native
#
# --repack-only skips the container entirely and re-wraps whatever that
# component last built into out/repo. It is how you hand the same build out
# under a second name, or retry a tarball, without paying for the build again.
#
# --suffix renames the tool so it sits beside whatever is already installed
# rather than replacing it: proton-cachyos-native-bc250-test1 appears as its own
# entry in Steam, with its own per-game selection, and the packaged version
# keeps working. Steam stores the tool name per game, so a tarball built with a
# different suffix is a different tool as far as Steam is concerned.
#
# Custom patches: drop .patch files into
#
#     local-patches/proton-cachyos-native/   applied to the Proton source tree
#     local-patches/protonge-latest/         applied to the unpacked GE tree
#
# They are applied in sorted order with `patch -Np1`, after everything this
# repository already applies, and a failure stops the build. Note the asymmetry:
# proton-cachyos-native is compiled from source, so a patch there can change
# Proton or Wine itself; protonge-latest repacks a prebuilt release, so patches
# there can only edit files that already exist in it.
set -Eeuo pipefail

# Silence is what made the first failure here hard to read: the pacman steps
# below hide their stdout, so errexit would otherwise abort with nothing but a
# non-zero status to go on. Name the line and the command instead.
trap 'status=$?; printf "\nERROR: %s failed at line %s (exit %s): %s\n" \
    "${BASH_SOURCE[0]:-$0}" "$LINENO" "$status" "$BASH_COMMAND" >&2' ERR

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${BC250_BUILD_IMAGE:-docker.io/library/archlinux:base-devel}"
ENGINE_SPEC="${BC250_CONTAINER_ENGINE:-podman}"
# Split on whitespace so the engine can carry its own prefix, which is what
# "sudo podman" or a sandboxed "flatpak-spawn --host podman" need.
read -r -a ENGINE <<< "$ENGINE_SPEC"
SUFFIX=""
OUT_DIR="${ROOT_DIR}/dist"
TARGETS=()
REPACK_ONLY=false

usage() {
    # The header comment above is the help text, however long it grows.
    awk 'NR > 1 { if (!/^#/) exit; sub(/^# ?/, ""); print }' "${BASH_SOURCE[0]}"
    exit "${1:-0}"
}

while (( $# )); do
    case "$1" in
        --suffix) SUFFIX="${2:?--suffix needs a value}"; shift 2 ;;
        --out)    OUT_DIR="${2:?--out needs a value}"; shift 2 ;;
        --image)  IMAGE="${2:?--image needs a value}"; shift 2 ;;
        --repack-only) REPACK_ONLY=true; shift ;;
        -h|--help) usage 0 ;;
        ge|native|both) TARGETS+=("$1"); shift ;;
        *) printf 'ERROR: unexpected argument: %s\n\n' "$1" >&2; usage 1 ;;
    esac
done

(( ${#TARGETS[@]} )) || TARGETS=(both)
COMPONENTS=()
for target in "${TARGETS[@]}"; do
    case "$target" in
        both)   COMPONENTS+=(protonge-latest-bc250 proton-cachyos-native-bc250) ;;
        ge)     COMPONENTS+=(protonge-latest-bc250) ;;
        native) COMPONENTS+=(proton-cachyos-native-bc250) ;;
    esac
done
# `ge native` and `both ge` both name GE once as far as the build is concerned.
readarray -t COMPONENTS < <(printf '%s\n' "${COMPONENTS[@]}" | awk '!seen[$0]++')

# A suffix has to survive being a directory name, a Steam-internal tool name and
# a tarball name, so keep it to what all three accept without quoting.
if [[ -n "$SUFFIX" && ! "$SUFFIX" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
    printf 'ERROR: --suffix must start alphanumeric and contain only [A-Za-z0-9._-]: %s\n' \
        "$SUFFIX" >&2
    exit 1
fi

# Resolve the extractor before anything expensive starts. This step runs on the
# host, not in the container, and a native build that dies here has already
# burned an hour: the first report of this was exactly that, on a Fedora host
# where bsdtar is not installed by default. bsdtar is the one that needs no
# helper binary; GNU tar can do it too, but shells out to zstd, so both halves
# of that route are checked here rather than assumed.
EXTRACT=()
if command -v bsdtar >/dev/null 2>&1; then
    EXTRACT=(bsdtar -xf)
elif tar --help 2>/dev/null | grep -q -- --zstd && command -v zstd >/dev/null 2>&1; then
    EXTRACT=(tar --zstd -xf)
else
    printf 'ERROR: need bsdtar, or GNU tar with a zstd binary, to unpack the package.\n' >&2
    printf '       Fedora: sudo dnf install bsdtar   (or zstd, for the tar route)\n' >&2
    printf '       Arch/CachyOS: sudo pacman -S --needed libarchive\n' >&2
    exit 1
fi

# Same reasoning for the rest of the post-build step: it rewrites the tool's vdf
# and writes the tarball, and finding any of that missing afterwards is finding
# it at the worst possible moment.
for tool in python3 tar; do
    command -v "$tool" >/dev/null 2>&1 || {
        printf 'ERROR: %s is needed to repack the built package.\n' "$tool" >&2
        exit 1
    }
done

if [[ "$REPACK_ONLY" == true ]]; then
    printf '==> repacking the last local build, without rebuilding\n'
else
    command -v "${ENGINE[0]}" >/dev/null 2>&1 || {
        printf 'ERROR: %s is not installed. Set BC250_CONTAINER_ENGINE=docker to use docker.\n' \
            "${ENGINE[0]}" >&2
        exit 1
    }

    container="bc250-local-$$"
    cleanup() { "${ENGINE[@]}" rm -f "$container" >/dev/null 2>&1 || true; }
    trap cleanup EXIT INT TERM

    # Rootless podman maps the invoking user to root inside the container, which
    # would leave every file the build writes into the checkout owned by a subuid on
    # the host. keep-id maps the user to itself instead, so the build user inside can
    # be given the same uid and the checkout stays the user's own.
    userns=()
    if [[ "$ENGINE_SPEC" == *podman* ]] \
       && [[ "$("${ENGINE[@]}" info --format '{{.Host.Security.Rootless}}' 2>/dev/null)" == true ]]; then
        userns=(--userns=keep-id)
    fi

    printf '==> starting %s (%s)\n' "$container" "$IMAGE"
    # label=disable rather than a :Z mount: :Z would recursively relabel the user's
    # checkout for SELinux, which is a persistent change to their working tree for
    # the sake of a container they started themselves to compile their own code. It
    # is a no-op where SELinux is not enabled, which includes the Arch host this
    # normally runs on. The ccache volume is what makes a second native build
    # minutes rather than hours, so it is worth keeping between runs.
    "${ENGINE[@]}" run -d --name "$container" \
        "${userns[@]}" \
        --user 0 \
        --security-opt label=disable \
        -v "${ROOT_DIR}:/workspace" \
        -v bc250-local-ccache:/ccache \
        -w /workspace \
        -e CCACHE_DIR=/ccache \
        -e CCACHE_COMPILERCHECK=content \
        -e BC250_LOCAL_PATCHES=1 \
        "$IMAGE" sleep infinity >/dev/null

    "${ENGINE[@]}" exec "$container" bash /workspace/scripts/local-build-inside.sh "${COMPONENTS[@]}"
fi

mkdir -p -- "$OUT_DIR"
for component in "${COMPONENTS[@]}"; do
    # Newest by mtime: version strings do not sort usefully, and a stale
    # package from an earlier run is exactly the thing not to ship.
    # `|| true` because pipefail turns the empty case into a hard failure before
    # the message below can explain it -- which is precisely the case where an
    # explanation is wanted, e.g. --repack-only with nothing built yet.
    package="$(ls -t -- "${ROOT_DIR}/out/repo/${component}"-*.pkg.tar.zst 2>/dev/null | head -n1 || true)"
    [[ -n "$package" ]] || {
        printf 'ERROR: %s produced no package\n' "$component" >&2
        exit 1
    }
    toolname="$component${SUFFIX:+-$SUFFIX}"
    staging="$(mktemp -d)"

    printf '==> repacking %s as %s\n' "$(basename "$package")" "$toolname"
    # The licences come along because packaging moves them out of the tool
    # directory into /usr/share/licenses, which a tarball has no equivalent of;
    # upstream Proton ships them inside the tool, so put them back there.
    "${EXTRACT[@]}" "$package" -C "$staging" \
        "usr/share/steam/compatibilitytools.d/${component}" \
        "usr/share/licenses/${component}"
    mv -- "$staging/usr/share/steam/compatibilitytools.d/${component}" \
          "$staging/${toolname}"
    if [[ -d "$staging/usr/share/licenses/${component}" ]]; then
        mv -- "$staging/usr/share/licenses/${component}"/* "$staging/${toolname}/"
    fi

    # Steam keys the per-game choice on the internal name, so renaming the
    # directory alone would leave two tools claiming one identity.
    python3 - "$staging/${toolname}/compatibilitytool.vdf" "$component" "$toolname" <<'EOF_VDF'
import re, sys
path, old, new = sys.argv[1:4]
with open(path, encoding="utf-8") as handle:
    text = handle.read()
if old not in text:
    raise SystemExit(f"ERROR: {path} does not name {old}; refusing to guess")
text = text.replace(f'"{old}"', f'"{new}"')
# Make the display name say which build this is, so two entries in Steam's list
# are told apart by reading them rather than by remembering the order.
if new != old:
    text = re.sub(r'("display_name"\s*")([^"]*)(")',
                  lambda m: m.group(1) + m.group(2) + f" [{new.rsplit('-', 1)[-1]}]" + m.group(3),
                  text, count=1)
with open(path, "w", encoding="utf-8") as handle:
    handle.write(text)
EOF_VDF

    tarball="${OUT_DIR}/${toolname}.tar.gz"
    tar -C "$staging" -czf "$tarball" "$toolname"
    rm -rf -- "$staging"
    printf '    %s (%s)\n' "$tarball" "$(du -h "$tarball" | cut -f1)"
done

cat <<EOF_DONE

==> done. Install privately with:

    mkdir -p ~/.local/share/Steam/compatibilitytools.d
    tar -C ~/.local/share/Steam/compatibilitytools.d -xzf <tarball>

Then restart Steam. The tool appears under Properties -> Compatibility.

A tarball is only the compatibility tool, so the packaged
/usr/lib/modules-load.d entry that loads ntsync at boot is not part of it. If
neither Proton package is installed from the repository, load it yourself:

    echo ntsync | sudo tee /etc/modules-load.d/ntsync.conf
    sudo modprobe ntsync
EOF_DONE
