#!/bin/sh
# Steam's toolmanifest.vdf points at this; it is the tool's entry point.
#
# protonge-latest-bc250 installs it as "proton" (GE itself lives under ge/),
# proton-cachyos-native-bc250 as "bc250-fsr4-proton" beside the Proton launcher
# it was built with. Either way it runs the wrapper, which selects the pinned
# FSR4 payload and then execve()s the real proton, so Steam still ends up
# supervising exactly one process.
#
# -B matters: /usr is read-only, and Python would otherwise try to write
# __pycache__ next to files pacman owns.
exec python3 -B "$(dirname -- "$0")/bc250-fsr4-launch.py" "$@"
