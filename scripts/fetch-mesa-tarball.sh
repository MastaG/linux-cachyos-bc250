#!/usr/bin/env bash
# Pre-fetch the upstream Mesa release tarball into a prepared build directory,
# and make sure the PKGBUILD's declared checksums actually describe that file.
#
# archive.mesa3d.org (annarchy.freedesktop.org) has been intermittently
# unreachable, answering roughly one request in five while port 443 hangs on
# the rest. makepkg gives up after a few attempts and the whole build fails,
# which has broken this repository's builds repeatedly.
#
# Downloading the tarball ourselves with a long retry budget turns that from a
# hard failure into a slow success.
#
# The checksum half exists because of upstream CachyOS commit c442588745
# ("mesa: 26.2.5-2", 2026-10-22), which bumped mesa and mesa/lib32-mesa in one
# commit and declared TWO DIFFERENT sha256 for the same
# "https://archive.mesa3d.org/mesa-$_pkgver.tar.xz": 794b3d17... in mesa and
# dca42e0c... in lib32-mesa. The file on the host is 794b3d17... (measured, and
# Mesa's own release notes agree), so lib32-mesa failed its validity check on
# five consecutive runs while a complete 68,652,756-byte download sat in the
# build directory. makepkg's only message for that is
# "One or more files did not pass the validity check!", which is how a wrong
# number in a PKGBUILD came to look like a bad mirror.
#
# The same commit also wrote a wrong *b2sums* entry in lib32-mesa
# (347f1e11... where the file is cfcc4d72...), and that is what killed the first
# run after the sha256 fix: the rewritten sha256 validated, makepkg then went on
# to "Validating source files with b2sums" and failed there. So the rule is now
# the general one -- once Mesa's release notes confirm the file, THE FILE IS THE
# AUTHORITY FOR EVERY CHECKSUM ARRAY the PKGBUILD declares for that source
# entry, and each of them is recomputed from the verified file.
#
# So: the declared sums are trusted first (cheap, and they are right most of the
# time). On a mismatch in any array the download is checked against MESA ITSELF
# -- the SHA256 line in https://docs.mesa3d.org/relnotes/<pkgver>.html, plus its
# SHA512 line when the page has one, which is the second opinion that makes
# rewriting safe -- and only if the file matches what Mesa published is the
# PKGBUILD rewritten. A sibling PKGBUILD's sum is deliberately NOT an authority:
# both files were wrong-ish in different ways before, and only upstream's release
# notes say what the tarball is. If Mesa's own sums do not match either, the build
# fails here, loudly, with every digest in hand, rather than after a 40-minute
# compile.
#
# Usage: fetch-mesa-tarball.sh <build-dir> [<cachyos-pkgbuild-commit>]
# The PKGBUILD in <build-dir> supplies the version; nothing is hardcoded here.
# The optional commit is only named in the warning, to point at the packaging
# change that introduced a mismatch.
#
# Test seam: BC250_MESA_RELNOTES_HTML=<file> reads Mesa's checksums from that
# file instead of the network. BC250_SKIP_MESA_PREFETCH=1 leaves the download
# (and therefore this check) to makepkg, as before.
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
CHECKER="${ROOT_DIR}/scripts/check-mesa-source-sums.py"

BUILD_DIR="${1:?build directory is required}"
UPSTREAM_COMMIT="${2:-unknown}"
PKGBUILD="${BUILD_DIR}/PKGBUILD"
[[ -f "$PKGBUILD" ]] || {
    printf 'ERROR: no PKGBUILD in %s\n' "$BUILD_DIR" >&2
    exit 1
}
[[ -f "$CHECKER" ]] || {
    printf 'ERROR: missing %s\n' "$CHECKER" >&2
    exit 1
}

# pkgver=26.2.1 and _pkgver=${pkgver/[a-z]/-&}, i.e. a release-candidate suffix
# gets a dash inserted (26.2.1rc1 -> 26.2.1-rc1). Reproduce that here.
pkgver="$(sed -n 's/^pkgver=\(.*\)$/\1/p' "$PKGBUILD" | head -n1)"
[[ -n "$pkgver" ]] || {
    printf 'ERROR: could not read pkgver from %s\n' "$PKGBUILD" >&2
    exit 1
}
_pkgver="$(sed -E 's/([a-z])/-\1/' <<<"$pkgver")"

tarball="mesa-${_pkgver}.tar.xz"
url="https://archive.mesa3d.org/${tarball}"
dest="${BUILD_DIR}/${tarball}"
relnotes_url="https://docs.mesa3d.org/relnotes/${pkgver}.html"
envfile="${BUILD_DIR}/bc250-mesa-tarball.env"

