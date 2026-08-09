# BC-250 CachyOS kernel + Mesa repository

[![Build and publish BC-250 CachyOS kernel and Mesa](https://github.com/MastaG/linux-cachyos-bc250/actions/workflows/build-release.yml/badge.svg)](https://github.com/MastaG/linux-cachyos-bc250/actions/workflows/build-release.yml)

This repository builds a BC-250-specific CachyOS kernel plus a patched CachyOS
Mesa package set and publishes both through the same fixed GitHub Release / pacman
repository.

Project: <https://github.com/MastaG/linux-cachyos-bc250>

Packages and repository assets: <https://github.com/MastaG/linux-cachyos-bc250/releases/tag/repo>

## Quick start for BC-250 users

If you only want to install this repository, the BC-250 kernel, and the patched
Mesa packages on CachyOS or Arch Linux, these are the basic steps.

### 1. Add the BC-250 package repository

On CachyOS, run this one-liner once:

```bash
sudo sed -i \
  -e '/^[[:space:]]*\[bc250-cachyos\][[:space:]]*$/,/^[[:space:]]*Server[[:space:]]*=[[:space:]]*https:\/\/github\.com\/MastaG\/linux-cachyos-bc250\/releases\/download\/repo[[:space:]]*$/d' \
  -e '/^[[:space:]]*\[cachyos-v3\][[:space:]]*$/i [bc250-cachyos]\nSigLevel = Optional TrustAll\nServer = https://github.com/MastaG/linux-cachyos-bc250/releases/download/repo\n' \
  /etc/pacman.conf
```

The command is safe to use if you previously added this repository with the old
README instructions: it first removes the existing `[bc250-cachyos]` block and
then inserts it directly **above `[cachyos-v3]`**. This priority is important
because the normal CachyOS repositories also contain packages such as `mesa`
and `vulkan-radeon`. With the BC-250 repository above them, normal
`sudo pacman -Syu` upgrades keep using the patched Mesa packages automatically.

If you use plain Arch Linux rather than CachyOS, add the same repository block
manually above `[core]` instead.

### 2. Enable the BC-250 fan/sensor driver at boot

Run this before installing the kernel:

```bash
printf '%s\n' 'nct6687' | sudo tee /etc/modules-load.d/nct6687.conf >/dev/null
```

This tells systemd to load the `nct6687` fan/sensor driver automatically at
boot. The kernel package contains the driver as `nct6687.ko`.

### 3. Install/update the kernel and patched Mesa

Install the BC-250 kernel and headers while doing a normal full system update:

```bash
sudo pacman -Syu linux-cachyos-bc250 linux-cachyos-bc250-headers
```

Because step 1 gives `[bc250-cachyos]` repository priority, pacman will also
select this repository's newer patched `mesa`, `vulkan-radeon`, and other Mesa
split packages automatically.

### 4. Reboot

```bash
sudo reboot
```

After rebooting, you can verify the running kernel and the fan/sensor module:

```bash
uname -r
lsmod | grep nct6687
```

For later updates, a normal full system upgrade is enough when the
`[bc250-cachyos]` repository has priority over the repositories that also
provide Mesa:

```bash
sudo pacman -Syu
```

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
The upstream Mesa `pkgver` and `epoch` are left unchanged. The generated PKGBUILD
is additionally given the fixed BC-250 CPU target
`-march=x86-64-v3 -mtune=znver2`, and the GitHub Actions run number is appended
to `pkgrel`, for example:

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

The BC-250 uses Zen 2 CPU cores. Both the kernel and Mesa builds are therefore
targeted explicitly at the BC-250 instead of the CPU used by the GitHub Actions
runner. In particular, the Mesa build never relies on `-march=native`.

### Kernel

The current CachyOS kernel PKGBUILD directly exposes `generic_v1` through
`generic_v4`, `zen4`, and `native`, but not a dedicated Zen 2 selector. This
repository therefore uses:

```bash
_processor_opt=generic_v3
KCFLAGS=-mtune=znver2
```

`generic_v3` keeps the kernel's supported x86-64-v3 ISA baseline and kernel
configuration. `-mtune=znver2` asks Clang to tune instruction scheduling and
code generation for Zen 2 without changing that ISA baseline.

### Mesa

The downloaded CachyOS Mesa PKGBUILD is adjusted during the build so its C and
C++ compiler flags end with:

```text
-march=x86-64-v3 -mtune=znver2
```

These flags are appended to the existing `CFLAGS` and `CXXFLAGS`, preserving the
normal CachyOS/Arch optimization and hardening flags while making the final CPU
target explicit. Because the BC-250 target is set inside the generated PKGBUILD
before `arch-meson` runs, a newer CPU on the GitHub Actions runner cannot cause
Mesa to be built with `-march=native` for that host.

## Detailed installation on CachyOS or Arch Linux

Add this repository to `/etc/pacman.conf`. Because this repository intentionally
overrides the normal `mesa` and `vulkan-radeon` packages, place it above the
regular CachyOS/Arch repositories if you want ordinary `pacman -Syu` upgrades
to keep using the patched Mesa packages:

```ini
[bc250-cachyos]
SigLevel = Optional TrustAll
Server = https://github.com/MastaG/linux-cachyos-bc250/releases/download/repo
```

On CachyOS, this one-liner removes an older copy of the block if present and
reinserts it immediately above `[cachyos-v3]`:

```bash
sudo sed -i -e '/^\[bc250-cachyos\]$/,/^Server = https:\/\/github\.com\/MastaG\/linux-cachyos-bc250\/releases\/download\/repo$/d' -e '/^\[cachyos-v3\]$/i [bc250-cachyos]\nSigLevel = Optional TrustAll\nServer = https://github.com/MastaG/linux-cachyos-bc250/releases/download/repo\n' /etc/pacman.conf
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

When unset, it defaults to `linux-cachyos-rc`. The workflow has a safety guard
for the RC-to-stable transition: as soon as the upstream `linux-cachyos-rc`
PKGBUILD reports kernel series **7.3 or newer**, it stops rebuilding the kernel.
The last published 7.2 BC-250 kernel and headers are retained in the fixed repo,
while Mesa can continue to build and update normally.

At that point, change the repository variable to the stable source:

```text
linux-cachyos
```

This resumes kernel builds from the stable CachyOS package, which should then be
the Linux 7.2 series. A manual workflow run can temporarily select `rc` or
`stable` without changing the repository variable.

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
Mesa packaging source daily. While kernel building is enabled, the fingerprint
also includes the BC-250 kernel patches, package name, CPU target, build scripts,
and exact `nct6687d` source commit. Mesa sources, Mesa patches, its BC-250 CPU
target, and the exact CachyOS Mesa packaging commit are always tracked. An
unchanged source is skipped.

When the `linux-cachyos-rc` guard detects 7.3 or newer, kernel inputs are removed
from the active fingerprint so later 7.3 RC changes do not cause pointless
BC-250 kernel rebuilds. Mesa changes can still trigger a Mesa-only publication;
the workflow downloads the previous fixed release first, keeps its 7.2 kernel
packages, replaces the old Mesa split packages, and regenerates the pacman
repository database.

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

- keyboardspecialist / bombers -  For his reverse engineering efforts for telemetry on 8 cores and the original patches for linux 6.18.  
  See: https://github.com/keyboardspecialist/bc250-steamos/tree/master/bc250-audio-fix
- higorprado / higorevop - For porting the telemetry patches to linux 7.x.  
  See: https://github.com/higorprado/bc250-8core-telemetry-report
- Trov - For the proper DP audio fix (posted on Discord and sent to LKML)
- DryhoppedIPA - For his fixes for the amdgpu kernel and mesa drivers
  See: https://github.com/DryhoppedIPA/bc250-gfx1013-fix

