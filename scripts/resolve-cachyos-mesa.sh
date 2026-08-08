#!/usr/bin/env bash
set -Eeuo pipefail

REPOSITORY="https://github.com/CachyOS/CachyOS-PKGBUILDS.git"
REF="${CACHYOS_MESA_REF:-refs/heads/master}"

if [[ "$REF" =~ ^[0-9a-f]{40}$ ]]; then
    printf '%s\n' "$REF"
    exit 0
fi

commit="$(git ls-remote "$REPOSITORY" "$REF" | awk 'NR == 1 { print $1 }')"
if [[ ! "$commit" =~ ^[0-9a-f]{40}$ ]]; then
    printf 'ERROR: could not resolve %s from %s\n' "$REF" "$REPOSITORY" >&2
    exit 1
fi

printf '%s\n' "$commit"
