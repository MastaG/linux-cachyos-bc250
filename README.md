# BC-250 CachyOS kernel repository

[![Build and publish BC-250 CachyOS kernel](https://github.com/MastaG/linux-cachyos-bc250/actions/workflows/build-release.yml/badge.svg)](https://github.com/MastaG/linux-cachyos-bc250/actions/workflows/build-release.yml)

This repository builds a BC-250-specific CachyOS kernel and publishes it as a
fixed GitHub Release that also acts as a pacman repository.

Project: <https://github.com/MastaG/linux-cachyos-bc250>

Packages and repository assets: <https://github.com/MastaG/linux-cachyos-bc250/releases/tag/repo>

## Stable package name across RC and stable kernels

The upstream source package can be either:

- `linux-cachyos-rc`, currently used for Linux 7.2 release candidates
- `linux-cachyos`, used after Linux 7.2 becomes the stable CachyOS kernel

Regardless of the selected source, this project always publishes:

- `linux-cachyos-bc250`
- `linux-cachyos-bc250-headers`

The pacman repository name and release URL also remain unchanged. Switching the
upstream source therefore does not require reinstalling a differently named
kernel or editing `/etc/pacman.conf`.

The expected version progression is:

```text
7.2.rc6 -> 7.2.rc7 -> 7.2.0 -> 7.2.1 -> ...
```

Pacman's version comparison treats an `rc` version as older than the final
numeric release, so `7.2.0` upgrades the installed `7.2.rcX` package normally.

## Included BC-250 patches

- Automatic selection of the normal 6-core or hybrid 8-core SMU telemetry layout
- Correct per-core telemetry for unlocked 8-core BC-250 systems
- GPU activity reporting through `gpu_busy_percent` and GPU Metrics
- Safe GFX clock fallback: the 8-core layout never interprets
  `C0Residency[6]` as `GfxclkFrequency`
- Cyan Skillfish DisplayPort audio quirk through `ignore_dpref_ss`

## CPU optimization

The BC-250 uses Zen 2 CPU cores. The current CachyOS PKGBUILD directly exposes
`generic_v1` through `generic_v4`, `zen4`, and `native`, but not a dedicated
Zen 2 selector.

This repository therefore uses the safe combination:

```bash
_processor_opt=generic_v3
KCFLAGS=-mtune=znver2
```

`generic_v3` keeps the kernel's supported x86-64-v3 ISA baseline and kernel
configuration. `-mtune=znver2` asks Clang to tune instruction scheduling and
code generation for Zen 2 without enabling instructions outside that baseline.
This is deliberately safer than forcing `-march=znver2` through an unsupported
PKGBUILD path.

## Install on CachyOS or Arch Linux

Add this repository to `/etc/pacman.conf`:

```ini
[bc250-cachyos]
SigLevel = Optional TrustAll
Server = https://github.com/MastaG/linux-cachyos-bc250/releases/download/repo
```

One way to append it:

```bash
sudo tee -a /etc/pacman.conf >/dev/null <<'EOF_REPO'

[bc250-cachyos]
SigLevel = Optional TrustAll
Server = https://github.com/MastaG/linux-cachyos-bc250/releases/download/repo
EOF_REPO
```

Refresh the databases and verify the repository:

```bash
sudo pacman -Syy
pacman -Sl bc250-cachyos
```

Install the kernel and headers during a normal full upgrade:

```bash
sudo pacman -Syu linux-cachyos-bc250 linux-cachyos-bc250-headers
```

Keep a known-working kernel installed as a fallback. After rebooting, verify:

```bash
pacman -Qi linux-cachyos-bc250
uname -r
```

## Migrating from the first `repo-rc` release

Remove or replace the old section:

```ini
[bc250-cachyos-v3-rc]
Server = https://github.com/MastaG/linux-cachyos-bc250/releases/download/repo-rc
```

with the new `[bc250-cachyos]` configuration shown above. Then install the
stable-name package:

```bash
sudo pacman -Syy
sudo pacman -Syu linux-cachyos-bc250 linux-cachyos-bc250-headers
```

The old `linux-cachyos-rc-bc250` package may coexist temporarily. Remove it only
after booting and validating the new kernel:

```bash
sudo pacman -Rns linux-cachyos-rc-bc250 linux-cachyos-rc-bc250-headers
```

The obsolete GitHub release/tag `repo-rc` can be deleted after the new `repo`
release has been tested successfully.

## Selecting the upstream source

Scheduled and push builds use the GitHub repository variable:

```text
CACHYOS_SOURCE_VARIANT
```

Accepted values:

```text
linux-cachyos-rc
linux-cachyos
```

When unset, it defaults to `linux-cachyos-rc`. Once Linux 7.2 is available from
the stable package, change the variable to:

```text
linux-cachyos
```

A manual workflow run can temporarily select `rc` or `stable` without changing
the repository variable.

## Self-hosted runner

The workflow targets a self-hosted runner with these labels:

```text
self-hosted
Linux
X64
bc250
```

It expects a Docker-compatible CLI/API. The tested arrangement is a GitHub
runner in Podman with the rootful Podman socket mounted as
`/var/run/docker.sock`. The workflow intentionally contains no global
`docker system prune`, so it will not remove unrelated host images or
containers.

## Automatic updates

A scheduled workflow checks the selected upstream PKGBUILD and config daily.
The fingerprint also includes the BC-250 patches, package name, CPU target, and
build scripts. An unchanged source is skipped.

New builds replace the assets under the fixed `repo` tag, so normal updates are
enough:

```bash
sudo pacman -Syu
```

The GitHub Actions run number is appended to `pkgrel`, allowing pacman to see a
patch-only rebuild as newer even when the upstream kernel version is unchanged.

## Published assets

Each successful build publishes:

- `linux-cachyos-bc250-*.pkg.tar.zst`
- `linux-cachyos-bc250-headers-*.pkg.tar.zst`
- `bc250-cachyos.db` and `bc250-cachyos.files`
- compressed repository databases
- `PKGBUILD`, `config`, and `.SRCINFO`
- `SHA256SUMS` and `build-info.env`

The release title and notes read `pkgbase`, `pkgver`, and `pkgrel` from
`.SRCINFO`. Publication fails rather than creating incomplete metadata.

## Package signing

The packages and repository database are currently unsigned, hence:

```ini
SigLevel = Optional TrustAll
```

GitHub HTTPS and `SHA256SUMS` are not a replacement for pacman package
signatures. Only use this repository when you trust this project and its
workflow.

## Local build

On an Arch/CachyOS system with the normal build dependencies:

```bash
CACHYOS_SOURCE_VARIANT=linux-cachyos-rc \
BC250_PKGREL=1 \
./scripts/build-package.sh
```

To build from the stable source later:

```bash
CACHYOS_SOURCE_VARIANT=linux-cachyos \
BC250_PKGREL=1 \
./scripts/build-package.sh
```

The generated repository is written to `out/repo/`.

## Patch behavior

Patch application is deliberately strict. When a future CachyOS source update
makes a hunk incompatible, `makepkg` stops during `prepare()` instead of
silently publishing an unverified kernel.
