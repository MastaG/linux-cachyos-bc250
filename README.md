# BC-250 CachyOS kernel + Mesa repository

[![Build and publish BC-250 CachyOS kernel and Mesa](https://github.com/MastaG/linux-cachyos-bc250/actions/workflows/build-release.yml/badge.svg)](https://github.com/MastaG/linux-cachyos-bc250/actions/workflows/build-release.yml)

This repository builds a BC-250-specific CachyOS kernel plus a patched CachyOS
Mesa package set and publishes both through the same fixed GitHub Release / pacman
repository.

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
- GFX1013/BC-250 PASID TLB flush routing through MMIO for sustained KFD workloads
- GFX1013/BC-250 compute GFXOFF guard while KFD compute is active
- GFX1013/BC-250 scoped PASID type-0 invalidation path
- Extended `nct6687` hwmon/PWM driver, built as a normal kernel module
- Mesa/RADV GFX1013 compute-queue enablement and ACE dispatch workaround

## NCT6687D hardware-monitoring module

The kernel package also includes the external
[`Fred78290/nct6687d`](https://github.com/Fred78290/nct6687d) driver as a normal
in-tree-built module:

```text
nct6687.ko.zst
```

Each workflow run resolves the latest commit on the driver's `main` branch,
downloads `nct6687.c` from that immutable commit, and records the exact commit in
`build-info.env` and the release notes. A driver update changes the source
fingerprint and therefore triggers a kernel rebuild. To temporarily pin a known
working revision, set the GitHub repository variable `NCT6687D_REF` to its full
40-character commit hash; when unset, `refs/heads/main` is used.

The upstream kernel's `nct6683` module recognizes the same NCT6683/NCT6686/NCT6687
Super-I/O IDs.  
This BC-250 kernel disables `CONFIG_SENSORS_NCT6683` and builds:

```text
CONFIG_SENSORS_NCT6687=m
```

Load the driver for the current session:

```bash
sudo modprobe nct6687
```

Set optional module parameters in `/etc/modprobe.d/nct6687.conf`, for example:

```ini
options nct6687 fan_mask=0x3f temp_mask=0x0f
```

Load it automatically during boot only when desired:

```bash
printf '%s\n' 'nct6687' | sudo tee /etc/modules-load.d/nct6687.conf >/dev/null
```

Because it remains a module, parameters can be changed without rebuilding the
kernel and a problematic driver can be unloaded with `sudo modprobe -r nct6687`.

## Patched CachyOS Mesa

The same workflow also resolves the latest commit of
[`CachyOS/CachyOS-PKGBUILDS`](https://github.com/CachyOS/CachyOS-PKGBUILDS)
`master`, downloads `mesa/mesa/PKGBUILD` plus its local
`gamescope-fps-limiter.patch`, and pins both to that exact commit for the build.
The upstream Mesa `pkgver` and `epoch` are left unchanged; the GitHub Actions run
number is appended to `pkgrel`, for example:

```text
26.1.6-1 -> 26.1.6-1.42
```

Only this Mesa patch is currently added to the downloaded PKGBUILD and built:

```text
patches/mesa/0001-gfx1013-compute-queue-fix.patch
```

It exposes the GFX1013 ACE compute queue, fixes the reported GFX10.1 IP minor
version, and enables the async-compute threadgroup workaround. It is intended to
be used together with the GFX1013 kernel compute/PASID patches shipped by this
repository.

These two patches are already rebased and kept in the repository, but are
**not applied to the Mesa package yet**:

```text
patches/mesa/0002-gfx1013-mesh-task-shaders.patch
patches/mesa/0003-gfx1013-taskmesh-queries.patch
```

They remain disabled until the mesh/task-shader work is ready to be enabled.
The workflow still publishes them as release assets for review and testing.

To pin the Mesa packaging source temporarily, set the GitHub repository variable
`CACHYOS_MESA_REF` to a full 40-character commit hash. When unset, the workflow
resolves `refs/heads/master` at the start of each run.

The Mesa split packages are added to the same `bc250-cachyos` pacman repository
as the kernel. To explicitly select the patched RADV packages from this
repository, use for example:

```bash
sudo pacman -S bc250-cachyos/mesa bc250-cachyos/vulkan-radeon
```

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
printf '%s\n' \
  '' \
  '[bc250-cachyos]' \
  'SigLevel = Optional TrustAll' \
  'Server = https://github.com/MastaG/linux-cachyos-bc250/releases/download/repo' \
  | sudo tee -a /etc/pacman.conf >/dev/null
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

A scheduled workflow checks the selected kernel PKGBUILD/config and the CachyOS
Mesa packaging source daily. The fingerprint also includes the BC-250 kernel and
Mesa patches, package name, CPU target, build scripts, the exact `nct6687d`
source commit, and the exact CachyOS Mesa packaging commit. An unchanged source
is skipped.

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
- all split packages produced by the CachyOS Mesa PKGBUILD, including `mesa` and `vulkan-radeon`
- `bc250-cachyos.db` and `bc250-cachyos.files`
- compressed repository databases
- kernel `PKGBUILD`, `config`, and `.SRCINFO`
- `mesa-PKGBUILD` and `mesa.SRCINFO`
- the exact fetched `nct6687.c` and its Kconfig/Makefile integration patch
- the three GFX1013 compute/PASID kernel patches
- all three rebased GFX1013 Mesa patches (only Mesa patch 0001 is applied)
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

On an Arch/CachyOS system with the normal build dependencies, build the kernel
first and then add Mesa to the same repository directory:

```bash
CACHYOS_SOURCE_VARIANT=linux-cachyos-rc BC250_PKGREL=1 ./scripts/build-package.sh
MESA_PKGREL=1 ./scripts/build-mesa-package.sh
```

To build the kernel from the stable source later, replace `linux-cachyos-rc` with
`linux-cachyos`. Both preparation scripts resolve their moving upstream sources
to exact commits before building.

The generated repository is written to `out/repo/`.

## Patch behavior

The rebased kernel and Mesa patches are verified against their supplied source
snapshots with `patch --fuzz=0`. If a future upstream update makes a hunk
incompatible, the build should stop during `prepare()` instead of publishing an
unreviewed forward-port.

## Credits

- keyboardspecialist / bombers: For his reverse engineering efforts for telemetry on 8 cores and the original patches for linux 6.18.  
  See: https://github.com/keyboardspecialist/bc250-steamos/tree/master/bc250-audio-fix
- higorprado / higorevop - For porting the telemetry patches to linux 7.x.  
  See: https://github.com/higorprado/bc250-8core-telemetry-report
- Trov - For the proper DP audio fix (posted on Discord and sent to LKML)

