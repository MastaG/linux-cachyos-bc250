#!/usr/bin/env bash
set -Eeuo pipefail

# Rebuild the pacman database over whatever is staged in out/repo.
#
# Runs after every component now, not just once at the end, because the runner
# publishes each component as soon as it builds and the database it uploads has
# to describe the packages that go up with it.
#
# Rebuilding from scratch rather than adding incrementally is deliberate: a
# component replaces its own packages by pkgbase before staging new ones, so the
# set on disk is authoritative and an incrementally-updated database could keep
# an entry for a file that is no longer there.

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${ROOT_DIR}/out/repo"
REPO_NAME="bc250-cachyos"

cd -- "$OUT_DIR"
shopt -s nullglob
packages=(./*.pkg.tar.zst)
(( ${#packages[@]} > 0 )) || {
    printf 'ERROR: no packages staged in %s\n' "$OUT_DIR" >&2
    exit 1
}

rm -f -- "${REPO_NAME}.db" "${REPO_NAME}.db.tar.zst" \
         "${REPO_NAME}.files" "${REPO_NAME}.files.tar.zst"
repo-add "${REPO_NAME}.db.tar.zst" "${packages[@]}" >/dev/null
cp -L --remove-destination "${REPO_NAME}.db.tar.zst" "${REPO_NAME}.db"
cp -L --remove-destination "${REPO_NAME}.files.tar.zst" "${REPO_NAME}.files"

# SHA256SUMS ships with every publish, so it has to be regenerated here too --
# a stale one alongside freshly uploaded packages is worse than none.
rm -f -- SHA256SUMS
while IFS= read -r -d '' file; do
    sha256sum "${file#./}"
done < <(find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 | sort -z) > SHA256SUMS

printf '==> repository database updated (%d packages)\n' "${#packages[@]}"
