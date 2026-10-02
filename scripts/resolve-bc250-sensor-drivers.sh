#!/usr/bin/env bash
set -Eeuo pipefail

# Resolve the pinned commits of the two BC-250 hwmon drivers shipped in the
# kernels (see patches/*/00??-bc250-vrm-memory-hwmon.patch):
#
#   BC250_VRM_COMMIT=<sha>     github.com/Hexxeh/bc250-vrm-dkms
#   BC250_MEMORY_COMMIT=<sha>  github.com/Hexxeh/bc250-memory-dkms
#
# BC250_VRM_REF / BC250_MEMORY_REF pin a branch, tag or full commit hash
# (default refs/heads/main). Same retry policy as resolve-nct6687d.sh: the
# kernel fingerprints key on these commits, so only a full 40-character hash is
# ever accepted, and a resolver that cannot get one fails loudly.

resolve() {
    local repository="$1" ref="$2" attempts=5 attempt out commit=""

    if [[ "$ref" =~ ^[0-9a-f]{40}$ ]]; then
        printf '%s\n' "$ref"
        return 0
    fi

    for attempt in $(seq 1 "$attempts"); do
        if out="$(git ls-remote "$repository" "$ref" 2>&1)"; then
            commit="$(printf '%s\n' "$out" | awk 'NR == 1 { print $1 }')"
            if [[ "$commit" =~ ^[0-9a-f]{40}$ ]]; then
                printf '%s\n' "$commit"
                return 0
            fi
        fi
        printf 'WARN: could not resolve %s from %s (attempt %d/%d): %s\n' \
            "$ref" "$repository" "$attempt" "$attempts" "${out%%$'\n'*}" >&2
        if (( attempt < attempts )); then sleep $(( attempt * 5 )); fi
    done

    printf 'ERROR: could not resolve %s from %s after %d attempts\n' \
        "$ref" "$repository" "$attempts" >&2
    return 1
}

vrm="$(resolve https://github.com/Hexxeh/bc250-vrm-dkms.git "${BC250_VRM_REF:-refs/heads/main}")"
memory="$(resolve https://github.com/Hexxeh/bc250-memory-dkms.git "${BC250_MEMORY_REF:-refs/heads/main}")"
printf 'BC250_VRM_COMMIT=%s\nBC250_MEMORY_COMMIT=%s\n' "$vrm" "$memory"
