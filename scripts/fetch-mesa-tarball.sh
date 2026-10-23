#!/usr/bin/env bash
# Pre-fetch the upstream Mesa release tarball into a prepared build directory,
# and make sure the PKGBUILD's declared sha256 actually describes that file.
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
# So: the declared sum is trusted first (cheap, and it is right most of the
# time). On a mismatch the download is checked against MESA ITSELF -- the
# SHA256 line in https://docs.mesa3d.org/relnotes/<pkgver>.html -- and only if
# the file matches what Mesa published is the PKGBUILD rewritten. A sibling
# PKGBUILD's sum is deliberately NOT an authority: both files were wrong-ish in
# different ways before, and only upstream's release notes say what the tarball
# is. If Mesa's own sum does not match either, the build fails here, loudly,
# with expected and observed digests, rather than after a 40-minute compile.
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
}

if [[ "$actual" == "$declared" ]]; then
    write_env pkgbuild-declared
    printf '==> Checksum matches the PKGBUILD (%s)\n' "$actual"
    exit 0
fi

printf '==> PKGBUILD declares %s for %s, the file is %s; asking Mesa\n' \
    "$declared" "$tarball" "$actual" >&2

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

published="$(python3 -B "$CHECKER" published "$page" "$tarball" 2>/dev/null || true)"
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

# The file is what Mesa released; the PKGBUILD's number is wrong. Rewrite it and
# shout, because this is an upstream packaging bug that will bite every builder
# of that PKGBUILD until it is fixed.
if ! python3 -B "$CHECKER" set "$PKGBUILD" archive.mesa3d.org "$actual"; then
    printf 'ERROR: could not rewrite the declared sum in %s\n' "$PKGBUILD" >&2
    exit 1
fi
write_env mesa-relnotes
# Keep the rejected value in the record too; the summary line is the one a human
# reads, the env file is the one a later agent greps.
printf 'MESA_TARBALL_REJECTED_SUM=%s\n' "$declared" >> "$envfile"

{
    printf 'WARNING: the declared sha256 in %s does not describe %s and was replaced\n' \
        "$PKGBUILD" "$tarball"
    printf '         declared: %s\n' "$declared"
    printf '         measured: %s  (= what Mesa publishes, %s)\n' "$actual" "$relnotes_url"
    printf '         packaging commit: %s\n' "$UPSTREAM_COMMIT"
    printf '         Report it upstream so this warning goes away; makepkg would\n'
    printf '         otherwise fail with "did not pass the validity check!" after a\n'
    printf '         full download and no hint of which side is wrong.\n'
} >&2
