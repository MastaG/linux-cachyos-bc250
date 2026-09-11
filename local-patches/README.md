# Local patches

Anything you drop here is applied only by `scripts/build-proton-tarball.sh`,
the private local-build path. CI never sets `BC250_LOCAL_PATCHES`, so the
packages published to the repository cannot pick up anything from this
directory.

    proton-cachyos-native/   applied to the Proton source tree, before it builds
    protonge-latest/         applied to the unpacked GE-Proton release

Patches are applied in sorted order with `patch --batch -Np1`, after everything
this repository already applies, and a failure stops the build. Name them so
the order reads correctly: `0001-something.patch`, `0002-something-else.patch`.

The two directories are not equivalent. `proton-cachyos-native` is compiled
from source, so a patch there can change Proton, Wine, dxvk or vkd3d-proton
themselves. `protonge-latest` repacks a release that is already built, so a
patch there can only edit files that ship inside it -- in practice the Python
under `protonfixes/`, the launch scripts, and the configuration files.

Both directories are ignored by git (see `.gitignore`), so private patches stay
private. Only this README is tracked.
