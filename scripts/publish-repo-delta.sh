#!/usr/bin/env bash
set -Eeuo pipefail

# Push whatever has changed in out/repo to the fixed `repo` release, without
# deleting and recreating it.
#
# This runs on the runner (which has gh and the token), between component
# builds, so a run that is cancelled or dies partway still leaves every
# component that finished published -- along with its -info.env, which is what
# stops the next run from rebuilding it.
#
# Ordering is the whole correctness argument. Users run `pacman -Syu` against
# this release while a build is in progress, and pacman reads the database and
# then fetches the files it names:
#
#   1. upload new and changed package files
#   2. upload the database that refers to them
#   3. only then delete assets nothing refers to any more
#
# So the database never names a file that is not there yet. A stale package file
# that lingers between steps is harmless -- pacman only fetches what the
# database lists.
#
# Deliberately fail-soft: finalize-repository.sh and the full publish at the end
# of the run remain authoritative. If this cannot reach GitHub, the run carries
# on and the final publish fixes everything up.

OUT_DIR="${OUT_DIR:-out/repo}"
STATE="${PUBLISH_STATE:-out/.published-state}"
LABEL="${1:-delta}"

: "${GH_TOKEN:?GH_TOKEN is required to publish}"

[[ -d "$OUT_DIR" ]] || { printf 'ERROR: %s does not exist\n' "$OUT_DIR" >&2; exit 1; }

# The database is uploaded after the packages it names, so keep it separate.
is_db_asset() {
    case "$1" in
        bc250-cachyos.db|bc250-cachyos.db.tar.zst) return 0 ;;
        bc250-cachyos.files|bc250-cachyos.files.tar.zst) return 0 ;;
        *) return 1 ;;
    esac
}

current="$(mktemp)"; trap 'rm -f "$current"' EXIT
while IFS= read -r -d '' file; do
    printf '%s  %s\n' "$(sha256sum < "$file" | awk '{print $1}')" "$(basename -- "$file")"
done < <(find "$OUT_DIR" -maxdepth 1 -type f -print0 | sort -z) > "$current"

[[ -f "$STATE" ]] || : > "$STATE"

sha_of() { awk -v n="$2" '$2 == n { print $1; exit }' "$1"; }

uploads=() db_uploads=() deletions=()
while read -r sha name; do
    if [[ "$(sha_of "$STATE" "$name")" != "$sha" ]]; then
        if is_db_asset "$name"; then db_uploads+=("$name"); else uploads+=("$name"); fi
    fi
done < "$current"

while read -r _ name; do
    [[ -n "$(sha_of "$current" "$name")" ]] || deletions+=("$name")
done < "$STATE"

if (( ${#uploads[@]} + ${#db_uploads[@]} + ${#deletions[@]} == 0 )); then
    printf '==> [%s] nothing changed; release left alone\n' "$LABEL"
    exit 0
fi

printf '==> [%s] publishing %d changed, %d database, %d removed\n' \
    "$LABEL" "${#uploads[@]}" "${#db_uploads[@]}" "${#deletions[@]}"

# The release has to exist before anything can be uploaded into it. On a first
# ever run there is nothing to create it from yet, so leave that to the final
# publish and simply do nothing here.
if ! gh release view repo >/dev/null 2>&1; then
    printf '::warning title=No release to update::[%s] the repo release does not exist yet; leaving it to the final publish.\n' "$LABEL"
    exit 0
fi

upload() {
    local name attempt
    for name in "$@"; do
        for attempt in 1 2 3; do
            if gh release upload repo "$OUT_DIR/$name" --clobber >/dev/null 2>&1; then
                continue 2
            fi
            printf 'WARN: [%s] upload of %s failed (attempt %d/3)\n' "$LABEL" "$name" "$attempt" >&2
            (( attempt < 3 )) && sleep $(( attempt * 5 ))
        done
        printf '::warning title=Incremental publish incomplete::[%s] could not upload %s; the final publish will retry.\n' \
            "$LABEL" "$name"
        return 1
    done
    return 0
}

# Packages first, database second. If the packages did not all make it, do not
# upload a database that would name a file that is not there.
if ! upload "${uploads[@]}"; then exit 0; fi
if (( ${#db_uploads[@]} )) && ! upload "${db_uploads[@]}"; then exit 0; fi

for name in "${deletions[@]:-}"; do
    [[ -n "$name" ]] || continue
    gh release delete-asset repo "$name" --yes >/dev/null 2>&1 ||
        printf 'WARN: [%s] could not remove stale asset %s\n' "$LABEL" "$name" >&2
done

cp -- "$current" "$STATE"
printf '==> [%s] release updated\n' "$LABEL"
