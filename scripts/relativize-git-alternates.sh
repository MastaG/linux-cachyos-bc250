#!/usr/bin/env bash
# Make git source clones under a build tree usable from outside the container.
#
# makepkg clones a git source with --shared, so the clone's
# .git/objects/info/alternates names the bare mirror it borrows objects from by
# an absolute path. Inside the build container that path is /workspace/build/...
# which does not exist on the host, so every git command in the clone fails
# ("unable to normalize alternate object path"). git also accepts an alternate
# relative to the objects directory, which resolves the same way on both sides.
#
# usage: relativize-git-alternates.sh [BUILD_ROOT]     (default /workspace/build)
set -Eeuo pipefail

root="${1:-/workspace/build}"
shopt -s nullglob

for alt in "$root"/*/src/*/.git/objects/info/alternates; do
    [[ -f "$alt" && ! -L "$alt" ]] || continue
    objects="$(cd -- "$(dirname -- "$alt")/.." && pwd -P)"
    changed=0
    out=""
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" == /* && -d "$line" ]]; then
            line="$(realpath -m --relative-to="$objects" -- "$line")"
            changed=1
        fi
        out+="$line"$'\n'
    done < "$alt"
    # Written in place so the file keeps its owner and mode.
    ((changed)) && printf '%s' "$out" > "$alt"
done
exit 0
