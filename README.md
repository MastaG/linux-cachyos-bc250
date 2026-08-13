# BC-250 CachyOS kernels + Mesa repository

[![Build and publish BC-250 CachyOS kernels and Mesa](https://github.com/MastaG/linux-cachyos-bc250/actions/workflows/build-release.yml/badge.svg)](https://github.com/MastaG/linux-cachyos-bc250/actions/workflows/build-release.yml)

This repository builds three BC-250-specific CachyOS kernels, patched stable Mesa and lib32-mesa packages, and an optional patched mesa-git/lib32-mesa-git pair.  
All packages are published through the same fixed GitHub Release / pacman repository.

Project: <https://github.com/MastaG/linux-cachyos-bc250>  
Packages and repository assets: <https://github.com/MastaG/linux-cachyos-bc250/releases/tag/repo>

## Kernel choices

The repository always builds these three independent kernel families:

| Package | CachyOS source | Purpose |
|---|---|---|
| `linux-cachyos-bc250` | `linux-cachyos` | Stable/default BC-250 kernel |
| `linux-cachyos-rc-bc250` | `linux-cachyos-rc` | Release-candidate/testing kernel |
| `linux-cachyos-bore-bc250` | `linux-cachyos-bore` | Stable-series BORE kernel |

Each has a matching `-headers` package.  
The package names are intentionally different, so multiple variants can remain installed side-by-side as fallback/test kernels.

The old `CACHYOS_SOURCE_VARIANT` switch and the Linux 7.3 RC guard are gone.  
The workflow follows all three upstream CachyOS packages independently and rebuilds only the kernel family whose fingerprint changed.

## Quick start for BC-250 users

### 1. Add the BC-250 package repository

On CachyOS, run this once:

```bash
sudo sed -i \
  -e '/^[[:space:]]*\[bc250-cachyos\][[:space:]]*$/,/^[[:space:]]*Server[[:space:]]*=[[:space:]]*https:\/\/github\.com\/MastaG\/linux-cachyos-bc250\/releases\/download\/repo[[:space:]]*$/d' \
  -e '/^[[:space:]]*\[cachyos-v3\][[:space:]]*$/i [bc250-cachyos]\nSigLevel = Optional TrustAll\nServer = https://github.com/MastaG/linux-cachyos-bc250/releases/download/repo\n' \
  /etc/pacman.conf
```

The repository is inserted directly above `[cachyos-v3]`.  
That priority is intentional because this repository also provides patched Mesa packages.

On plain Arch Linux, add the same block manually above the normal repositories:

```ini
[bc250-cachyos]
SigLevel = Optional TrustAll
Server = https://github.com/MastaG/linux-cachyos-bc250/releases/download/repo
```

### 2. Enable the BC-250 fan/sensor driver at boot

```bash
printf '%s\n' 'nct6687' | sudo tee /etc/modules-load.d/nct6687.conf >/dev/null
```

All three kernels contain the external `nct6687` driver as an in-tree-built module.

### 3. Add the required AMDGPU scheduler parameter

The GFX1013 compute fixes are intended to run with `amdgpu.sched_policy=2`.  
On CachyOS with Limine:

```bash
grep -Eq '^[[:space:]]*KERNEL_CMDLINE\[default\].*amdgpu\.sched_policy=2' /etc/default/limine || \
  printf '%s\n' 'KERNEL_CMDLINE[default]+=amdgpu.sched_policy=2' | \
  sudo tee -a /etc/default/limine >/dev/null
```

If `/etc/default/limine` is changed after a kernel is already installed, run:

```bash
sudo limine-mkinitcpio
```

### 4. Install a kernel

The stable kernel is the recommended default:

```bash
sudo pacman -Syu linux-cachyos-bc250 linux-cachyos-bc250-headers
```

Optional RC/testing kernel:

```bash
sudo pacman -S linux-cachyos-rc-bc250 linux-cachyos-rc-bc250-headers
```

Optional BORE kernel:

```bash
sudo pacman -S linux-cachyos-bore-bc250 linux-cachyos-bore-bc250-headers
```

Because the package names are separate, installing the RC or BORE variant does not require removing the stable BC-250 kernel.

With `[bc250-cachyos]` above the normal CachyOS repositories, installed stable Mesa and lib32-Mesa split packages also update to the patched BC-250 builds during a normal `pacman -Syu`.  
`mesa-git` and `lib32-mesa-git` remain opt-in alternatives.

### 5. Reboot and verify

```bash
sudo reboot
```

After rebooting:

```bash
uname -r
lsmod | grep nct6687
cat /proc/cmdline | grep -o 'amdgpu.sched_policy=[^ ]*'
```

The last command should show:

```text
amdgpu.sched_policy=2
```

## Kernel patch sets

Kernel patches are deliberately separated by kernel series:

```text
patches/kernel-7.1/
patches/kernel-7.2/
```

`linux-cachyos` and `linux-cachyos-bore` currently share the same Linux 7.1 source series and therefore use the same `kernel-7.1` patch set.  
`linux-cachyos-rc` currently uses the Linux 7.2 RC source and the separate `kernel-7.2` patch set.

### Linux 7.1 patch set

Applied to both `linux-cachyos-bc250` and `linux-cachyos-bore-bc250`:

```text
0001-bc250-8core-telemetry-gpu-activity.patch
0002-bc250-audio.patch
0003-nct6687d-hwmon.patch
0004-gfx1013-pasid-tlb-invalidation.patch
0005-gfx1013-compute-gfxoff-guard.patch
```

The audio patch disables DP spread spectrum for Cyan Skillfish through `ignore_dpref_ss`.  
It is required for the supplied Linux 7.1 source used to rebase this patch set.

### Linux 7.2 patch set

Applied to `linux-cachyos-rc-bc250`:

```text
0001-bc250-8core-telemetry-gpu-activity.patch
0003-nct6687d-hwmon.patch
0004-gfx1013-pasid-tlb-invalidation.patch
0005-gfx1013-compute-gfxoff-guard.patch
```

There is intentionally no `0002-bc250-audio.patch` here.  
The equivalent Cyan Skillfish DP spread-spectrum fix is already present in the current Linux 7.2 RC source.

Both patch sets contain:

> The telemetry/activity and tunable GFXCLK/activity cache logic is consolidated in `0001-bc250-8core-telemetry-gpu-activity.patch`.  
> Both cache windows default to 25 ms and can still be changed at runtime or disabled with `0`.

- automatic 6-core / hybrid 8-core Cyan Skillfish SMU telemetry handling;
- correct per-core telemetry for unlocked 8-core BC-250 systems;
- GPU activity reporting through GPU Metrics and `GPU_LOAD`, with a tunable per-device cache (`amdgpu.cs_activity_cache_ms`, default 25 ms, `0` disables it);
- safe GFX clock handling for the hybrid metrics layout, with tunable `GetGfxclkFrequency` mailbox caching (`amdgpu.cs_gfxclk_cache_ms`, default 25 ms, `0` disables it);
- the v33 merged GFX1013 PASID TLB invalidation fix;
- the GFX1013 compute GFXOFF guard;
- integration of the external `nct6687` hwmon/PWM driver.

## NCT6687D hardware-monitoring module

Each workflow run resolves the configured `Fred78290/nct6687d` revision, downloads `nct6687.c` from that immutable commit and builds it as:

```text
nct6687.ko.zst
```

The upstream kernel's `nct6683` driver recognizes overlapping Super-I/O IDs.  
All three BC-250 kernels therefore build:

```text
# CONFIG_SENSORS_NCT6683 is not set
CONFIG_SENSORS_NCT6687=m
```

To pin a known driver revision, set repository variable `NCT6687D_REF` to a full 40-character commit hash.  
When unset, the resolver follows the configured upstream branch.

## Patched stable CachyOS Mesa

The workflow resolves a single exact commit from `CachyOS/CachyOS-PKGBUILDS` and downloads the current stable Mesa packaging from that revision.  
The upstream Mesa version and epoch remain unchanged; the GitHub Actions run number is appended to `pkgrel`.

All four BC-250 Mesa patches are applied at build time, in order:

```text
patches/mesa/0001-gfx1013-compute-queue-fix.patch
patches/mesa/0002-gfx1013-mesh-task-shaders.patch
patches/mesa/0003-gfx1013-taskmesh-queries.patch
patches/mesa/0004-radv-gfx103.patch
```

`0001` is the normal BC-250 path and remains active at all times. It exposes the dedicated ACE compute queue and applies the GFX1013 async-compute workaround required by the matching kernel fixes.  
`0002` and `0003` contain the experimental mesh/task-shader and mesh-query support. For GFX1013 their user-visible feature path remains disabled unless `0004` sees `RADV_GFX103=1` at runtime.

For an individual Steam game that needs the experimental path, use:

```text
RADV_GFX103=1 %command%
```

Without `RADV_GFX103`, GFX1013 keeps its normal GFX10.1 software level and the experimental mesh/task features are not exposed.  
With the variable enabled, `0004` promotes the RADV software `gfx_level` to GFX10.3 for that process. This is intentionally experimental: the override affects RADV code paths that key off `gfx_level`, not only the mesh/task extension checks.

Stable Mesa is built with:

```text
-march=x86-64-v3 -mtune=znver2
```

## Patched stable CachyOS lib32-mesa

`lib32-mesa` comes directly from the current CachyOS `mesa/lib32-mesa/PKGBUILD` at the same pinned packaging commit.  
It receives the exact same four GFX1013 patches and runtime gating as stable 64-bit Mesa, so 32-bit Wine/Steam workloads see the same driver behavior.

The clean Arch build container explicitly enables `[multilib]` before dependency resolution.

## Optional patched CachyOS mesa-git

Mesa-Git also uses the current CachyOS PKGBUILD and **unchanged upstream `customization.cfg`**.  
The workflow resolves Mesa `main` first and pins that exact commit through CachyOS' `mesa-userpatches/user.cfg` mechanism, so the source cannot move during a build.

CachyOS' `_lib32=true` remains enabled.  
One Mesa-Git build therefore produces the matched pair:

```text
mesa-git
lib32-mesa-git
```

The Git variant carries a separately rebased copy of the same four-patch series:

```text
patches/mesa-git/0001-gfx1013-compute-queue-fix.patch
patches/mesa-git/0002-gfx1013-mesh-task-shaders.patch
patches/mesa-git/0003-gfx1013-taskmesh-queries.patch
patches/mesa-git/0004-radv-gfx103.patch
```

`0001` remains active regardless of environment variables.  
The GFX1013 mesh/task path from `0002`/`0003` is opt-in through `RADV_GFX103=1`; `0004` provides that runtime override and defaults to disabled.

There is deliberately no separate `series` file. The build script explicitly applies the four numbered patches in order through CachyOS' `mesa-userpatches` mechanism.

To switch explicitly to Git Mesa:

```bash
sudo pacman -S bc250-cachyos/mesa-git bc250-cachyos/lib32-mesa-git
```

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

## Credits

- keyboardspecialist / bombers — reverse engineering work for BC-250 telemetry and the original audio/telemetry work.  
  <https://github.com/keyboardspecialist/bc250-steamos/tree/master/bc250-audio-fix>
- higorprado / higorevop — porting the telemetry patches to Linux 7.x.  
  <https://github.com/higorprado/bc250-8core-telemetry-report>
- DryhoppedIPA — GFX1013 amdgpu and Mesa fixes.  
  <https://github.com/DryhoppedIPA/bc250-gfx1013-fix>