# Escape hatch for local work: during an outage the retry budget below can take
# twenty minutes, which is right for CI and painful when hand-running a prepare
# script. Set BC250_SKIP_MESA_PREFETCH=1 to leave the download to makepkg -- and
# with it the checksum check, so a wrong declared sum fails in makepkg instead.
if [[ -n "${BC250_SKIP_MESA_PREFETCH:-}" ]]; then
    printf '==> BC250_SKIP_MESA_PREFETCH set; leaving the tarball to makepkg\n'
    exit 0
fi

# Only bother if the PKGBUILD actually pulls this tarball; if upstream ever
# switches to a git source this becomes a no-op instead of a failure.
if ! grep -q 'archive\.mesa3d\.org' "$PKGBUILD"; then
    printf '==> PKGBUILD does not use archive.mesa3d.org; skipping pre-fetch\n'
    exit 0
fi

if [[ -s "$dest" ]]; then
    # Present is not the same as correct: CI reuses build directories, and the
    # file that matters here was a complete download with the wrong declared
    # sum. Either way the checksum below still has to agree with the PKGBUILD.
    printf '==> %s already present; checking it against the PKGBUILD\n' "$tarball"
else
    printf '==> Pre-fetching %s (long retry budget; the host is frequently down)\n' "$url"
    if ! curl -fL --output "$dest" \
            --retry 20 --retry-all-errors --retry-delay 15 --retry-max-time 1200 \
            --connect-timeout 20 --speed-time 60 --speed-limit 1024 \
            "$url"; then
        # Leave the decision to makepkg rather than failing the build here: it may
        # still succeed on its own, and a partial file must not be left behind.
        rm -f -- "$dest"
        printf 'WARNING: could not pre-fetch %s; letting makepkg try instead\n' "$tarball" >&2
        exit 0
    fi
    printf '==> Pre-fetched %s (%s bytes)\n' "$tarball" "$(stat -c%s "$dest")"
fi

