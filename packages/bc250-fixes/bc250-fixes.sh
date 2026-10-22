#!/bin/sh
# Small corrections for things other packages get wrong on a BC-250. Run by
# bc250-fixes.hook after the packages named there are installed or upgraded.
# Every fix checks that the problem is still present before touching anything,
# so a fix retires itself once the package that caused it is repaired.

# cachyos-handheld 1.4.1 ships a "Return to Gaming Mode" shortcut that runs
# "steamosctl switch-to-game-mode". On a BC-250 steamos-manager does not export
# the SessionManagement1 interface that command calls, so the click does
# nothing. steamos-session-select (also from cachyos-handheld) does the same
# switch and works. Rewrite only that exact command. The file is not in the
# package's backup list, so pacman overwrites it silently (no .pacnew) on the
# next cachyos-handheld upgrade, and this hook then runs again. Only done when
# the replacement command is really installed, so a shortcut is never swapped
# for one that cannot work either.
F=/usr/share/applications/steamos-gamemode.desktop
SELECT=/usr/bin/steamos-session-select
if [ -x "$SELECT" ] && [ -f "$F" ] && grep -q '^Exec=/usr/bin/steamosctl switch-to-game-mode$' "$F"; then
    sed -i 's|^Exec=/usr/bin/steamosctl switch-to-game-mode$|Exec=/usr/bin/steamos-session-select gamescope|' "$F"
fi

# steamos-manager is Valve's "SteamOS Manager daemon"; CachyOS builds it from
# their own fork and it used to be pulled in by cachyos-handheld. Its session
# plumbing does not work on this image: it writes the holo-named one-shot conf.d
# file, which plasmalogin never reads, so Steam's "Switch to Desktop" costs you a
# session restart and lands straight back in Steam. Measured on two matched boards
# (same plasma-login-manager, same gamescope-session-cachyos, same kernel, same
# conf.d): with the package present the button does nothing, without it the request
# falls back to steam-set-session writing the steamos-named file, which is honoured,
# and Plasma comes up. CachyOS dropped the dependency on 2026-10-19, so systems that
# installed cachyos-handheld during that window are still carrying it as an orphan.
#
# A nested pacman cannot run here: a PostTransaction hook still holds the database
# lock, so "pacman -R" from this script fails with "unable to lock database" (verified
# on a board with a test hook). Hand it to systemd-run instead -- and let that unit
# retry, because on the 2026-10-22 smoke test the first deferred attempt landed while
# the parent transaction was still running its snapper hooks and did nothing, and only
# a later run completed it. -Rns rather than -Rn so the dependencies it drags in leave
# with it; on a default install none of those three packages are present (verified
# against the freshly flashed board and the live cachyos-handheld depends), so this
# branch never runs there at all. Both commands are overridable for the tests.
PACMAN="${BC250_PACMAN:-/usr/bin/pacman}"
RUNNER="${BC250_SYSTEMD_RUN:-/usr/bin/systemd-run}"
if [ -x "$PACMAN" ] && [ -x "$RUNNER" ] && "$PACMAN" -Qq steamos-manager >/dev/null 2>&1; then
    printf '==> bc250-fixes: removing steamos-manager (it breaks Switch to Desktop on this image)\n'
    "$RUNNER" --quiet --on-active=15 --unit=bc250-fixes-steamos-manager \
        --property=Restart=on-failure --property=RestartSec=60 --property=StartLimitBurst=5 \
        "$PACMAN" -Rns --noconfirm steamos-manager \
        || printf 'WARNING: bc250-fixes could not schedule the removal; run: pacman -Rns steamos-manager\n' >&2
fi

exit 0
