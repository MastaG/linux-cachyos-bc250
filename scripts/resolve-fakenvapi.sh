#!/usr/bin/env bash
# Resolve which fakenvapi release the FSR4 Proton packages should bundle.
#
# Unlike the OptiScaler build, which is deliberately pinned so a nightly cannot
# rebuild a ~700 MB package every day, fakenvapi is tracked live: it releases
# rarely (1.4.1 stood for months), and the point of shipping it is that users get
# the current one without anyone editing a pin. A new upstream release therefore
# changes the component fingerprint and rebuilds both Proton packages.
#
# Set FAKENVAPI_TAG to bundle a specific release instead of the newest one.
set -Eeuo pipefail

REPOSITORY="optiscaler/fakenvapi"
TAG="${FAKENVAPI_TAG:-}"

# Same reasoning as resolve-protonge.sh: plain curl, because this also runs in
# the Arch build container which has no gh and no token. A transient API failure
# must fail loudly rather than resolve to something else -- the build cache keys
# on this tag.
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

release="$(api "repos/${REPOSITORY}/releases/latest")"

if [[ -z "$TAG" ]]; then
    TAG="$(printf '%s' "$release" | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n1)"
fi

# Tags look like v1.4.1. Anything else means the naming changed and the version
# derived below is no longer trustworthy, so stop rather than invent one.
if [[ ! "$TAG" =~ ^v([0-9]+\.[0-9]+(\.[0-9]+)?)$ ]]; then
    printf 'ERROR: unexpected fakenvapi tag: %s\n' "$TAG" >&2
    exit 1
fi
VERSION="${BASH_REMATCH[1]}"

# Read the asset name rather than construct it: upstream has published a single
# .7z per release, but guessing the filename would turn a rename into a 404 at
# build time instead of an error here.
ASSET="$(printf '%s' "$release" |
    tr ',' '\n' | sed -n 's/.*"name": *"\(fakenvapi[^"]*\.7z\)".*/\1/p' | head -n1)"
if [[ -z "$ASSET" ]]; then
    printf 'ERROR: release %s publishes no fakenvapi .7z asset\n' "$TAG" >&2
    exit 1
fi

URL="https://github.com/${REPOSITORY}/releases/download/${TAG}/${ASSET}"

# fakenvapi publishes no checksum file, so the only way to pin it is to hash the
# asset. It is ~120 KB, which is cheap enough to do on every fingerprint check.
SHA256="$(curl -fsSL --retry 5 --retry-all-errors "$URL" | sha256sum | awk '{print $1}')"
if [[ ! "$SHA256" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'ERROR: could not hash %s\n' "$URL" >&2
    exit 1
fi

cat <<EOF_INFO
FAKENVAPI_TAG=${TAG}
FAKENVAPI_VERSION=${VERSION}
FAKENVAPI_ASSET=${ASSET}
FAKENVAPI_URL=${URL}
FAKENVAPI_SHA256=${SHA256}
EOF_INFO
