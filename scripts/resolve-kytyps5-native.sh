#!/usr/bin/env bash
# Resolve which KytyPS5-Native commit kytyps5-native-git builds.
#
# Upstream's CI publishes a GitHub release for every push to main whose build
# and unit tests passed, so the newest release is the newest commit known to
# build. Tracking main itself would also pick up commits whose CI failed.
#
# Prints an env file: the release tag and the full commit it was made from.
# Set KYTY_TAG to build a specific release instead of the newest one.
set -Eeuo pipefail

REPOSITORY="superkeka/KytyPS5-Native"
TAG="${KYTY_TAG:-}"

# Plain curl rather than gh, as in resolve-protonge.sh: this also runs where
# there is no GitHub CLI. A transient failure must not resolve to something
# else -- the build cache keys on the commit -- so retry, then give up loudly.
attempts=5
retry() {
    local what="$1" out attempt
    shift
    for attempt in $(seq 1 "$attempts"); do
        if out="$("$@" 2>&1)"; then
            printf '%s\n' "$out"
            return 0
        fi
        printf 'WARN: could not query %s (attempt %d/%d): %s\n' \
            "$what" "$attempt" "$attempts" "${out%%$'\n'*}" >&2
        if (( attempt < attempts )); then sleep $(( attempt * 5 )); fi
    done
    printf 'ERROR: gave up querying %s after %d attempts\n' "$what" "$attempts" >&2
    return 1
}

if [[ -z "$TAG" ]]; then
    auth=()
    token="${GH_TOKEN:-${GITHUB_TOKEN:-}}"
    [[ -z "$token" ]] || auth=(-H "Authorization: Bearer $token")
    TAG="$(retry "the latest release" curl -fsSL "${auth[@]}" \
        -H 'Accept: application/vnd.github+json' \
        "https://api.github.com/repos/${REPOSITORY}/releases/latest" |
        sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -n1)"
fi

# Upstream tags look like KytyPS5-Native-2026-10-29-b9a29ef. Anything else
# means its release scheme changed; stop rather than guess.
if [[ ! "$TAG" =~ ^KytyPS5-Native-[0-9]{4}-[0-9]{2}-[0-9]{2}-([0-9a-f]{7,})$ ]]; then
    printf 'ERROR: unexpected KytyPS5-Native tag: %s\n' "$TAG" >&2
    exit 1
fi
short="${BASH_REMATCH[1]}"

# `gh release create --target` makes a lightweight tag; ^{} covers an annotated
# one too.
refs="$(retry "the tag ${TAG}" git ls-remote "https://github.com/${REPOSITORY}.git" \
    "refs/tags/${TAG}" "refs/tags/${TAG}^{}")"
commit="$(awk '$2 ~ /\^\{\}$/ { print $1 }' <<<"$refs")"
[[ -n "$commit" ]] || commit="$(awk 'NR == 1 { print $1 }' <<<"$refs")"

if [[ ! "$commit" =~ ^[0-9a-f]{40}$ || "$commit" != "$short"* ]]; then
    printf 'ERROR: tag %s resolved to %q, which is not commit %s\n' "$TAG" "$commit" "$short" >&2
    exit 1
fi

cat <<EOF_INFO
KYTY_TAG=${TAG}
KYTY_COMMIT=${commit}
EOF_INFO
