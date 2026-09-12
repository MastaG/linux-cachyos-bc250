# Local patches

Anything you drop here is applied only by `scripts/build-proton-tarball.sh`,
the private local-build path. CI never sets `BC250_LOCAL_PATCHES`, so the
packages published to the repository cannot pick up anything from this
directory.

    proton-cachyos-native/   applied to the Proton source tree, before it builds

Patches are applied in sorted order with `patch --batch -Np1`, after everything
this repository already applies, and a failure stops the build. In the native
package that happens at the end of `prepare()`, after the submodules are checked
out, so paths like `wine/dlls/...` and `dxvk/src/...` are there to patch. Name them so
the order reads correctly: `0001-something.patch`, `0002-something-else.patch`.

`proton-cachyos-native` is compiled from source, so a patch here can change
Proton, Wine, dxvk or vkd3d-proton themselves.

It is the only package built this way. The other two are Steam Linux Runtime
builds, which is the environment anti-cheat trusts, and making it convenient to
carry private patches into one of those is not something this repository does.

Both directories are ignored by git (see `.gitignore`), so private patches stay
private. Only this README is tracked.
