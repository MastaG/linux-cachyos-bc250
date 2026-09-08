#!/bin/sh
# Steam's toolmanifest.vdf points at "/proton"; this is that entry point.
#
# The real GE-Proton lives under ge/. Going through the wrapper is what lets the
# pinned FSR4 payload be selected without patching GE's own launcher, and the
# wrapper execve()s ge/proton, so Steam still ends up supervising one process.
#
# -B matters: /usr is read-only, and Python would otherwise try to write
# __pycache__ next to files pacman owns.
exec python3 -B "$(dirname -- "$0")/bc250-fsr4-launch.py" "$@"
