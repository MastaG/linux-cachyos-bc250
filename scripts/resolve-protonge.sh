#!/usr/bin/env bash
# Resolve which GE-Proton release protonge-latest-bc250 should package.
#
# Prints an env file naming the tag, the pkgver derived from it, and the SHA256
# of the x86_64 tarball. GE publishes only a .sha512sum next to each tarball, so
# that is the pin we can obtain without downloading half a gigabyte; the PKGBUILD
# verifies the tarball with sha512sums= for exactly that reason.
#
# Set PROTONGE_TAG to package a specific release instead of the newest one.
set -Eeuo pipefail

REPOSITORY="GloriousEggroll/proton-ge-custom"
TAG="${PROTONGE_TAG:-}"

# Plain curl rather than gh: this also runs inside the Arch build container,
# which has no GitHub CLI and no token, and an unauthenticated read of a public
# release is well inside the anonymous rate limit. GH_TOKEN is used when it
# happens to be set, purely for headroom.
#
# A transient API failure must not silently resolve to something else. The build
# cache keys on this tag, so guessing here either rebuilds a ~700 MB package for
# nothing or publishes the wrong Proton.
attempts=5
api() {
    local path="$1" out attempt
    local -a auth=()
    local token="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
    if [[ -n "$token" ]]; then
        auth=(-H "Authorization: Bearer $token")
    fi
    for attempt in $(seq 1 "$attempts"); do
        if out="$(curl -fsSL "${auth[@]}" \
                    -H 'Accept: application/vnd.github+json' \
                    "https://api.github.com/${path}" 2>&1)"; then
            printf '%s\n' "$out"
            return 0
        fi
        printf 'WARN: could not query %s (attempt %d/%d): %s\n' \
            "$path" "$attempt" "$attempts" "${out%%$'\n'*}" >&2
        if (( attempt < attempts )); then sleep $(( attempt * 5 )); fi
    done
    printf 'ERROR: gave up querying %s after %d attempts\n' "$path" "$attempts" >&2
    return 1
}

if [[ -z "$TAG" ]]; then
    TAG="$(api "repos/${REPOSITORY}/releases/latest" | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n1)"
fi

# GE tags look like GE-Proton11-6. Anything else means the naming changed and the
# pkgver derivation below is no longer trustworthy, so stop rather than invent one.
if [[ ! "$TAG" =~ ^GE-Proton([0-9]+)-([0-9]+)$ ]]; then
    printf 'ERROR: unexpected GE-Proton tag: %s\n' "$TAG" >&2
    exit 1
fi
VERSION="${BASH_REMATCH[1]}.${BASH_REMATCH[2]}"

ASSET="${TAG}-x86_64.tar.gz"
SUMS_URL="https://github.com/${REPOSITORY}/releases/download/${TAG}/${ASSET%.tar.gz}.sha512sum"
SHA512="$(curl -fsSL --retry 5 --retry-all-errors "$SUMS_URL" | awk -v want="$ASSET" '$2 == want { print $1; exit }')"

if [[ ! "$SHA512" =~ ^[0-9a-f]{128}$ ]]; then
    printf 'ERROR: could not read a SHA512 for %s from %s\n' "$ASSET" "$SUMS_URL" >&2
    exit 1
fi

cat <<EOF_INFO
PROTONGE_TAG=${TAG}
PROTONGE_VERSION=${VERSION}
PROTONGE_ASSET=${ASSET}
PROTONGE_URL=https://github.com/${REPOSITORY}/releases/download/${TAG}/${ASSET}
PROTONGE_SHA512=${SHA512}
EOF_INFO
