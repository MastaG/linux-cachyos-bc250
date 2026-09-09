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
# Deliberately not inside the workspace: ci-build.sh setup does
# `chown -R builder:builder /workspace` so the container can build there, which
# leaves the runner unable to write to it. Reading out/repo still works, since
# makepkg produces world-readable files.
STATE="${PUBLISH_STATE:-${RUNNER_TEMP:-out}/bc250-published-state}"
LABEL="${1:-delta}"

: "${GH_TOKEN:?GH_TOKEN is required to publish}"

# Name the repository explicitly instead of letting gh infer it from git.
#
# This runs between component builds, after ci-build.sh setup has done
# `chown -R builder:builder /workspace` so the container can build there. gh
# shells out to git, git then refuses the workspace with "detected dubious
# ownership", and every incremental publish failed that way -- five components
# in run 34311070564, each reporting the release as unreachable when it was
# perfectly reachable. The final publish only worked because it runs after the
# ownership is restored.
export GH_REPO="${GH_REPO:-${GITHUB_REPOSITORY:-}}"
[[ -n "$GH_REPO" ]] || unset GH_REPO

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

# Confirm the release is there before uploading into it, with retries and the
# real error kept -- a single transient read used to be enough to skip the whole
# upload, because this both hid the error and then tried to *create* the release
# as a fallback. Actions cannot create releases on this repository (see
# scripts/../.github/workflows: HTTP 403 with Contents: write), so that fallback
# could never succeed and only turned a blip into a silent no-op.
release_present=false
for attempt in 1 2 3; do
    if view_err="$(gh release view repo 2>&1 >/dev/null)"; then
        release_present=true
        break
    fi
    printf 'WARN: [%s] could not read the repo release (attempt %d/3): %s\n' \
        "$LABEL" "$attempt" "${view_err%%$'\n'*}" >&2
    (( attempt < 3 )) && sleep $(( attempt * 5 ))
done
if [[ "$release_present" != true ]]; then
    printf '::warning title=Release unreachable::[%s] the repo release could not be read, so nothing was uploaded. The final publish reports what to do if it is genuinely missing.\n' "$LABEL"
    exit 0
fi

upload() {
    local name attempt err
    for name in "$@"; do
        for attempt in 1 2 3; do
            if err="$(gh release upload repo "$OUT_DIR/$name" --clobber 2>&1 >/dev/null)"; then
                continue 2
            fi
            printf 'WARN: [%s] upload of %s failed (attempt %d/3): %s\n' \
                "$LABEL" "$name" "$attempt" "${err%%$'\n'*}" >&2
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
