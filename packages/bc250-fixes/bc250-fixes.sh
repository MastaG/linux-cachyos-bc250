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
# next cachyos-handheld upgrade, and this hook then runs again.
F=/usr/share/applications/steamos-gamemode.desktop
if [ -f "$F" ] && grep -q '^Exec=/usr/bin/steamosctl switch-to-game-mode$' "$F"; then
    sed -i 's|^Exec=/usr/bin/steamosctl switch-to-game-mode$|Exec=/usr/bin/steamos-session-select gamescope|' "$F"
fi

exit 0
