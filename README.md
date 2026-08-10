# BC-250 CachyOS kernel + Mesa repository

[![Build and publish BC-250 CachyOS kernel and Mesa](https://github.com/MastaG/linux-cachyos-bc250/actions/workflows/build-release.yml/badge.svg)](https://github.com/MastaG/linux-cachyos-bc250/actions/workflows/build-release.yml)

This repository builds a BC-250-specific CachyOS kernel, patched stable Mesa and lib32-mesa package sets, and an optional patched mesa-git/lib32-mesa-git pair.  
All packages are published through the same fixed GitHub Release / pacman repository.

Project: <https://github.com/MastaG/linux-cachyos-bc250>

Packages and repository assets: <https://github.com/MastaG/linux-cachyos-bc250/releases/tag/repo>

## Quick start for BC-250 users

If you only want to install this repository, the BC-250 kernel, and the patched Mesa packages on CachyOS or Arch Linux, these are the basic steps.

### 1. Add the BC-250 package repository

On CachyOS, run this one-liner once:

```bash
sudo sed -i \
  -e '/^[[:space:]]*\[bc250-cachyos\][[:space:]]*$/,/^[[:space:]]*Server[[:space:]]*=[[:space:]]*https:\/\/github\.com\/MastaG\/linux-cachyos-bc250\/releases\/download\/repo[[:space:]]*$/d' \
  -e '/^[[:space:]]*\[cachyos-v3\][[:space:]]*$/i [bc250-cachyos]\nSigLevel = Optional TrustAll\nServer = https://github.com/MastaG/linux-cachyos-bc250/releases/download/repo\n' \
  /etc/pacman.conf
```

The command is safe to use if you previously added this repository with the old README instructions: it first removes the existing `[bc250-cachyos]` block and then inserts it directly **above `[cachyos-v3]`**.  
This priority is important because the normal CachyOS repositories also contain packages such as `mesa` and `vulkan-radeon`.  
With the BC-250 repository above them, normal `sudo pacman -Syu` upgrades keep using the patched Mesa packages automatically.

If you use plain Arch Linux rather than CachyOS, add the same repository block manually above `[core]` instead.

### 2. Enable the BC-250 fan/sensor driver at boot

Run this before installing the kernel:

```bash
printf '%s\n' 'nct6687' | sudo tee /etc/modules-load.d/nct6687.conf >/dev/null
```

This tells systemd to load the `nct6687` fan/sensor driver automatically at boot.  
The kernel package contains the driver as `nct6687.ko`.

### 3. Add the required AMDGPU scheduler parameter

The GFX1013 compute fixes are intended to run with `amdgpu.sched_policy=2`.  
On CachyOS with Limine, add it to `/etc/default/limine` before installing the kernel:

```bash
grep -Eq '^[[:space:]]*KERNEL_CMDLINE\[default\].*amdgpu\.sched_policy=2' /etc/default/limine || \
  printf '%s\n' 'KERNEL_CMDLINE[default]+=amdgpu.sched_policy=2' | \
  sudo tee -a /etc/default/limine >/dev/null
```

The `+=` form appends the parameter to the existing default Limine kernel command line instead of replacing it.  
On a BC-250 system this means the parameter is also present if you boot another kernel that uses the default Limine command line.

If you use another bootloader instead of Limine, add `amdgpu.sched_policy=2` to that bootloader's kernel command line instead.

If you edit `/etc/default/limine` after the kernel is already installed, apply the change manually with:

```bash
sudo limine-mkinitcpio
```

### 4. Install/update the kernel and patched Mesa

Install the BC-250 kernel and headers while doing a normal full system update:

```bash
sudo pacman -Syu linux-cachyos-bc250 linux-cachyos-bc250-headers
```

Because step 1 gives `[bc250-cachyos]` repository priority, pacman will also select this repository's newer patched `mesa`, `vulkan-radeon`, and installed `lib32-mesa` split packages automatically.  
The optional `mesa-git` and `lib32-mesa-git` packages are **not** installed automatically; users must explicitly choose them instead of stable Mesa.  
On a normal CachyOS Limine installation, installing the kernel also runs the Limine/mkinitcpio hooks, so the parameter added in step 3 is picked up automatically.

### 5. Reboot

```bash
sudo reboot
```

After rebooting, verify the running kernel, the fan/sensor module, and the AMDGPU scheduler parameter:

```bash
uname -r
lsmod | grep nct6687
cat /proc/cmdline | grep -o 'amdgpu.sched_policy=[^ ]*'
```

The last command should show:

```text
amdgpu.sched_policy=2
```

For later updates, a normal full system upgrade is enough when the `[bc250-cachyos]` repository has priority over the repositories that also provide Mesa:

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

The pacman repository name and release URL also remain unchanged.  
Switching the upstream source therefore does not require reinstalling a differently named kernel or editing `/etc/pacman.conf`.

The expected version progression is:

```text
7.2.rc6 -> 7.2.rc7 -> 7.2.0 -> 7.2.1 -> ...
```

Pacman's version comparison treats an `rc` version as older than the final numeric release, so `7.2.0` upgrades the installed `7.2.rcX` package normally.

## Included BC-250 patches

- Automatic selection of the normal 6-core or hybrid 8-core SMU telemetry layout
- Correct per-core telemetry for unlocked 8-core BC-250 systems
- GPU activity reporting through `gpu_busy_percent` and GPU Metrics
- Safe GFX clock fallback: the 8-core layout never interprets
  `C0Residency[6]` as `GfxclkFrequency`
- GFX1013/BC-250 PASID TLB invalidation fix: MMIO routing plus the scoped PASID type-0 path, merged into one v33 patch
- GFX1013/BC-250 compute GFXOFF guard while KFD compute is active
- Extended `nct6687` hwmon/PWM driver, built as a normal kernel module
- Mesa/RADV GFX1013 compute-queue enablement and ACE dispatch workaround

## NCT6687D hardware-monitoring module

The kernel package also includes the external [`Fred78290/nct6687d`](https://github.com/Fred78290/nct6687d) driver as a normal in-tree-built module:

```text
nct6687.ko.zst
```

Each workflow run resolves the latest commit on the driver's `main` branch, downloads `nct6687.c` from that immutable commit, and records the exact commit in `build-info.env` and the release notes.  
A driver update changes the source fingerprint and therefore triggers a kernel rebuild.  
To temporarily pin a known working revision, set the GitHub repository variable `NCT6687D_REF` to its full 40-character commit hash; when unset, `refs/heads/main` is used.

The upstream kernel's `nct6683` module recognizes the same NCT6683/NCT6686/NCT6687 Super-I/O IDs.  
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

Because it remains a module, parameters can be changed without rebuilding the kernel and a problematic driver can be unloaded with `sudo modprobe -r nct6687`.

## Patched CachyOS Mesa

The same workflow also resolves the latest commit of [`CachyOS/CachyOS-PKGBUILDS`](https://github.com/CachyOS/CachyOS-PKGBUILDS) `master`, downloads `mesa/mesa/PKGBUILD` plus its local `gamescope-fps-limiter.patch`, and pins both to that exact commit for the build.  
The upstream Mesa `pkgver` and `epoch` are left unchanged.  
The generated PKGBUILD is additionally given the fixed BC-250 CPU target `-march=x86-64-v3 -mtune=znver2`, and the GitHub Actions run number is appended to `pkgrel`, for example:

```text
26.1.6-1 -> 26.1.6-1.42
```

Only this Mesa patch is currently added to the downloaded PKGBUILD and built:

```text
patches/mesa/0001-gfx1013-compute-queue-fix.patch
```

It exposes the GFX1013 ACE compute queue, fixes the reported GFX10.1 IP minor version, and enables the async-compute threadgroup workaround.  
It is intended to be used together with the GFX1013 kernel compute/PASID patches shipped by this repository.

These two patches are already rebased and kept in the repository, but are **not applied to the Mesa package yet**:

```text
patches/mesa/0002-gfx1013-mesh-task-shaders.patch
patches/mesa/0003-gfx1013-taskmesh-queries.patch
```

They remain disabled until the mesh/task-shader work is ready to be enabled.  
The workflow still publishes them as release assets for review and testing.

To pin the CachyOS Mesa packaging source temporarily, set the GitHub repository variable `CACHYOS_MESA_REF` to a full 40-character commit hash.  
The same pinned `CachyOS-PKGBUILDS` revision is used for stable Mesa, lib32-mesa, and the mesa-git packaging files.  
When unset, the workflow resolves `refs/heads/master` at the start of each run.

The Mesa split packages are added to the same `bc250-cachyos` pacman repository as the kernel.  
To explicitly select the patched RADV packages from this repository, use for example:

```bash
sudo pacman -S bc250-cachyos/mesa bc250-cachyos/vulkan-radeon
```

## Patched CachyOS lib32-mesa

The repository also builds CachyOS `mesa/lib32-mesa/PKGBUILD` from the same pinned `CachyOS-PKGBUILDS` revision.  
`lib32-mesa` uses the same stable Mesa release and the same active `0001-gfx1013-compute-queue-fix.patch` as the 64-bit stable Mesa packages.

The workflow appends the same GitHub Actions run number to `pkgrel` and uses the same fixed BC-250 CPU target:

```text
-march=x86-64-v3 -mtune=znver2
```

All split packages produced by the CachyOS `lib32-mesa` PKGBUILD are published, including `lib32-mesa` and `lib32-vulkan-radeon`.  
If the normal CachyOS versions are already installed, a regular `sudo pacman -Syu` upgrades them to the patched BC-250 builds because this repository has priority.

## Optional patched CachyOS mesa-git

The repository additionally publishes optional `mesa-git` and `lib32-mesa-git` packages based directly on CachyOS `mesa/mesa-git/PKGBUILD`.  
The downloaded CachyOS `customization.cfg` is kept unchanged.  
Its current upstream default is `_lib32=true`, so the same build produces both the 64-bit and 32-bit Git variants from the same Mesa source revision.

The workflow resolves the current Mesa `main` commit before the build and pins that revision through the PKGBUILD's supported `mesa-userpatches/user.cfg` override.  
This keeps `customization.cfg` itself identical to CachyOS while preventing Mesa `main` from moving halfway through a workflow run.

Mesa main has moved since the stable 26.1.x source used by the original patches.  
The repository therefore carries a separate rebased patch series under `patches/mesa-git/`.

Only this rebased patch is active:

```text
patches/mesa-git/0001-gfx1013-compute-queue-fix.patch
```

The GFX1013 IP minor-version correction from the stable patch is already present upstream in current Mesa main, so that hunk is intentionally absent from the Git patch.  
The remaining ACE compute-queue exposure and async-compute threadgroup workaround are still applied.

These rebased Git patches are published but remain disabled:

```text
patches/mesa-git/0002-gfx1013-mesh-task-shaders.patch
patches/mesa-git/0003-gfx1013-taskmesh-queries.patch
```

They remain disabled for the same reason as the stable variants: mesh/task shading can hard-hang GFX1013.  
`0003` depends on `0002`.

The upstream CachyOS package metadata is intentionally left alone.  
In particular, this repository does **not** rename or add Mesa split-package aliases in `provides` or `conflicts`; `mesa-git` and `lib32-mesa-git` use the same package relationships as the CachyOS PKGBUILD.

To switch both 64-bit and 32-bit Mesa to the Git build:

```bash
sudo pacman -S bc250-cachyos/mesa-git bc250-cachyos/lib32-mesa-git
```

Install both packages together on gaming systems so Steam/Wine 32-bit userspace uses the same Mesa Git revision as 64-bit applications.  
The Git packages conflict with and provide the corresponding stable Mesa packages, so pacman can replace the installed stable set during the switch.  
The separately published stable `lib32-mesa` packages remain available for users who stay on stable Mesa; they are not intended to be mixed with `lib32-mesa-git`.

To pin Mesa Git temporarily, set the GitHub repository variable `MESA_GIT_REF` to a full 40-character Mesa commit hash.  
When unset, the workflow resolves `refs/heads/main` from the upstream Mesa repository.

## CPU optimization

The BC-250 uses Zen 2 CPU cores.  
The kernel, stable Mesa, lib32-mesa, and mesa-git builds are therefore targeted explicitly at the BC-250 instead of the CPU used by the GitHub Actions runner.  
None of the Mesa builds relies on `-march=native`.

### Kernel

The current CachyOS kernel PKGBUILD directly exposes `generic_v1` through `generic_v4`, `zen4`, and `native`, but not a dedicated Zen 2 selector.  
This repository therefore uses:

```bash
_processor_opt=generic_v3
KCFLAGS=-mtune=znver2
```

`generic_v3` keeps the kernel's supported x86-64-v3 ISA baseline and kernel configuration.  
`-mtune=znver2` asks Clang to tune instruction scheduling and code generation for Zen 2 without changing that ISA baseline.

### Mesa, lib32-mesa, and mesa-git

All three downloaded CachyOS Mesa PKGBUILDs are adjusted during the build so their C and C++ compiler flags end with:

```text
-march=x86-64-v3 -mtune=znver2
```

These flags are appended to the existing `CFLAGS` and `CXXFLAGS`, preserving the normal CachyOS/Arch optimization and hardening flags while making the final CPU target explicit.  
The mesa-git PKGBUILD receives the same flags after its optional custom-optimization block, so both `mesa-git` and `lib32-mesa-git` are built with the BC-250 target.  
A newer CPU on the GitHub Actions runner therefore cannot cause any of these packages to be built with `-march=native` for that host.

## Detailed installation on CachyOS or Arch Linux

Add this repository to `/etc/pacman.conf`.  
Because this repository intentionally overrides the normal `mesa` and `vulkan-radeon` packages, place it above the regular CachyOS/Arch repositories if you want ordinary `pacman -Syu` upgrades to keep using the patched Mesa packages:

```ini
[bc250-cachyos]
SigLevel = Optional TrustAll
Server = https://github.com/MastaG/linux-cachyos-bc250/releases/download/repo
```

On CachyOS, this one-liner removes an older copy of the block if present and reinserts it immediately above `[cachyos-v3]`:

```bash
sudo sed -i \
  -e '/^[[:space:]]*\[bc250-cachyos\][[:space:]]*$/,/^[[:space:]]*Server[[:space:]]*=[[:space:]]*https:\/\/github\.com\/MastaG\/linux-cachyos-bc250\/releases\/download\/repo[[:space:]]*$/d' \
  -e '/^[[:space:]]*\[cachyos-v3\][[:space:]]*$/i [bc250-cachyos]\nSigLevel = Optional TrustAll\nServer = https://github.com/MastaG/linux-cachyos-bc250/releases/download/repo\n' \
  /etc/pacman.conf
```

Refresh the databases and verify the repository:

```bash
sudo pacman -Syy
pacman -Sl bc250-cachyos
```

Configure the `nct6687` fan/sensor module to load automatically:

```bash
printf '%s\n' 'nct6687' | sudo tee /etc/modules-load.d/nct6687.conf >/dev/null
```

When using CachyOS with Limine, add the required AMDGPU scheduler parameter before installing the kernel:

```bash
grep -Eq '^[[:space:]]*KERNEL_CMDLINE\[default\].*amdgpu\.sched_policy=2' /etc/default/limine || \
  printf '%s\n' 'KERNEL_CMDLINE[default]+=amdgpu.sched_policy=2' | \
  sudo tee -a /etc/default/limine >/dev/null
```

The `KERNEL_CMDLINE[default]+=` form appends the parameter without replacing the existing default command line.

Install the kernel and headers during a normal full upgrade:

```bash
sudo pacman -Syu linux-cachyos-bc250 linux-cachyos-bc250-headers
```

CachyOS' Limine integration updates kernel boot entries automatically when kernels are installed or removed.  
Because the parameter is added before the kernel installation, no separate `limine-mkinitcpio` command is normally needed at this point.  
If `/etc/default/limine` is changed later, run `sudo limine-mkinitcpio` manually before rebooting.

Keep a known-working kernel installed as a fallback.  
After rebooting, verify:

```bash
pacman -Qi linux-cachyos-bc250
uname -r
cat /proc/cmdline | grep -o 'amdgpu.sched_policy=[^ ]*'
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

When unset, it defaults to `linux-cachyos-rc`.  
The workflow has a safety guard for the RC-to-stable transition: as soon as the upstream `linux-cachyos-rc` PKGBUILD reports kernel series **7.3 or newer**, it stops rebuilding the kernel.  
The last published 7.2 BC-250 kernel and headers are retained in the fixed repo, while Mesa can continue to build and update normally.

At that point, change the repository variable to the stable source:

```text
linux-cachyos
```

This resumes kernel builds from the stable CachyOS package, which should then be the Linux 7.2 series.  
A manual workflow run can temporarily select `rc` or `stable` without changing the repository variable.

## Self-hosted runner

The workflow targets a self-hosted runner with these labels:

```text
self-hosted
Linux
X64
bc250
```

It expects a Docker-compatible CLI/API.  
The tested arrangement is a GitHub runner in Podman with the rootful Podman socket mounted as `/var/run/docker.sock`.  
The workflow intentionally contains no global `docker system prune`, so it will not remove unrelated host images or containers.

## Automatic updates

The scheduled workflow checks four components independently: the kernel, stable Mesa, stable lib32-mesa, and mesa-git.  
Each component has its own source fingerprint, so a new Mesa `main` commit normally rebuilds only the `mesa-git` component (both `mesa-git` and `lib32-mesa-git`) instead of rebuilding the kernel and stable Mesa packages every day.

The kernel fingerprint tracks the selected CachyOS kernel PKGBUILD/config, all BC-250 kernel patches, the CPU target, build scripts, and the exact `nct6687d` source commit.  
The stable Mesa and lib32-mesa fingerprints track their own CachyOS packaging files plus the stable BC-250 Mesa patch set.  
The mesa-git fingerprint additionally tracks the resolved upstream Mesa `main` commit and the separately rebased `patches/mesa-git/` series.

For a partial update, the workflow downloads the previous fixed release, replaces only packages belonging to the changed `pkgbase`, keeps all unchanged packages, and then regenerates the pacman repository database.  
On the first partial run after upgrading from the older single-fingerprint workflow, legacy kernel metadata in `build-info.env` is migrated automatically to the new per-component format.  
A kernel rebuild starts a fresh repository, so all Mesa components are rebuilt in the same run to repopulate it completely.

When the `linux-cachyos-rc` guard detects 7.3 or newer, kernel generation remains paused and the last 7.2 BC-250 kernel packages are retained.  
Stable Mesa, lib32-mesa, and mesa-git can continue updating independently while the guard is active.

New builds replace the assets under the fixed `repo` tag, so normal updates are enough:

```bash
sudo pacman -Syu
```

The GitHub Actions run number is appended to `pkgrel`, allowing pacman to see a patch-only rebuild as newer even when the upstream kernel version is unchanged.

## Published assets

Each successful build publishes:

- `linux-cachyos-bc250-*.pkg.tar.zst`
- `linux-cachyos-bc250-headers-*.pkg.tar.zst`
- all split packages produced by the stable CachyOS Mesa PKGBUILD, including `mesa` and `vulkan-radeon`
- all split packages produced by the stable CachyOS lib32-mesa PKGBUILD, including `lib32-mesa` and `lib32-vulkan-radeon`
- the optional `mesa-git-*.pkg.tar.zst` and `lib32-mesa-git-*.pkg.tar.zst` packages
- `bc250-cachyos.db` and `bc250-cachyos.files`
- compressed repository databases
- kernel `PKGBUILD`, `config`, and `.SRCINFO`
- `mesa-PKGBUILD`, `mesa.SRCINFO`, `lib32-mesa-PKGBUILD`, and `lib32-mesa.SRCINFO`
- `mesa-git-PKGBUILD`, unchanged `mesa-git-customization.cfg`, `mesa-git-user.cfg`, and `mesa-git.SRCINFO`
- the exact fetched `nct6687.c` and its Kconfig/Makefile integration patch
- the two GFX1013 compute/PASID kernel patches (merged PASID TLB invalidation + compute GFXOFF guard)
- all three stable GFX1013 Mesa patches and all three separately rebased Mesa-Git patches; only each series' `0001` is active
- per-component metadata files plus `SHA256SUMS` and `build-info.env`

Each component builder records the package metadata needed by the final repository step.  
The finalizer rebuilds the pacman database, release notes, aggregate `build-info.env`, and checksums from the staged packages and per-component metadata.  
Publication fails if required component metadata is missing instead of silently creating an incomplete repository.

## Package signing

The packages and repository database are currently unsigned, hence:

```ini
SigLevel = Optional TrustAll
```

GitHub HTTPS and `SHA256SUMS` are not a replacement for pacman package signatures.  
Only use this repository when you trust this project and its workflow.

## Local build

The CI workflow is the recommended build path because it enables Arch multilib, creates a clean build user, and handles partial repository updates.  
For manual testing, the component build scripts can also be run directly on an Arch/CachyOS system with their normal build dependencies available.

The four package builders are:

```text
scripts/build-package.sh
scripts/build-mesa-package.sh
scripts/build-lib32-mesa-package.sh
scripts/build-mesa-git-package.sh
```

The Mesa preparation scripts resolve moving sources to exact commits when the corresponding commit environment variable is not supplied.  
`mesa-git` is pinned to the resolved Mesa commit through the PKGBUILD-supported `mesa-userpatches/user.cfg` override before `makepkg` starts, while the downloaded CachyOS `customization.cfg` remains unchanged.

After staging the desired components in `out/repo/`, `scripts/finalize-repository.sh` recreates the repository database, release metadata, and checksums.  
In CI, component fingerprints and previous-release preservation are handled automatically.

## Patch behavior

The stable Mesa and lib32-mesa packages share the stable GFX1013 patch series.  
Mesa-Git has a separate series rebased against current Mesa main; the supplied snapshot is used to verify that all three Git patches apply cleanly in sequence.  
If future upstream Mesa changes make the active patch incompatible, `makepkg` stops during `prepare()` instead of publishing an unreviewed forward-port.

## Credits

- keyboardspecialist / bombers -  For his reverse engineering efforts for telemetry on 8 cores and the original patches for linux 6.18.  
  See: https://github.com/keyboardspecialist/bc250-steamos/tree/master/bc250-audio-fix
- higorprado / higorevop - For porting the telemetry patches to linux 7.x.  
  See: https://github.com/higorprado/bc250-8core-telemetry-report
- DryhoppedIPA - For his fixes for the amdgpu kernel and mesa drivers
  See: https://github.com/DryhoppedIPA/bc250-gfx1013-fix

