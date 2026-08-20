# BC-250 CachyOS kernels + Mesa repository

[![Build and publish BC-250 CachyOS kernels and Mesa](https://github.com/MastaG/linux-cachyos-bc250/actions/workflows/build-release.yml/badge.svg)](https://github.com/MastaG/linux-cachyos-bc250/actions/workflows/build-release.yml)

This repository builds three BC-250-specific CachyOS kernels, patched stable Mesa and lib32-mesa packages, and an optional patched mesa-git/lib32-mesa-git pair.  
All packages are published through the same fixed GitHub Release / pacman repository.

Project: <https://github.com/MastaG/linux-cachyos-bc250>  
Packages and repository assets: <https://github.com/MastaG/linux-cachyos-bc250/releases/tag/repo>

## Mesa behavior, performance and stability

The patched Mesa packages enable the GFX1013 async-compute path by default; no environment variable is required for normal use.  
Games that benefit from async compute can see a significant performance improvement. In current BC-250 community testing, Cyberpunk 2077 has shown gains of roughly 10–15 FPS.

Async compute can also increase GPU load and voltage requirements.  
Some BC-250 systems that were previously stable have shown green-screen or black-screen GPU crashes after enabling the async-compute path. Community reports indicate that some boards need a small GPU-voltage increase to remain stable, with around +25 mV being sufficient in several cases. This is not required on every BC-250: if the GPU is stable, no voltage change is needed.

`RADV_GFX103=1` is separate from async compute and should **not** be enabled globally.  
Use it only per-game for titles that need the experimental GFX10.3 mesh-shader path. It has been tested successfully with Final Fantasy VII Rebirth, which currently does not start on the BC-250 without the override in community testing. Mesh shaders work for this test case, but **task shaders are still not working correctly**. Games that depend on task shaders may render incorrectly, hang or crash when `RADV_GFX103=1` is enabled.

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

### 3. Install a kernel

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

### 4. Reboot and verify

```bash
sudo reboot
```

After rebooting:

```bash
uname -r
lsmod | grep nct6687
```

## Optional AMDGPU scheduler tuning

Do **not** add `amdgpu.sched_policy=2` as a required installation step.  
Current BC-250 testing shows that scheduler performance is workload-dependent: some systems or games are slightly faster or smoother with the default hardware scheduler (`sched_policy=0`), while others can benefit from the non-HWS path (`sched_policy=2`). Average FPS and frametime behavior can also move in different directions.

The kernel default is `amdgpu.sched_policy=0`. Test both values on your own system if you want to tune gaming performance or frametimes, and keep the setting that works best for your workload.  
To verify the active value after boot:

```bash
cat /proc/cmdline | grep -o 'amdgpu.sched_policy=[^ ]*'
```

If no value is printed, the normal kernel default (`0`) is in use.

If you previously followed an older version of this README that added `sched_policy=2` as a required setting, remove that dedicated line and rebuild Limine before comparing policies:

```bash
sudo sed -i '/^[[:space:]]*KERNEL_CMDLINE\[default\]+=[[:space:]]*amdgpu\.sched_policy=2[[:space:]]*$/d' /etc/default/limine
sudo limine-mkinitcpio
```

To test `sched_policy=2` on CachyOS with Limine, add it to `/etc/default/limine` and regenerate the Limine initramfs configuration:

```bash
printf '%s\n' 'KERNEL_CMDLINE[default]+=amdgpu.sched_policy=2' | \
  sudo tee -a /etc/default/limine >/dev/null
sudo limine-mkinitcpio
```

Remove that line again to return to the default HWS policy.  
The optional ROCm/KFD runlist-TLB workaround documented below requires hardware scheduling and therefore does **not** operate with `sched_policy=2`.

## Experimental ROCm / KFD kernel support

`0006-bc250-kfd-flush-tlb-by-runlist.patch` is based on the BC-250 ROCm investigation by GabriWar.  
Under KFD hardware scheduling on GFX1013, the normal gfx10 PASID TLB flush can fail to find a VMID because the HWS path does not populate the `ATC_VMID*_PASID_MAPPING` table used by that flush. Rebuilding an active HWS runlist has been measured to clear the stale translation state and is therefore provided as an experimental workaround.

The workaround is **disabled by default** and restricted to PCI device `0x13FE` with GFX IP `10.1.3`. It also refuses to run under non-HWS scheduling or MES.  
Enable it at boot only for ROCm/KFD testing:

```text
amdgpu.bc250_flush_by_runlist=1
```

Or enable/disable it at runtime while HWS is already active:

```bash
echo 1 | sudo tee /sys/module/amdgpu/parameters/bc250_flush_by_runlist
echo 0 | sudo tee /sys/module/amdgpu/parameters/bc250_flush_by_runlist
```

The helper only rebuilds an already-active runlist, preserving the scheduler state instead of accidentally activating an inactive runlist.  
Because the mechanism depends on the hardware scheduler, it is a no-op with `amdgpu.sched_policy=2`; use the normal `sched_policy=0` when testing this ROCm workaround.

`0007-amdgpu-ttm-null-page-guard.patch` is separate from the TLB workaround. TTM allocation failures can legitimately leave NULL entries in a partially populated page vector, while AMDGPU's unpopulate path dereferenced every entry before calling `ttm_pool_free()`. The patch skips NULL entries during the `page->mapping` cleanup; the TTM free path in the supplied Linux 7.2 source already handles those sparse entries.  
This does not fix the compute fault that caused a partial allocation; it prevents that failure from escalating into a kernel NULL-pointer panic during cleanup.

ROCm userspace still requires additional GFX1013-specific work outside this kernel repository. These kernel patches alone should not be read as complete ROCm support.

### ROCm userspace requirements

GabriWar's working stack uses stock ROCm userspace, but adds a GFX1013-specific rocBLAS/Tensile kernel library and a PyTorch build compiled natively for `gfx1013`. The rocBLAS library files are installed under `/opt/rocm/lib/rocblas/library`; without GFX1013 code objects, even basic rocBLAS workloads such as matrix multiplication cannot run correctly on the BC-250.

The current reference setup also uses a small set of runtime settings, including `HSA_ENABLE_SDMA=0`, `GPU_PINNED_MIN_XFER_SIZE=16384` and `TORCH_BLAS_PREFER_HIPBLASLT=0`. Earlier serialization/warm-up workarounds were removed after testing showed they did not address the underlying stale-translation problem.

The userspace side is still experimental and can evolve independently of these kernel patches. For the current build instructions, GFX1013 rocBLAS/Tensile artifacts, PyTorch notes, validation tools and ongoing ROCm investigation, see [GabriWar/bc250-rocm-working](https://github.com/GabriWar/bc250-rocm-working).

## Kernel patch sets

Patches are organized per upstream CachyOS source package rather than per kernel version:

```text
patches/linux-cachyos/
patches/linux-cachyos-rc/
```

`patches/linux-cachyos` is applied to both `linux-cachyos-bc250` and `linux-cachyos-bore-bc250`, since `linux-cachyos` and `linux-cachyos-bore` are built from the same upstream source series.  
`patches/linux-cachyos-rc` is applied only to `linux-cachyos-rc-bc250`. It starts as an exact copy of `patches/linux-cachyos`, since `linux-cachyos-rc` currently also resolves to the Linux 7.2 series (7.3-rc has not been published upstream yet) — but it is a dedicated directory precisely so it can diverge independently once CachyOS starts shipping a real 7.3-rc PKGBUILD.

### linux-cachyos patch set

Applied to `linux-cachyos-bc250`, `linux-cachyos-rc-bc250` and `linux-cachyos-bore-bc250`:

```text
0001-bc250-8core-telemetry-gpu-activity.patch
0003-nct6687d-hwmon.patch
0004-gfx1013-pasid-tlb-invalidation.patch
0005-gfx1013-compute-gfxoff-guard.patch
0006-bc250-kfd-flush-tlb-by-runlist.patch
0007-amdgpu-ttm-null-page-guard.patch
0008-cyan-skillfish-sclk-range.patch
```

There is intentionally no `0002-bc250-audio.patch` here. That Cyan Skillfish DP spread-spectrum fix (disabling `ignore_dpref_ss`) is required on the older Linux 7.1 series this repository previously built, but it is already present upstream in the Linux 7.2 source, so applying it again would fail to patch cleanly.

This patch set contains:

> The telemetry/activity and tunable GFXCLK/activity/metrics cache logic is consolidated in `0001-bc250-8core-telemetry-gpu-activity.patch`.  
> All three cache windows default to 25 ms and can still be changed at runtime or disabled with `0`.

- automatic 6-core / hybrid 8-core Cyan Skillfish SMU telemetry handling;
- correct per-core telemetry for unlocked 8-core BC-250 systems;
- GPU activity reporting through GPU Metrics and `GPU_LOAD` derived from the GFX ring's emitted-fence count (Cyan Skillfish's `GRBM_STATUS` register reads back all-ones regardless of GPU state, which previously pegged `gpu_busy_percent` at 100% even at idle), with a tunable per-device cache (`amdgpu.cs_activity_cache_ms`, default 25 ms, `0` disables it);
- safe GFX clock handling for the hybrid metrics layout, with tunable `GetGfxclkFrequency` mailbox caching (`amdgpu.cs_gfxclk_cache_ms`, default 25 ms, `0` disables it);
- a tunable cache (`amdgpu.cs_metrics_cache_ms`, default 25 ms, `0` disables it) for the bulk SMU metrics table refresh backing temperature, power, voltage, socclk/vclk/dclk/uclk and throttler-status reads. Upstream's own internal debounce for that transfer is only 1 ms, so every distinct hwmon attribute a monitoring tool polls in one cycle could otherwise trigger its own SMU mailbox round trip;
- corrected `gpu_metrics` CPU-power reporting and overflow-safe 16-bit power export;
- optional full BC-250 APU telemetry through `pp_dpm_socclk` (`amdgpu.cs_full_telemetry=1`), disabled by default so the normal sysfs clock ABI is preserved;
- the v33 merged GFX1013 PASID TLB invalidation fix;
- the GFX1013 compute GFXOFF guard;
- an **opt-in** KFD/HWS runlist rebuild workaround for stale ROCm compute TLB translations (`amdgpu.bc250_flush_by_runlist=1`);
- a defensive AMDGPU TTM NULL-page guard so partially populated BO cleanup cannot dereference a missing page;
- a widened Cyan Skillfish SMU SCLK range (350–2230 MHz, up from the stock 1000–2000 MHz) so userspace SMU-based governors such as [filippor/cyan-skillfish-governor](https://github.com/filippor/cyan-skillfish-governor/tree/smu) can drive the full clock range;
- integration of the external `nct6687` hwmon/PWM driver.

## BC-250 APU telemetry

The main telemetry patch now includes the additional Cyan Skillfish metrics work while keeping the normal interfaces safe by default.  
The existing automatic 6-core / hybrid 8-core mapping, GPU activity sampling and 25 ms activity/GFXCLK caches remain unchanged.

The `gpu_metrics` export now places the VDDCR_VDD rail in `average_cpu_power` instead of incorrectly exposing it as SoC power. The VDDCR_GFX rail continues to feed `average_gfx_power`, while `average_soc_power` remains at the unsupported sentinel because this firmware table has no separate SoC-rail power value.  
The GPU Metrics v2.2 power fields are only 16-bit milliwatt values, so values above their usable range are saturated instead of silently wrapping to a much lower number. `0xffff` remains reserved as the kernel's unsupported-value sentinel.

A more detailed human-readable APU telemetry view is also available, but is **opt-in** because replacing the normal `pp_dpm_socclk` contents unconditionally would break the standard sysfs clock interface. Enable it at runtime with:

```bash
echo 1 | sudo tee /sys/module/amdgpu/parameters/cs_full_telemetry
cat /sys/bus/pci/devices/0000:01:00.0/pp_dpm_socclk
```

Or enable it at boot with:

```text
amdgpu.cs_full_telemetry=1
```

The diagnostic view reports the detected layout, per-core clocks/power/temperature/C0 residency, L3 clocks and temperatures, GFX/SOC/VCLK/DCLK/memory clocks, edge temperature, CPU and GPU rail voltage/current/power, socket power and throttler status.  
On the discovered 8-core hybrid firmware layout there is no table slot for core 0 power or core 7 C0 residency, and only cores 4 and 5 have per-core temperature slots; these unavailable values are shown as `n/a` rather than interpreting unrelated fields as telemetry.

While `cs_full_telemetry=1` is active, `pp_dpm_socclk` is intentionally used as the diagnostic output instead of its normal single-clock listing. Return to the standard behavior at runtime with:

```bash
echo 0 | sudo tee /sys/module/amdgpu/parameters/cs_full_telemetry
```

## GPU telemetry cache tunables

Reading GPU telemetry on Cyan Skillfish means talking to the SMU firmware, and doing that too often is a real stability risk on this board. This is also why some userspace SMU-based governors, such as [cyan-skillfish-governor](https://github.com/filippor/cyan-skillfish-governor/tree/smu), offer a `set-method = "kernel"` option to set clocks through the kernel interface instead of the SMU directly.

Three independent caches bound how often the kernel talks to the SMU for telemetry:

| Parameter | Default | Covers |
|---|---|---|
| `amdgpu.cs_activity_cache_ms` | 25 ms | `gpu_busy_percent` / `GPU_LOAD` sampling |
| `amdgpu.cs_gfxclk_cache_ms` | 25 ms | The `GetGfxclkFrequency` SMU mailbox message |
| `amdgpu.cs_metrics_cache_ms` | 25 ms | The bulk SMU metrics table: temperature, power, voltage, socclk/vclk/dclk/uclk and throttler status |

All three default to 25 ms, matching [MangoHud](https://github.com/flightlessmango/MangoHud)'s default telemetry poll interval, since that is the most common way BC-250 users watch these values live while gaming. Each is independently tunable and `0` disables that cache (every read then hits the SMU directly).

Change any of them at runtime:

```bash
echo 50 | sudo tee /sys/module/amdgpu/parameters/cs_activity_cache_ms
echo 50 | sudo tee /sys/module/amdgpu/parameters/cs_gfxclk_cache_ms
echo 50 | sudo tee /sys/module/amdgpu/parameters/cs_metrics_cache_ms
```

Or set them permanently at boot, the same way as the other `amdgpu.*` parameters documented above:

```text
amdgpu.cs_activity_cache_ms=50 amdgpu.cs_gfxclk_cache_ms=50 amdgpu.cs_metrics_cache_ms=50
```

`gpu_busy_percent` itself no longer touches the SMU or any hardware register at all: it is derived purely from the GFX ring's existing software fence-tracking, the same activity signal that already backs `fdinfo`'s `drm-engine-gfx`. `cs_activity_cache_ms` only bounds how often that essentially free sample is retaken, not SMU traffic.

## cyan-skillfish-governor recommendations

The 8-core hybrid telemetry decoding in this repository's kernel patches is unofficial and community-reverse-engineered; the Cyan Skillfish SMU firmware was written with 6 CPU cores in mind, and the extra decoding only applies to boards running a patched BIOS that unlocks the two extra cores.

For [cyan-skillfish-governor](https://github.com/filippor/cyan-skillfish-governor/tree/smu) users on this kernel:

- Use `set-method = "kernel"`. The widened Cyan Skillfish SMU SCLK range above exists specifically to make this option viable end to end. Setting frequency through the kernel interface avoids the extra SMU mailbox round-trips that `set-method = "smu"` requires, and excessive SMU traffic is a real crash risk on this board.
- Leave `fix-metrics = false` and `fix-freq = false`. Both bind-mount a corrected value over a sysfs file to work around inaccurate stock telemetry, but this repository's kernel patches already fix that telemetry at the source: `gpu_metrics`'s `average_gfx_activity` and `gpu_busy_percent` are populated by the same corrected kernel function, and `freq1_input` already reflects a real `GetGfxclkFrequency` SMU read. Enabling either on this kernel only adds an extra bind mount (and, for `fix-freq`, a second independent SMU connection) to duplicate a number the kernel already reports correctly.

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

All five BC-250 Mesa patches are applied at build time, in order:

```text
patches/mesa/0001-gfx1013-compute-queue-fix.patch
patches/mesa/0002-gfx1013-mesh-task-shaders.patch
patches/mesa/0003-gfx1013-taskmesh-queries.patch
patches/mesa/0004-radv-gfx103.patch
patches/mesa/0005-bc250-fsr4-selective-sdot4x8.patch
```

`0001` is the normal BC-250 path and remains active at all times. It exposes the dedicated ACE compute queue and applies the GFX1013 async-compute workaround required by the matching kernel fixes.  
`0002` and `0003` contain the experimental mesh/task-shader and mesh-query plumbing. For GFX1013 their user-visible feature path remains disabled unless `0004` sees `RADV_GFX103=1` at runtime.  
`0005` is always active regardless of environment variables. It splits the NIR fallback expansion for the signed 4x8 dot product (`sdot_4x8_a_b`, used by `[iu]dp4a`) into Mesa's original balanced sum and a right-leaning reassociated sum, selecting between them based on whether the `sdot_4x8_iadd` accumulator is a compile-time constant. A 64-shader FSR4 corpus found that reassociating unconditionally is a large win on most kernels but causes catastrophic register-pressure/spilling regressions on specific shaders that accumulate into a constant; the constant case keeps the balanced lowering, everything else gets the reassociated one. This is EXP-028 from BC-250 FSR4 testing (David Moraza Sanchez, [dmorazasanchez/bc250-fsr4, `v2` branch](https://github.com/dmorazasanchez/bc250-fsr4/tree/v2)), verified with FSR 4.1.1 in Cyberpunk 2077, superseding the earlier unconditional-reassociation patch.

For an individual Steam game that specifically needs the experimental mesh-shader path, use:

```text
RADV_GFX103=1 %command%
```

Without `RADV_GFX103`, GFX1013 keeps its normal GFX10.1 software level and the experimental mesh/task features are not exposed.  
With the variable enabled, `0004` promotes the RADV software `gfx_level` to GFX10.3 for that process. Final Fantasy VII Rebirth is currently the main tested use case and its mesh-shader path works with this override. **Task shaders are still not working correctly**, so games that rely on task shaders may render incorrectly, hang or crash. Do not export `RADV_GFX103=1` globally; enable it only for games that need it.

Stable Mesa is built with:

```text
-march=x86-64-v3 -mtune=znver2
```

## Patched stable CachyOS lib32-mesa

`lib32-mesa` comes directly from the current CachyOS `mesa/lib32-mesa/PKGBUILD` at the same pinned packaging commit.  
It receives the exact same five GFX1013 patches and runtime gating as stable 64-bit Mesa, so 32-bit Wine/Steam workloads see the same driver behavior.

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

The Git variant carries a separately rebased copy of the same five-patch series:

```text
patches/mesa-git/0001-gfx1013-compute-queue-fix.patch
patches/mesa-git/0002-gfx1013-mesh-task-shaders.patch
patches/mesa-git/0003-gfx1013-taskmesh-queries.patch
patches/mesa-git/0004-radv-gfx103.patch
patches/mesa-git/0005-bc250-fsr4-selective-sdot4x8.patch
```

`0001` and `0005` remain active regardless of environment variables.  
The experimental GFX1013 mesh/task path from `0002`/`0003` is opt-in through `RADV_GFX103=1`; `0004` provides that runtime override and defaults to disabled. The same limitations as stable Mesa apply: mesh shaders are the currently tested use case, while task shaders are still not working correctly.

There is deliberately no separate `series` file. The build script explicitly applies the five numbered patches in order through CachyOS' `mesa-userpatches` mechanism.

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
- GabriWar — BC-250 ROCm/KFD TLB investigation, runlist invalidation workaround and AMDGPU TTM NULL-page guard.  
  <https://github.com/GabriWar/bc250-rocm-working>
- punsh — additional BC-250 APU telemetry and GPU Metrics power-field fixes.
- David Moraza Sanchez (dmorazasanchez) — BC-250 FSR4 EXP-028 selective signed 4x8 dot-product fallback lowering.  
  <https://github.com/dmorazasanchez/bc250-fsr4/tree/v2>
- FilippoR / ViRazY - For the kernel GPU frequency ranges
