#!/bin/sh
# Installed as /usr/bin/kytyps5-native (the launcher) and /usr/bin/kytyps5-run
# (upstream's Steam shortcut runner: kytyps5-run "<game folder>" [--keep-steam]).
#
# Upstream keeps saves and caches next to the program, which cannot be written in
# /usr/lib. So run a copy in the user's own folder, refreshed only when the
# package version changes. kyty-lodhw (root) is not copied; it runs from /usr/lib.
src=/usr/lib/kytyps5-native
dst=${XDG_DATA_HOME:-$HOME/.local/share}/KytyPS5-Native/package
want=$(cat "$src/VERSION") || exit 1
if [ "$(cat "$dst/VERSION" 2>/dev/null)" != "$want" ]; then
	mkdir -p "$dst" || exit 1
	# --remove-destination: a copy still running (another game) keeps its old
	# files instead of failing with "text file busy".
	for item in kyty_launcher kyty_emulator kytyps5-run.sh assets; do
		cp -r --remove-destination "$src/$item" "$dst/" || exit 1
	done
	printf '%s\n' "$want" > "$dst/VERSION"
fi
case ${0##*/} in
kytyps5-run) exec "$dst/kytyps5-run.sh" "$@" ;;
*) cd "$dst" && exec "$dst/kyty_launcher" "$@" ;;
esac