actual="$(sha256sum "$dest" | awk '{print $1}')"
bytes="$(stat -c%s "$dest")"
declared="$(python3 -B "$CHECKER" declared "$PKGBUILD" archive.mesa3d.org 2>/dev/null || true)"
if [[ ! "$declared" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'ERROR: could not read the tarball sha256 the PKGBUILD declares\n' >&2
    printf '       measured %s (%s bytes)\n' "$actual" "$bytes" >&2
    exit 1
fi

write_env() {
    # Picked up by scripts/prepare-*-mesa-pkgbuild.sh into the component's build
    # env file, so a run log shows which checksum was accepted and on whose
    # authority -- the answer to "why did the PKGBUILD change under us".
    cat > "$envfile" <<EOF_TARBALL
MESA_TARBALL=${tarball}
MESA_TARBALL_BYTES=${bytes}
MESA_TARBALL_SHA256=${actual}
MESA_TARBALL_SUM_SOURCE=${1}
MESA_TARBALL_RELNOTES_URL=${relnotes_url}
MESA_TARBALL_UPSTREAM_COMMIT=${UPSTREAM_COMMIT}
EOF_TARBALL
    shift
    # Whatever the caller passes as extra arguments lands in the file too, one
    # KEY=value per line: which arrays were replaced, with what they disagreed,
    # and the second digest Mesa's page gave us.
    for kv in "$@"; do
        printf '%s\n' "$kv" >> "$envfile"
    done
}

# Every checksum array this PKGBUILD declares for this source, compared with the
# file. An empty answer means the PKGBUILD describes the file exactly, which is
# the normal case and needs no authority but its own.
mismatch_out="$(python3 -B "$CHECKER" mismatch "$PKGBUILD" archive.mesa3d.org "$dest")" || {
    printf 'ERROR: cannot read the declared checksums of %s\n' "$PKGBUILD" >&2
    printf '%s\n' "$mismatch_out" >&2
    exit 1
}

if [[ -z "$mismatch_out" ]]; then
    write_env pkgbuild-declared
    printf '==> Checksum matches the PKGBUILD (%s)\n' "$actual"
    exit 0
fi

# MISMATCH <array> <index> <declared> <measured>, one per disagreeing array.
mapfile -t mismatches <<<"$mismatch_out"
for line in "${mismatches[@]}"; do
    [[ -n "$line" ]] || continue
    read -r _tag _array _index want got <<<"$line"
    printf '==> PKGBUILD declares %s for %s, the file is %s; asking Mesa\n' \
        "$want" "$tarball" "$got" >&2
done

page="${BC250_MESA_RELNOTES_HTML:-}"
if [[ -z "$page" ]]; then
    page="$(mktemp)"
    if ! curl -fsSL --retry 5 --retry-all-errors --connect-timeout 20 --max-time 300 \
            -o "$page" "$relnotes_url"; then
        printf 'ERROR: %s is unreachable, so the mismatch cannot be adjudicated\n' \
            "$relnotes_url" >&2
        printf '       PKGBUILD declares %s, the download is %s (%s bytes)\n' \
            "$declared" "$actual" "$bytes" >&2
        exit 1
    fi
fi

published_lines="$(python3 -B "$CHECKER" published "$page" "$tarball" 2>/dev/null || true)"
published="$(sed -n 's/^sha256=//p' <<<"$published_lines")"
published_sha512="$(sed -n 's/^sha512=//p' <<<"$published_lines")"
if [[ ! "$published" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'ERROR: %s lists no SHA256 for %s, so the mismatch cannot be adjudicated\n' \
        "$relnotes_url" "$tarball" >&2
    printf '       PKGBUILD declares %s, the download is %s (%s bytes)\n' \
        "$declared" "$actual" "$bytes" >&2
    exit 1
fi

if [[ "$actual" != "$published" ]]; then
    # Neither the packaging nor the tarball agrees with Mesa: something changed
    # upstream again, or the download is corrupt. Say so in one place, now.
    printf 'ERROR: %s does not match the checksum Mesa publishes\n' "$tarball" >&2
    printf '       Mesa publishes   %s (%s)\n' "$published" "$relnotes_url" >&2
    printf '       PKGBUILD declares %s\n' "$declared" >&2
    printf '       download is       %s (%s bytes)\n' "$actual" "$bytes" >&2
    exit 1
fi

if [[ -n "$published_sha512" ]]; then
    measured_sha512="$(sha512sum "$dest" | awk '{print $1}')"
    if [[ "$measured_sha512" != "$published_sha512" ]]; then
        # The page gives a second digest and it disagrees: the file is not Mesa's
        # release, so it is not an authority for rewriting anything either.
        printf 'ERROR: %s matches Mesa'\''s SHA256 but not the SHA512 Mesa publishes\n' \
            "$tarball" >&2
        printf '       Mesa publishes   sha256 %s, sha512 %s (%s)\n' \
            "$published" "$published_sha512" "$relnotes_url" >&2
        printf '       download is      sha256 %s, sha512 %s (%s bytes)\n' \
            "$actual" "$measured_sha512" "$bytes" >&2
        exit 1
    fi
fi

# The file is what Mesa released, so every array that disagrees with it is the
# wrong side. Rewrite them all and shout once, naming each, because this is an
# upstream packaging bug that will bite every builder of that PKGBUILD until it
# is fixed.
sync_out="$(python3 -B "$CHECKER" sync "$PKGBUILD" archive.mesa3d.org "$dest")" || {
    printf 'ERROR: could not rewrite the declared sums in %s\n' "$PKGBUILD" >&2
    printf '%s\n' "$sync_out" >&2
    exit 1
}
mapfile -t sync_lines <<<"$sync_out"
replaced=()
for line in "${sync_lines[@]}"; do
    if [[ "$line" == REPLACED\ * ]]; then
        replaced+=( "$line" )
    fi
done
[[ ${#replaced[@]} -gt 0 ]] || {
    printf 'ERROR: the sums disagreed but nothing was rewritten in %s\n' "$PKGBUILD" >&2
    exit 1
}

env_extra=(
    "MESA_TARBALL_REPLACED_ARRAYS=$(printf '%s\n' "${replaced[@]}" |
        awk '{print $2}' | paste -sd, -)"
)
for line in "${replaced[@]}"; do
    read -r _tag array index old _new <<<"$line"
    env_extra+=(
        "MESA_TARBALL_REJECTED_SUM_$(tr '[:lower:]' '[:upper:]' <<<"${array}")=$old"
    )
    # The bare key stays the sha256 one: that is the key the 2026-10-23 incident
    # is greped for, and the sha256 array is the one Mesa's page can vouch for.
    if [[ "$array" == sha256sums ]]; then
        env_extra+=("MESA_TARBALL_REJECTED_SUM=$old")
    fi
done
if [[ -n "${measured_sha512:-}" ]]; then
    env_extra+=("MESA_TARBALL_SHA512_MATCHES_MESA=Y")
fi

write_env mesa-relnotes "${env_extra[@]}"

{
    printf 'WARNING: %s does not describe %s in %d declared array(s) and all of them were replaced\n' \
        "$PKGBUILD" "$tarball" "${#replaced[@]}"
    for line in "${replaced[@]}"; do
        read -r _tag array index old new <<<"$line"
        printf '         %s[%s]: %s -> %s\n' "$array" "$index" "$old" "$new"
    done
    printf '         sha256 of the file: %s  (= what Mesa publishes, %s)\n' \
        "$actual" "$relnotes_url"
    printf '         packaging commit: %s\n' "$UPSTREAM_COMMIT"
    printf '         Report it upstream so this warning goes away; makepkg would\n'
    printf '         otherwise fail with "did not pass the validity check!" after a\n'
    printf '         full download and no hint of which side is wrong.\n'
} >&2
