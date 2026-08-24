#!/usr/bin/env bash
# Report whether the fixed package release exists, distinguishing a genuine
# "not published yet" from a transient GitHub/network failure.
#
# Those two cases must not be conflated. The build cache decides what to
# rebuild by diffing fingerprints against build-info.env from that release, and
# the publish step re-seeds itself from its assets. Silently treating an
# unreachable API as "there is no previous release" forces a full rebuild of
# all three kernels and all of Mesa (about an hour), and can republish a
# release seeded from nothing.
#
# Prints "found" or "missing" on stdout. Exits non-zero if the state could not
# be determined, so callers can fail loudly instead of guessing.
set -Eeuo pipefail

TAG="${1:-repo}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"

attempts=5
for attempt in $(seq 1 "$attempts"); do
    if out="$(gh api "repos/${GITHUB_REPOSITORY}/releases/tags/${TAG}" 2>&1)"; then
        printf 'found\n'
        exit 0
    fi
    # A real 404 is an answer, not a failure: the release has never been made.
    if grep -qE 'HTTP 404|Not Found' <<<"$out"; then
        printf 'missing\n'
        exit 0
    fi
    printf 'WARN: could not query the %s release (attempt %d/%d): %s\n' \
        "$TAG" "$attempt" "$attempts" "${out%%$'\n'*}" >&2
    if (( attempt < attempts )); then sleep $(( attempt * 10 )); fi
done

printf 'ERROR: gave up querying the %s release after %d attempts\n' "$TAG" "$attempts" >&2
exit 1
