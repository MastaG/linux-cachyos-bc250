# Building, CI and repository internals

How this repository builds and publishes itself. None of this is needed to use
the packages — see the [README](../README.md) for that.

---

## CPU optimization

All kernels use CachyOS' safe x86-64-v3 baseline with additional Zen 2 tuning:

```text
_processor_opt=generic_v3
KCFLAGS=-mtune=znver2
```

Mesa, lib32-mesa, mesa-git and lib32-mesa-git use:

```text
-march=x86-64-v3 -mtune=znver2
```

The build runner's own CPU therefore cannot leak a wider `-march=native` target into BC-250 packages.

## Persistent ccache

The CI container enables makepkg's native `ccache` integration and also prepends `/usr/lib/ccache/bin` to `PATH`.  
This applies to **all makepkg builds in the workflow**, not only the kernels:

```text
linux-cachyos-bc250
linux-cachyos-rc-bc250
linux-cachyos-bore-bc250
mesa / its split packages
lib32-mesa / its split packages
mesa-git + lib32-mesa-git
```

The cache lives in the persistent container-engine named volume:

```text
bc250-ccache:/ccache
```

and is currently capped at 30 GiB.  
Because the volume survives the temporary `archlinux:base-devel` container, clean `makepkg --cleanbuild` runs can still reuse compiler output.  
The workflow prints `ccache -s` statistics at the end of every build.

## Self-hosted runner

The workflow targets:

```text
self-hosted
Linux
X64
bc250
```

It expects a Docker-compatible CLI/API.  
The tested setup is a GitHub Actions runner in Podman with the Podman socket exposed as `/var/run/docker.sock`.  
The build itself runs in a disposable `archlinux:base-devel` container while `bc250-ccache` persists separately.

## Automatic updates

Six components have independent source fingerprints:

```text
kernel-stable
kernel-rc
kernel-bore
mesa
lib32-mesa
mesa-git
```

A change to one kernel does **not** force the other kernels or any Mesa component to rebuild.  
Likewise, a new Mesa `main` commit normally rebuilds only `mesa-git`/`lib32-mesa-git`.

For partial publications, the workflow downloads the previous fixed `repo` release and stages it in `out/repo`.  
Each builder reads `.PKGINFO` from existing package archives and removes only packages whose `pkgbase` matches the component being rebuilt.  
This means package ownership does not depend on filename guessing and remains correct when a CachyOS PKGBUILD adds or removes split package names.

The kernel package families are:

```text
linux-cachyos-bc250
linux-cachyos-rc-bc250
linux-cachyos-bore-bc250
```

The Mesa package families are:

```text
mesa
lib32-mesa
mesa-git
```

After the changed components are added, `scripts/finalize-repository.sh` validates that all six families are present and rebuilds the complete pacman database.

The first run after migrating from the former single-kernel workflow intentionally rebuilds all three kernel families because the old release has no fingerprints for the new RC and BORE packages.  
Existing unchanged Mesa packages can be preserved.

## Published assets

A complete fixed release contains at least:

- `linux-cachyos-bc250` + headers;
- `linux-cachyos-rc-bc250` + headers;
- `linux-cachyos-bore-bc250` + headers;
- stable Mesa split packages;
- stable lib32-mesa split packages;
- `mesa-git` + `lib32-mesa-git`;
- `bc250-cachyos.db` and `bc250-cachyos.files` plus compressed forms;
- `kernel-stable-PKGBUILD`, `kernel-stable.SRCINFO`, `kernel-stable-config`;
- `kernel-rc-PKGBUILD`, `kernel-rc.SRCINFO`, `kernel-rc-config`;
- `kernel-bore-PKGBUILD`, `kernel-bore.SRCINFO`, `kernel-bore-config`;
- both rebased kernel patch sets;
- the exact fetched `nct6687.c`;
- Mesa PKGBUILDs, SRCINFO files and patch assets;
- `kernel-stable-info.env`, `kernel-rc-info.env`, `kernel-bore-info.env`;
- `mesa-info.env`, `lib32-mesa-info.env`, `mesa-git-info.env`;
- `bc250-dual-audio` + its PKGBUILD, `.SRCINFO` and `bc250-dual-audio-info.env`;
- `linux-cachyos-bc250-meta` + its PKGBUILD, `.SRCINFO` and `linux-cachyos-bc250-meta-info.env`;
- `protonge-latest-bc250` + its PKGBUILD, `.SRCINFO` and `protonge-latest-bc250-info.env`;
- `proton-cachyos-native-bc250` + its PKGBUILD, `.SRCINFO` and `proton-cachyos-native-bc250-info.env`;
- aggregate `build-info.env`, release notes and `SHA256SUMS`.

Publication validates the complete staged repository before deleting/replacing the fixed `repo` release.

## Local kernel builds

The generic kernel builder accepts one of the three upstream variants:

```bash
CACHYOS_SOURCE_VARIANT=linux-cachyos ./scripts/build-package.sh
CACHYOS_SOURCE_VARIANT=linux-cachyos-rc ./scripts/build-package.sh
CACHYOS_SOURCE_VARIANT=linux-cachyos-bore ./scripts/build-package.sh
```

`prepare-pkgbuild.sh` selects the package name and kernel patch directory automatically.

The Mesa builders are:

```text
scripts/build-mesa-package.sh
scripts/build-lib32-mesa-package.sh
scripts/build-mesa-git-package.sh
```

For reproducible full repository builds, CI remains the recommended path because it configures multilib, ccache, the clean build user, source fingerprints and previous-release preservation.

## Package signing

Packages and the repository database are currently unsigned, hence:

```ini
SigLevel = Optional TrustAll
```

GitHub HTTPS and `SHA256SUMS` are not a replacement for pacman package signatures.  
Only use this repository when you trust the project and its workflow.

