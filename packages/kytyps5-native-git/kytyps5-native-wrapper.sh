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
# A connected DualSense: WirePlumber starts a new controller at 40% and its USB
# mixer sits at 80%, far below a PS5. Kyty plays the controller's speaker on the
# front channels of its 4-channel sink and the haptics on the rear ones, so the
# two get their own levels (percent; KYTYPS5_DS_SPEAKER=off leaves all of it alone).
ds_levels() {
	speaker=${KYTYPS5_DS_SPEAKER:-50} haptics=${KYTYPS5_DS_HAPTICS:-90}
	{ [ "$speaker" = off ] || [ "$haptics" = off ]; } && return 0
	if command -v pactl >/dev/null; then
		pactl list sinks short 2>/dev/null | while read -r _ name _; do
			case $name in
			*DualSense*) pactl set-sink-volume "$name" "$speaker%" "$speaker%" "$haptics%" "$haptics%" 2>/dev/null ;;
			esac
		done
	fi
	if command -v amixer >/dev/null; then
		sed -n 's/^ *\([0-9][0-9]*\) .*DualSense.*/\1/p' /proc/asound/cards 2>/dev/null | while read -r card; do
			amixer -q -c "$card" sset PCM 100% 2>/dev/null
		done
	fi
	return 0
}
ds_levels
case ${0##*/} in
kytyps5-run) exec "$dst/kytyps5-run.sh" "$@" ;;
*) cd "$dst" && exec "$dst/kyty_launcher" "$@" ;;
esac
