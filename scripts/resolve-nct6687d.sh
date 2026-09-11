#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY="https://github.com/Fred78290/nct6687d.git"
REF="${NCT6687D_REF:-refs/heads/main}"

if [[ "$REF" =~ ^[0-9a-f]{40}$ ]]; then
    printf '%s\n' "$REF"
    exit 0
fi

# Retry rather than fail the whole run on a transient outage. This resolves
# before anything is built, so a five-second blip at the forge used to throw
# away the entire scheduled build -- gitlab.freedesktop.org returning 503
# ("Gitaly is not available") is exactly how that happens.
#
# A wrong answer is worse than a slow one: the build cache keys on this commit,
# so the retry only ever accepts a full 40-character hash, and gives up loudly.
attempts=5
commit=""
for attempt in $(seq 1 "$attempts"); do
    if out="$(git ls-remote "$REPOSITORY" "$REF" 2>&1)"; then
        commit="$(printf '%s\n' "$out" | awk 'NR == 1 { print $1 }')"
        if [[ "$commit" =~ ^[0-9a-f]{40}$ ]]; then
            break
        fi
    fi
    commit=""
    printf 'WARN: could not resolve %s from %s (attempt %d/%d): %s\n' \
        "$REF" "$REPOSITORY" "$attempt" "$attempts" "${out%%$'\n'*}" >&2
    if (( attempt < attempts )); then sleep $(( attempt * 5 )); fi
done

if [[ ! "$commit" =~ ^[0-9a-f]{40}$ ]]; then
    printf 'ERROR: could not resolve %s from %s after %d attempts\n' \
        "$REF" "$REPOSITORY" "$attempts" >&2
    exit 1
fi

printf '%s\n' "$commit"
