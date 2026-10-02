#!/usr/bin/env bash
set -Eeuo pipefail

# Resolve the pinned commits of the two BC-250 hwmon drivers shipped in the
# kernels (see patches/*/00??-bc250-vrm-memory-hwmon.patch):
#
#   BC250_VRM_COMMIT=<sha>     BC250_VRM_TAG=<tag>     github.com/Hexxeh/bc250-vrm-dkms
#   BC250_MEMORY_COMMIT=<sha>  BC250_MEMORY_TAG=<tag>  github.com/Hexxeh/bc250-memory-dkms
#
# By default each driver follows its highest release tag (vX.Y[.Z], compared
# as versions; pre-release tags such as v1.1.0-rc1 are ignored), so the
# kernels never build an experimental commit from a branch and only move on
# when the author tags a higher version. BC250_VRM_REF / BC250_MEMORY_REF
# override that with a branch, tag or full commit hash.
#
# Same retry policy as resolve-nct6687d.sh: the kernel fingerprints key on
# these commits, so only a full 40-character hash is ever accepted, and a
# resolver that cannot get one fails loudly.

ls_remote() {
    local repository="$1" attempts=5 attempt out
    shift
    for attempt in $(seq 1 "$attempts"); do
        if out="$(git ls-remote "$@" "$repository" 2>&1)"; then
            printf '%s\n' "$out"
            return 0
        fi
        printf 'WARN: git ls-remote %s failed (attempt %d/%d): %s\n' \
            "$repository" "$attempt" "$attempts" "${out%%$'\n'*}" >&2
        if (( attempt < attempts )); then sleep $(( attempt * 5 )); fi
    done
    printf 'ERROR: could not list %s after %d attempts\n' "$repository" "$attempts" >&2
    return 1
}

# Print "<commit> <label>" for one repository.
resolve() {
    local repository="$1" ref="$2" refs tag commit

    if [[ "$ref" =~ ^[0-9a-f]{40}$ ]]; then
        printf '%s %s\n' "$ref" "$ref"
        return 0
    fi

    if [[ -n "$ref" ]]; then
        refs="$(ls_remote "$repository" --tags --heads)"
        # An annotated tag lists its commit as "<ref>^{}"; prefer that.
        commit="$(awk -v r="$ref" '$2 == r "^{}" || $2 == "refs/tags/" r "^{}" { print $1; exit }' <<<"$refs")"
        [[ -n "$commit" ]] || commit="$(awk -v r="$ref" '$2 == r || $2 == "refs/tags/" r || $2 == "refs/heads/" r { print $1; exit }' <<<"$refs")"
        label="$ref"
    else
        refs="$(ls_remote "$repository" --tags)"
        tag="$(awk '{ sub("^refs/tags/", "", $2); sub("\\^\\{\\}$", "", $2); print $2 }' <<<"$refs" |
            grep -E '^v[0-9]+(\.[0-9]+)*$' | sort -uV | tail -n 1)"
        [[ -n "$tag" ]] || {
            printf 'ERROR: %s has no release tag (vX.Y[.Z]) to follow\n' "$repository" >&2
            return 1
        }
        commit="$(awk -v t="refs/tags/$tag^{}" '$2 == t { print $1; exit }' <<<"$refs")"
        [[ -n "$commit" ]] || commit="$(awk -v t="refs/tags/$tag" '$2 == t { print $1; exit }' <<<"$refs")"
        label="$tag"
    fi

    [[ "$commit" =~ ^[0-9a-f]{40}$ ]] || {
        printf 'ERROR: could not resolve %s in %s\n' "${ref:-the latest release tag}" "$repository" >&2
        return 1
    }
    printf '%s %s\n' "$commit" "$label"
}

read -r vrm vrm_tag < <(resolve https://github.com/Hexxeh/bc250-vrm-dkms.git "${BC250_VRM_REF:-}")
read -r memory memory_tag < <(resolve https://github.com/Hexxeh/bc250-memory-dkms.git "${BC250_MEMORY_REF:-}")
[[ -n "${vrm:-}" && -n "${memory:-}" ]] || exit 1
printf 'BC250_VRM_COMMIT=%s\nBC250_VRM_TAG=%s\nBC250_MEMORY_COMMIT=%s\nBC250_MEMORY_TAG=%s\n' \
    "$vrm" "$vrm_tag" "$memory" "$memory_tag"
