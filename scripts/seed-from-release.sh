#!/usr/bin/env bash
set -Eeuo pipefail

# Seed out/repo from the `repo` release with everything except the older
# builds kept there (scripts/package-archive.py): files listed in
# archive-index.txt stay on the release for downgrades but never come back into
# out/repo, so they are not re-added to the database, re-uploaded, or carried in
# the workflow artifact. Without this every run would download (and upload as an
# artifact) all archived builds too -- several times the size of the repository.
#
# Exit status: 0 when the download succeeded, non-zero otherwise (the caller
# retries and decides what an empty release means).

DEST="${1:?destination directory required}"
export GH_REPO="${GH_REPO:-${GITHUB_REPOSITORY:-}}"
[[ -n "$GH_REPO" ]] || unset GH_REPO

mkdir -p -- "$DEST"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

assets="$(gh release view repo --json assets --jq '.assets[].name')"
[[ -n "$assets" ]] || exit 1

archived=""
if grep -qx 'archive-index.txt' <<<"$assets"; then
    gh release download repo --pattern archive-index.txt --dir "$tmp" --clobber
    archived="$(grep -v '^#' "$tmp/archive-index.txt" | cut -f1)"
fi

patterns=()
skipped=0
while IFS= read -r name; do
    [[ -n "$name" ]] || continue
    if [[ -n "$archived" ]] && grep -qxF -- "$name" <<<"$archived"; then
        skipped=$((skipped + 1))
        continue
    fi
    patterns+=(--pattern "$name")
done <<<"$assets"

(( ${#patterns[@]} > 0 )) || exit 1
gh release download repo --dir "$DEST" --clobber "${patterns[@]}"
printf '==> seeded %d current assets; left %d archived older builds on the release\n' \
    "$(( ${#patterns[@]} / 2 ))" "$skipped"
