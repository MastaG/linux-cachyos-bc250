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

Or install [`linux-cachyos-bc250-meta`](#linux-cachyos-bc250-meta) instead, which pulls in the stable kernel, its headers, and the other BC-250 extras (currently `bc250-dual-audio`) together, and picks up any new ones added to it in the future on a normal `pacman -Syu`.

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

### 5. Running 8 CPU cores? Check which BIOS you have

Check what your board reports:

```bash
lscpu | grep '^Core(s) per socket'
```

Skip the rest of this step if that says `6` — everything works out of the box and nothing here applies to you.

The BC-250's SMU firmware was written for 6 CPU cores. If your BIOS unlocks all 8, that firmware has to report per-core telemetry it was never designed to report, and **which BIOS you flashed decides how complete that telemetry is**. The kernel picks the right decoding automatically, so there is nothing to configure in the normal case — but you should know which of these two you are in:

| Your BIOS | What to do | What you get |
|---|---|---|
| Unlocks 8 cores **and** patches the SMU (current community BIOS) | Nothing. This is the default. | Clock, power, temperature and C0 residency for **all 8 cores** |
| Unlocks 8 cores on the **stock, unpatched** SMU (older BIOS) | Add `amdgpu.cs_legacy_8core_metrics=1` | Correct but **incomplete** — see below |

A prebuilt, easy-to-flash UEFI firmware carrying both the core unlock and the SMU patch is published here:

<https://github.com/Forbidden-Darkness/AMD-BC-250-UEFI-v2.2-Firmware-Menu-Script/releases>

Follow that repository's own instructions — it ships a script that unpacks the firmware to a USB stick and reboots you into the flashing environment. Flashing firmware can brick a board if it is interrupted, so read its README first and do not do it on a machine you cannot afford to lose.

If you would rather not flash anything, the kernel parameter is a perfectly good answer. Set it on the stock BIOS with 8 cores unlocked and telemetry becomes correct instead of scrambled — you just do not get the full picture, because that firmware has no table slot for some of it:

```text
amdgpu.cs_legacy_8core_metrics=1
```

| Reading | Stock BIOS, 8 cores unlocked |
|---|---|
| Core clock | All 8 cores |
| Core power | Cores 1-7 (core 0 has no slot) |
| Core temperature | Cores 4 and 5 only |
| C0 residency | Cores 0-6 (core 7 has no slot) |
| GFX clock, voltages, socket power, temperatures | Complete |

Missing values are reported as unavailable rather than filled in with a number belonging to a different field, so nothing lies to you.

**Do not set this parameter if you are on the patched BIOS** — it decodes the table the wrong way and your telemetry will look scrambled. If you are unsure which BIOS you have, boot without the parameter and look at per-core temperatures in `amdgpu_top`: on the patched BIOS all eight are plausible room-temperature-and-up values. If most of them read zero, you are on the older BIOS and want the parameter.

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
`patches/linux-cachyos-rc` is applied only to `linux-cachyos-rc-bc250`, and the two sets are now anchored to different kernels: `patches/linux-cachyos` targets the **Linux 7.2** series, `patches/linux-cachyos-rc` targets **Linux 7.3-rc**. That is exactly why the directory was split.

The two sets currently contain the same eight patches with the same content — all of them applied to 7.3-rc1 unmodified. Only the hunk offsets and blob hashes differ, because each set is regenerated against its own base so that future rebases are measured from the right kernel.

### Kernel patch set

Both sets carry the same eight patches — `patches/linux-cachyos` for `linux-cachyos-bc250` and `linux-cachyos-bore-bc250` (7.2), `patches/linux-cachyos-rc` for `linux-cachyos-rc-bc250` (7.3-rc):

```text
0001-bc250-8core-telemetry-gpu-activity.patch
0003-nct6687d-hwmon.patch
0004-gfx1013-pasid-tlb-invalidation.patch
0005-gfx1013-compute-gfxoff-guard.patch
0006-bc250-kfd-flush-tlb-by-runlist.patch
0007-amdgpu-ttm-null-page-guard.patch
0008-cyan-skillfish-sclk-range.patch
0009-bc250-40cu-unlock.patch
```

There is intentionally no `0002-bc250-audio.patch` here. That Cyan Skillfish DP spread-spectrum fix (disabling `ignore_dpref_ss`) was required on the older Linux 7.1 series this repository previously built, but it has been upstream since Linux 7.2, so applying it again would fail to patch cleanly.

This patch set contains:

> The telemetry/activity and tunable GFXCLK/activity/metrics cache logic is consolidated in `0001-bc250-8core-telemetry-gpu-activity.patch`.  
> All three cache windows default to 25 ms and can still be changed at runtime or disabled with `0`.

- automatic 6-core / 8-core Cyan Skillfish SMU metrics layout detection;
- correct per-core telemetry for unlocked 8-core BC-250 systems, matched to the patched SMU firmware in the current community BIOS, with an opt-in fallback (`amdgpu.cs_legacy_8core_metrics=1`) for an older BIOS that unlocks the cores without the SMU metrics patch;
- GPU activity reporting through GPU Metrics and `GPU_LOAD` derived from the GFX ring's emitted-fence count (Cyan Skillfish's `GRBM_STATUS` register reads back all-ones regardless of GPU state, which previously pegged `gpu_busy_percent` at 100% even at idle), with a tunable per-device cache (`amdgpu.cs_activity_cache_ms`, default 25 ms, `0` disables it);
- GFX clock read through the `GetGfxclkFrequency` SMU mailbox, with tunable caching (`amdgpu.cs_gfxclk_cache_ms`, default 25 ms, `0` disables it);
- a tunable cache (`amdgpu.cs_metrics_cache_ms`, default 25 ms, `0` disables it) for the bulk SMU metrics table refresh backing temperature, power, voltage, socclk/vclk/dclk/uclk and throttler-status reads. Upstream's own internal debounce for that transfer is only 1 ms, so every distinct hwmon attribute a monitoring tool polls in one cycle could otherwise trigger its own SMU mailbox round trip;
- corrected `gpu_metrics` CPU-power reporting and overflow-safe 16-bit power export;
- optional full BC-250 APU telemetry through `pp_dpm_socclk` (`amdgpu.cs_full_telemetry=1`), disabled by default so the normal sysfs clock ABI is preserved;
- the v33 merged GFX1013 PASID TLB invalidation fix;
- the GFX1013 compute GFXOFF guard;
- an **opt-in** KFD/HWS runlist rebuild workaround for stale ROCm compute TLB translations (`amdgpu.bc250_flush_by_runlist=1`);
- a defensive AMDGPU TTM NULL-page guard so partially populated BO cleanup cannot dereference a missing page;
- a widened Cyan Skillfish SMU SCLK range (350–2230 MHz, up from the stock 1000–2000 MHz) so userspace SMU-based governors such as [filippor/cyan-skillfish-governor](https://github.com/filippor/cyan-skillfish-governor/tree/smu) can drive the full clock range;
- integration of the external `nct6687` hwmon/PWM driver.
- an **opt-in** 40 CU unlock for the harvested shader engines (`amdgpu.bc250_cc_write_mode=3`), described below.

## Optional 40 CU unlock

The BC-250 is a salvaged PS5 APU and ships with **24 of its 40 RDNA2 compute units enabled**. The remaining 16 were fused off by firmware policy rather than because they are defective: they still have power, clocks and matching CGTS configuration, and no power gating is active on them.

`0009-bc250-40cu-unlock.patch` re-enables them by writing two hardware registers during CU enumeration, based on the research and testing in [duggasco/bc250-40cu-unlock](https://github.com/duggasco/bc250-40cu-unlock).

Both registers are required, and this is the part that took the original author a controlled experiment to establish — neither one alone does anything:

| Register | Role | Stock | Unlocked |
|---|---|---|---|
| `CC_GC_SHADER_ARRAY_CONFIG` | enumeration mask: how many CUs the driver, RADV and KFD *see* | `0xfff80000` | `0xffe00000` |
| `SPI_PG_ENABLE_STATIC_WGP_MASK` | dispatch gate: where the SPI is allowed to *send waves* | `0x7` (WGP 0–2) | `0x1F` (WGP 0–4) |

Clearing only the enumeration mask makes the driver report 40 CUs while the hardware still dispatches to 24; enabling only dispatch leaves the driver generating work for 24. A third register, `RLC_PG_ALWAYS_ON_WGP_MASK`, keeps the newly enabled WGPs powered.

**It is disabled by default and does nothing unless you ask for it.** The module parameter defaults to `0`, and every register write is additionally guarded on PCI device ID `0x13FE`, so the patch is inert on any other GPU. There is no permanent change to the hardware: boot without the setting and the board is back to 24 CUs.

Enable it at boot:

```text
amdgpu.bc250_cc_write_mode=3
```

Or persist it with a modprobe drop-in:

```bash
printf '%s\n' 'options amdgpu bc250_cc_write_mode=3' | \
  sudo tee /etc/modprobe.d/bc250-40cu.conf >/dev/null
```

Verify after rebooting:

```bash
dmesg | grep active_cu_number     # expect: active_cu_number 40
dmesg | grep bc250-40cu           # shows the before/after register values
RADV_DEBUG=info vulkaninfo --summary 2>&1 | grep num_cu   # expect: num_cu = 40
```

### Thermals — read this before enabling

The extra CUs cost power. The upstream measurements, on a Vulkan LLM inference workload, were roughly **1.6x throughput for about +30 W and +4 °C** when clocks are held at 1500 MHz. Left at the governor's 2 GHz default the same board drew around 181 W and reached **96 °C**, which is not a sustainable operating point.

If you enable this, cap the clocks. With [cyan-skillfish-governor](https://github.com/filippor/cyan-skillfish-governor/tree/smu), the widened SCLK range from `0008` makes 1500 MHz / 900 mV reachable as a safe point, and that is the combination the author recommends. Watch temperatures on the first few runs rather than assuming your board behaves like theirs.

### Not every board may be healthy at 40 CUs

Harvest patterns vary. Boards whose disabled CUs are contiguous appear to be policy-harvested, but a scattered pattern may indicate genuinely defective silicon. The upstream project ships tooling to map your own board and to mask individual WGPs through `amdgpu.disable_cu=SE.SH.WGP` if some of the unlocked units turn out to be unstable. Masking works at WGP granularity, so disabling one CU disables its partner.

This patch is carried unmodified apart from one rebase: upstream Linux added an `adev` argument to `amdgpu_gfx_parse_disable_cu()` after the patch was written, so its context needed updating. The register writes themselves are untouched.

## BC-250 APU telemetry

The main telemetry patch includes the additional Cyan Skillfish metrics work while keeping the normal interfaces safe by default.  
GPU activity sampling and the 25 ms activity/GFXCLK caches are unchanged.

### 6-core and 8-core metrics layouts

The Cyan Skillfish SMU firmware was written for 6 CPU cores. On a BIOS that unlocks all 8, the firmware's metrics table changes shape, and the kernel has to decode it differently. The layout is selected automatically from the number of physical cores the CPU reports, so nothing normally needs configuring:

| Cores detected | Layout used |
|---|---|
| 6 | Stock Cyan Skillfish table |
| 8 | 8-core table as produced by the patched SMU firmware |

The 8-core layout matches the SMU metrics patch in [rw-r-r-0644/bc250-smu-unlock](https://github.com/rw-r-r-0644/bc250-smu-unlock), which is carried by the current community BIOS ([prebuilt firmware here](https://github.com/Forbidden-Darkness/AMD-BC-250-UEFI-v2.2-Firmware-Menu-Script/releases); see [step 5](#5-running-8-cpu-cores-check-which-bios-you-have) of the quick start). That firmware widens every per-core array to eight entries and keeps its own slot for each remaining field, so **all eight cores report clock, power, temperature and C0 residency**, with no gaps. The struct offsets in the kernel patch are taken directly from that firmware patch's store instructions rather than guessed, and the total export length is asserted at compile time against the 0x11c bytes the firmware actually DMAs.

If you unlocked 8 cores on an **older BIOS that does not carry the SMU metrics patch**, that firmware instead packed the extra cores into the original 116-byte table, leaving several fields with no slot at all. Select that older decoding with:

```text
amdgpu.cs_legacy_8core_metrics=1
```

or at runtime with `echo 1 | sudo tee /sys/module/amdgpu/parameters/cs_legacy_8core_metrics`. Telemetry is then correct but incomplete: core power covers cores 1-7, only cores 4 and 5 have a temperature, C0 residency covers cores 0-6, and the stock GfxclkFrequency slot is occupied by C0Residency[6], so GFX clock is read through the `GetGfxclkFrequency` SMU message instead. Everything with no slot is reported as unavailable rather than being filled in from an unrelated field.

Leave the parameter off unless your telemetry is visibly wrong on 8 cores — on the patched firmware it produces garbage, which is exactly what the old default did on the new firmware. If you are unsure which BIOS you have, compare per-core temperatures in `amdgpu_top`: on the patched firmware with the default setting all eight are plausible, and with the wrong setting most read as zero.

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
Its first line names the active layout (`6-core stock`, `8-core` or `8-core legacy`), which is the quickest way to confirm what the kernel decided. In the legacy layout the firmware has no table slot for core 0 power or core 7 C0 residency, and only cores 4 and 5 have per-core temperature slots; those values are shown as `n/a` rather than interpreting unrelated fields as telemetry.

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

The 8-core telemetry decoding in this repository's kernel patches is unofficial and community-reverse-engineered; the Cyan Skillfish SMU firmware was written with 6 CPU cores in mind, and the extra decoding only applies to boards running a patched BIOS that unlocks the two extra cores.

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

## Optional BC-250 dual-output audio

`bc250-dual-audio` packages [MastaG/bc250-dual-audio](https://github.com/MastaG/bc250-dual-audio), a WirePlumber policy that gives the BC-250 two permanent, mutually-exclusive outputs:

- **Native HDMI/DisplayPort** — the normal ACP sink, untouched and EDID/ELD-driven;
- **Dolby Digital 5.1 (AC3 Encoder)** — a permanent virtual sink. Selecting it moves normal playback over, waits for native HDMI to suspend, then opens a hidden `plug:bc250_a52 -> hw:Generic,3` backend; selecting native HDMI again tears that backend down first. A runtime hardware lock between the AC3 arbiter and a patched ALSA monitor keeps a DP/HDMI hotplug from racing the AC3 backend into `EBUSY`.

Not installed by default — install it explicitly:

```bash
sudo pacman -S bc250-dual-audio
systemctl --user restart pipewire pipewire-pulse wireplumber
```

Then verify with the diagnostic script it ships:

```bash
/usr/share/bc250-dual-audio/check.sh
```

Rebased on and tested against **WirePlumber 0.5.17**. Installing prints a warning if your WirePlumber version differs, or if its stock ALSA monitor is not the exact file this override was rebased onto — that override is a full replacement of that script, so a WirePlumber update can silently leave it based on the wrong source. See the [upstream README](https://github.com/MastaG/bc250-dual-audio) for the full mode-authority model, mutual-exclusion behavior and expected log output while switching.

Packaging note: its ALSA-monitor override installs to `/usr/local/share/wireplumber/scripts/monitors/alsa.lua` rather than `/usr/share`. That is not a leftover — `wireplumber`'s own package owns the `/usr/share` copy of that exact file, and `/usr/local/share` precedes `/usr/share` in `XDG_DATA_DIRS`, so this shadows the stock script without a package conflict and without being overwritten when `wireplumber` updates. This package's other script, which has no name collision with anything `wireplumber` ships, installs normally under `/usr/share`.

## linux-cachyos-bc250-meta

A pure metapackage — it installs no files of its own, it just depends on the recommended BC-250 software set:

- `linux-cachyos-bc250`
- `linux-cachyos-bc250-headers`
- `bc250-dual-audio`

```bash
sudo pacman -S linux-cachyos-bc250-meta
```

The point of it is future-proofing: as more BC-250-specific extras land in this repository (for example a VCN unlock, once upstream support for that exists), they get added to this package's `depends=` array instead of requiring users to notice and install each one by hand. Once you have `linux-cachyos-bc250-meta` installed, a plain `sudo pacman -Syu` picks up any newly added extra the next time this package's version is bumped for that — the same mechanism that already updates every other package in this repository, extended to cover the set as a whole.

Installing it does not remove the ability to manage those packages individually, and does not pull in the RC or BORE kernel variants — it only ever tracks the stable kernel.

## Patched stable CachyOS Mesa

The workflow resolves a single exact commit from `CachyOS/CachyOS-PKGBUILDS` and downloads the current stable Mesa packaging from that revision.  
The upstream Mesa version and epoch remain unchanged; the GitHub Actions run number is appended to `pkgrel`.

All five BC-250 Mesa patches are applied at build time, in order:

```text
patches/mesa/0001-gfx1013-compute-queue-fix.patch
patches/mesa/0002-gfx1013-mesh-task-shaders.patch
patches/mesa/0003-gfx1013-taskmesh-queries.patch
patches/mesa/0004-radv-gfx103.patch
patches/mesa/0005-bc250-fsr4-v3.patch
```

`0001` is the normal BC-250 path and remains active at all times. It exposes the dedicated ACE compute queue and applies the GFX1013 async-compute workaround required by the matching kernel fixes.  
`0002` and `0003` contain the experimental mesh/task-shader and mesh-query plumbing. For GFX1013 their user-visible feature path remains disabled unless `0004` sees `RADV_GFX103=1` at runtime.  
`0005` is always active regardless of environment variables. GFX1013 has no working packed signed dot product, so `sdot_4x8_iadd` (used by `[iu]dp4a`) falls back to software. The patch makes that fallback much cheaper in two ways: a dense-reduction prepass that expands the largest FSR4 reduction kernels into signed 24-bit multiply chains, and a deferred lowering round that holds the remaining packed `SDot` operations through one full NIR optimization pass before restoring the real capability set and lowering them. Keeping the `SDot` intact lets Mesa's own `iadd(sdot(a, b, 0), c)` fold absorb FSR4's accumulator wrapper, which is what shortens the live ranges that were spilling. A 64-shader FSR4 capture found register pressure and occupancy, not static instruction count, are what actually govern runtime: the worst shader in the corpus dropped from 1314 VGPR spills at 4 waves/SIMD to 0 spills at 6 waves/SIMD, despite a higher naive instruction-cost estimate. This never advertises hardware dot-product support and never emits the broken `v_dot4_i32_i8`. Based on EXP-042B (V3) from BC-250 FSR4 testing (David Moraza Sanchez, [dmorazasanchez/bc250-fsr4, `v3` branch](https://github.com/dmorazasanchez/bc250-fsr4/tree/v3)), verified with FSR 4.1.1 in Cyberpunk 2077 at 63 FPS (up from 58 FPS pre-V3), superseding the earlier EXP-028 selective-reassociation patch.

The patch is carried as upstream wrote it, apart from two hunks dropped while rebasing onto this tree: the GFX1013 compute-queue change and the `RADV_GFX103` override, which duplicate `0001` and `0004` byte-for-byte and would otherwise fail to apply twice. The patch header records that.

One part of it is easy to misread. `0005` raises the LDS spill-slot budget for GFX1013 compute shaders that are already spilling heavily (128–255 spill slots). That deliberately costs occupancy, because in ACO every spill slot which does not fit in LDS goes to scratch instead, and scratch on this APU is backed by shared system memory. Keeping that traffic on-die is worth more here than the lost waves: removing this override measured roughly 12 ms versus 8 ms of OptiScaler frame time on real BC-250 hardware. It is not a mistake, and it should not be "simplified" away.

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
patches/mesa-git/0005-bc250-fsr4-v3.patch
```

`0001` and `0005` remain active regardless of environment variables.  
The experimental GFX1013 mesh/task path from `0002`/`0003` is opt-in through `RADV_GFX103=1`; `0004` provides that runtime override and defaults to disabled. The same limitations as stable Mesa apply: mesh shaders are the currently tested use case, while task shaders are still not working correctly.

There is deliberately no separate `series` file. The build script explicitly applies the five numbered patches in order through CachyOS' `mesa-userpatches` mechanism.

To switch explicitly to Git Mesa:

```bash
sudo pacman -S bc250-cachyos/mesa-git bc250-cachyos/lib32-mesa-git
```

## FSR4 isolation testing driver (opt-in, for testers)

This harness exists to A/B individual FSR4 patch pieces on real hardware, using a swappable RADV-only driver. It is **idle** unless a question is open; the packages it publishes track whatever `patches/mesa-testing/0005` currently carries.

```bash
sudo pacman -Syu vulkan-radeon-testing lib32-vulkan-radeon-testing   # try it
sudo pacman -Syu vulkan-radeon lib32-vulkan-radeon                   # go back
```

They `provide`/`conflict` the normal `vulkan-radeon` packages, so swapping is one command each way and nothing else on the system changes. Only the RADV driver differs; kernels and stable Mesa are untouched.

### Result of the V3 bisection (2026-08-25, settled)

Reverting the trimmed patch to upstream's full form restored performance, but restored four pieces at once. Bisecting on hardware isolated the one that matters:

| Variant | Latency / fps | Verdict |
|---|---|---|
| Full upstream V3 | ~4 ms, ~89 fps | fast — reference |
| Trimmed (four pieces removed) | ~6 ms, ~80 fps | slow |
| Trimmed + LDS spill override | ~6 ms, ~80 fps | eliminated |
| Positive control (= full upstream) | ~4.2 ms, ~89 fps | harness validated |
| **Full minus spill override minus wrapper rules** | **~4 ms, ~89 fps** | **the answer** |

The **`imad24_ir3` MAD-chain lowering** is what makes V3 fast. The LDS spill override and the `iadd(0, OpSDot)` wrapper rules earn nothing and are no longer shipped.

Two things that measurement overturned, worth recording because both are counterintuitive:

- The MAD chain emits roughly **75% more instructions** than the balanced/`add3` form, since `v_mad_i32_i24` is VOP3 and cannot take SDWA byte-selects. It is faster regardless: the chain keeps one accumulator live where `add3` needs four products live at once, and on these shaders register pressure dominates instruction count.
- The spill override was justified as moving spill traffic from system-memory scratch onto on-die LDS. Plausible, and wrong — adding it alone reproduced the full regression.

The positive control was the step that made the rest trustworthy: the testing driver is built through a reduced single-package PKGBUILD, so confirming it reproduces the known-good numbers is what separates "this piece does nothing" from "the harness is broken".

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
- David Moraza Sanchez (dmorazasanchez) — BC-250 FSR4 EXP-042B (V3) deferred SDot lowering.  
  <https://github.com/dmorazasanchez/bc250-fsr4/tree/v3>
- FilippoR / ViRazY - For the kernel GPU frequency ranges
- duggasco — BC-250 40 CU unlock: dual-register (CC + SPI) research, testing and tooling.  
  <https://github.com/duggasco/bc250-40cu-unlock>
- rw-r-r-0644 — BC-250 SMU unlock, including the 8-core metrics firmware patch this repository's kernel decoding is derived from.  
  <https://github.com/rw-r-r-0644/bc250-smu-unlock>
- Forbidden-Darkness — prebuilt BC-250 UEFI firmware bundling the 8-core unlock with the SMU telemetry patch, and the script that flashes it.  
  <https://github.com/Forbidden-Darkness/AMD-BC-250-UEFI-v2.2-Firmware-Menu-Script/releases>
