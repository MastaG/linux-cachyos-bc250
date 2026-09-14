# Patch sets and hardware details

Everything this repository changes in the kernel and in Mesa, and the hardware
detail behind those changes. For installing and using the packages, see the
[README](../README.md).

---

## Kernel patch sets

Patches are organized per upstream CachyOS source package rather than per kernel version:

```text
patches/linux-cachyos/
patches/linux-cachyos-rc/
```

`patches/linux-cachyos` is applied to both `linux-cachyos-bc250` and `linux-cachyos-bore-bc250`, since `linux-cachyos` and `linux-cachyos-bore` are built from the same upstream source series.  
`patches/linux-cachyos-rc` is applied only to `linux-cachyos-rc-bc250`, and the two sets are now anchored to different kernels: `patches/linux-cachyos` targets the **Linux 7.2** series, `patches/linux-cachyos-rc` targets **Linux 7.3-rc**. That is exactly why the directory was split.

The two sets currently contain the same eleven patches with the same content. Only the hunk offsets and blob hashes differ, because each set is regenerated against its own base so that future rebases are measured from the right kernel. A test asserts that: `KernelPatchSetTests` compares the two directories by patch *substance* — the files touched and the lines changed — so a patch added to one set and forgotten in the other fails before CI ever builds it.

### Kernel patch set

Both sets share these eleven BC-250 patches — `patches/linux-cachyos` for `linux-cachyos-bc250` and `linux-cachyos-bore-bc250` (7.2), `patches/linux-cachyos-rc` for `linux-cachyos-rc-bc250` (7.3-rc):

```text
0001-bc250-8core-telemetry-gpu-activity.patch
0003-nct6687d-hwmon.patch
0004-gfx1013-pasid-tlb-invalidation.patch
0005-gfx1013-compute-gfxoff-guard.patch
0006-bc250-kfd-flush-tlb-by-runlist.patch
0007-amdgpu-ttm-null-page-guard.patch
0008-cyan-skillfish-sclk-range.patch
0009-bc250-40cu-unlock.patch
0011-gud-bound-tv-mode-count.patch
0012-dcn201-hdmi21-pcon.patch
0013-dcn201-enable-dsc.patch
```

`0011` was written for 7.3-rc and lived only in the RC set until 7.2.5 backported
the `drm/gud` change that needs it. It is not optional on either series: without
it the build dies at link time, in a driver this hardware does not even use —

```text
ld.lld: error: call to __read_overflow marked "dontcall-error": detected
read beyond size of object (1st parameter)
```

— which is what happened to `linux-cachyos-bc250` the day 7.2.5 landed. Both the
failure and the fix were reproduced against 7.2.5 with CachyOS's own config
before this was moved across, because the trap only appears at `-O3` with
ThinLTO; a `defconfig` build of the same tree passes.

`0012` and `0013` are the DCN201 display patches described in [4K120 4:4:4 through an HDMI 2.1 PCON](#4k120-444-through-an-hdmi-21-pcon) below.

`patches/linux-cachyos-rc` additionally carries one [HDMI 2.1 patch](#hdmi-21-vrr-and-allm-backport-rc-kernel-only) (`0010`), which applies only to the 7.3 series.

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

## HDMI 2.1 VRR and ALLM backport (RC kernel only)

`linux-cachyos-rc-bc250` carries one extra patch, `0010`, supporting HDMI 2.1
Variable Refresh Rate for sinks that advertise it through the HDMI Forum VSDB
(HF-VSDB) rather than AMD's own FreeSync VSDB. That matters for the
Steam-Machine use case: TVs and AV receivers generally advertise VRR/ALLM the
HDMI-Forum way, not the AMD way.

This was an eight-patch backport when it was written against 7.3-rc1. **CachyOS
has since merged its `7.3/hdmi` branch into `7.3/base`, so seven of the eight
arrived upstream in `cachyos-7.3-rc2-1` and were removed here** — carrying them
would have meant applying the same changes twice. Verified two ways before
removal: each removed patch reverses cleanly against the new tree, and
`git merge-base --is-ancestor` confirms every one of their commits is now an
ancestor of `cachyos-7.3-rc2-1`.

`0010` (upstream `640fd039dc8b`, "Emit VTEM for HF-VSDB VRR on TMDS links") is
the one that did **not** arrive that way. It came from `drm-next` directly and
was never on CachyOS's `7.3/hdmi` branch, so it still has to be carried here. It
is also the most useful of the set for adapter-based setups. Before it,
`amdgpu_dm_update_freesync_state_on_stream()` only built the VTEM — the Video
Timing Extended Metadata packet, which is how HDMI 2.1 carries VRR timing — for
`SIGNAL_TYPE_HDMI_FRL`. A sink advertising HF-VSDB VRR but no AMD FreeSync
therefore never received a VTEM on a TMDS link, and VRR could not engage at all.
Per HDMI 2.1 a VTEM is valid on both TMDS and FRL; only the compressed CVTEM is
FRL-only. It is reviewed by Harry Wentland and carries a `Tested-by:` from Valve.

It is queued for **Linux 7.4** — it landed in `drm-next` on 2026-09-02, one day
after 7.3-rc1 was tagged, so it missed the 7.3 merge window by a day and can be
dropped once 7.4 arrives.

Caveat: the BC-250 is DisplayPort-only, so `0010` applies only through a
**passive** DP++ adapter, where the GPU drives HDMI TMDS directly — exactly the
case the VTEM fix targets. Through an **active** DP→HDMI converter the GPU still
speaks DisplayPort and this code never runs.

That is no longer the end of the story for active adapters, though. `0012` and
`0013` below make the driver negotiate FRL with an HDMI 2.1 protocol converter
and compress the stream with DSC, which is a different and much higher-bandwidth
path than anything `0010` touches.

## 4K120 4:4:4 through an HDMI 2.1 PCON

Two patches, `0012` and `0013`, both against
`drivers/gpu/drm/amd/display/dc/resource/dcn201/dcn201_resource.c`. Together they
make 3840x2160@120Hz at full 4:4:4 chroma reachable on a BC-250 through a
DisplayPort 1.4 → HDMI 2.1 FRL protocol converter.

Both are the work of **TeleBooth**, who published them at
<https://gist.github.com/TeleBooth/d88ef745895d444a401d0e621de9818e> along with
the debugfs capture proving DSC engaged on real hardware — a Cable Matters 102101
PCON into an LG CX — and several other BC-250 owners have reported them working
since. The patch files themselves are signed "Anonymous". They are not upstream,
and they are carried here unchanged apart from one stray blank line and a commit
message.

### Why it needs both

4K120 at 4:4:4 8bpc needs roughly 28 Gbit/s of payload. DP 1.4 HBR3 x4 carries
25.92 Gbit/s raw, about 20.7 Gbit/s after 8b/10b, so the mode does not fit
uncompressed — which is why the BC-250 has only ever offered 4K120 at 4:2:0, or
4K60 at 4:4:4. DSC compresses roughly 1.7:1 (the working capture runs at
224/16 = 14 bpp) and the mode fits.

`0012` sets `dc->caps.dp_hdmi21_pcon_support = true`. DCN201 is the only
DCN2-class resource pool in the tree that leaves it false; without it the link
layer never attempts FRL negotiation with the converter at all, and the adapter
is driven as plain HDMI 2.0 TMDS.

`0013` enables the DSC hardware. Cyan Skillfish carries two DSC engines on-die,
but the DCN201 pool ships with `num_dsc = 0`, creates no DSC objects and leaves
`.add_dsc_to_stream_resource` NULL, so DC can never select DSC. The patch does
four things, and all four are required:

- `num_dsc = 2` in the resource caps;
- create the two DSC objects with `dcn20_dsc_create()`, and destroy them in
  `dcn201_resource_destruct()`;
- wire `.add_dsc_to_stream_resource = dcn20_add_dsc_to_stream_resource`;
- propagate `num_dsc` into `dcn201_ip` before `dml_init_instance()`.

The last one is the non-obvious half. The Display Mode Library validates modes
against its own IP description, so without it DML reads `NumberOfDSC = 0` and
rejects every DSC-requiring mode with `Not enough DSC Units` while the hardware
objects sit there unused.

### Why reusing DCN200's DSC code is safe

`dcn20_dsc_create()` hands the block dcn20's own static register table, which is
built from Navi10's offsets rather than Cyan Skillfish's. That would be a bug if
the two disagreed. They do not:

```text
navi10   DCN_BASE__INST0_SEG0..5 = 0x12, 0xC0, 0x34C0, 0x9000, 0, 0
cyanskf  DMU_BASE__INST0_SEG0..5 = 0x12, 0xC0, 0x34C0, 0x9000, 0, 0
```

`mmDSC_TOP0_DSC_TOP_CONTROL` is `0x3000` with `BASE_IDX = 2` in the DCN 2.0.0
headers, so both resolve to the same absolute address. The public DCN 2.0.1
headers contain no DSC register definitions at all — 600 in 2.0.0 against 0 in
2.0.1 — which is why the driver described the hardware as having none.

### Known limitation: DSC power gating

DCN201 leaves `.dsc_pg_control`, `.enable_stream_gating` and
`.disable_stream_gating` NULL, so the DSC power islands are never explicitly
ungated. Every call site in the tree NULL-checks before dereferencing, so nothing
crashes — this was checked rather than assumed — and DCN201's own `init_hw` does
not touch DSC at all. It works because the islands come up powered on this part.
Wiring `dcn20_dsc_pg_control()` in would not change that either: it returns early
when `DOMAIN16_PG_CONFIG` is absent from the register list, and DCN201 has no
DSC power domains defined. If a future kernel starts gating them, the failure
mode is a dark screen rather than an oops.

### What you need for it to do anything

- An **active** DP 1.4 → HDMI 2.1 FRL protocol converter. A passive DP++ adapter
  cannot do FRL and is unaffected by these patches.
- A sink that reports DSC and FEC support — any HDMI 2.1 TV, in practice.
- Nothing to configure. There is no module parameter: the capability is simply
  present, and DC uses DSC when a mode needs it.

To confirm it engaged, with debugfs mounted:

```bash
sudo grep -H . /sys/kernel/debug/dri/*/DP-1/dsc_clock_en \
                /sys/kernel/debug/dri/*/DP-1/dsc_bits_per_pixel
```

`dsc_clock_en: 1` and a `dsc_bits_per_pixel` of `224` (14 bpp) is the working
state. If DSC is not engaged the mode simply falls back to what fits — 4K120
4:2:0 or 4K60 4:4:4 — rather than failing visibly.


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

The 8-core layout matches the SMU metrics patch in [rw-r-r-0644/bc250-smu-unlock](https://github.com/rw-r-r-0644/bc250-smu-unlock), which is carried by the current community BIOS ([prebuilt firmware here](https://github.com/Forbidden-Darkness/AMD-BC-250-UEFI-v2.2-Firmware-Menu-Script/releases); see [step 5](../README.md#5-running-8-cpu-cores-check-which-bios-you-have) of the quick start). That firmware widens every per-core array to eight entries and keeps its own slot for each remaining field, so **all eight cores report clock, power, temperature and C0 residency**, with no gaps. The struct offsets in the kernel patch are taken directly from that firmware patch's store instructions rather than guessed, and the total export length is asserted at compile time against the 0x11c bytes the firmware actually DMAs.

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

## Patched stable CachyOS Mesa

The workflow resolves a single exact commit from `CachyOS/CachyOS-PKGBUILDS` and downloads the current stable Mesa packaging from that revision.  
The upstream Mesa version and epoch remain unchanged; the GitHub Actions run number is appended to `pkgrel`.

All nine BC-250 Mesa patches are applied at build time, in order:

```text
patches/mesa/0001-gfx1013-compute-queue-fix.patch
patches/mesa/0002-gfx1013-mesh-task-shaders.patch
patches/mesa/0003-gfx1013-taskmesh-queries.patch
patches/mesa/0004-radv-gfx103.patch
patches/mesa/0005-bc250-fsr4-v3.patch
patches/mesa/0006-bc250-fsr4-combined-unroll.patch
patches/mesa/0007-bc250-fsr4-imageprep-texture.patch
patches/mesa/0008-bc250-fsr4-resolution-variants.patch
patches/mesa/0009-bc250-fsr4-production-defaults.patch
```

`0001` is the normal BC-250 path and remains active at all times. It exposes the dedicated ACE compute queue and applies the GFX1013 async-compute workaround required by the matching kernel fixes.  
`0002` and `0003` contain the experimental mesh/task-shader and mesh-query plumbing. For GFX1013 their user-visible feature path remains disabled unless `0004` sees `RADV_GFX103=1` at runtime.  
`0005` is always active regardless of environment variables. GFX1013 has no working packed signed dot product, so `sdot_4x8_iadd` (used by `[iu]dp4a`) falls back to software. The patch makes that fallback much cheaper in two ways: a dense-reduction prepass that expands the largest FSR4 reduction kernels into signed 24-bit multiply chains, and a deferred lowering round that holds the remaining packed `SDot` operations through one full NIR optimization pass before restoring the real capability set and lowering them. Keeping the `SDot` intact lets Mesa's own `iadd(sdot(a, b, 0), c)` fold absorb FSR4's accumulator wrapper, which is what shortens the live ranges that were spilling. A 64-shader FSR4 capture found register pressure and occupancy, not static instruction count, are what actually govern runtime: the worst shader in the corpus dropped from 1314 VGPR spills at 4 waves/SIMD to 0 spills at 6 waves/SIMD, despite a higher naive instruction-cost estimate. This never advertises hardware dot-product support and never emits the broken `v_dot4_i32_i8`. Based on EXP-042B (V3) from BC-250 FSR4 testing (David Moraza Sanchez, [dmorazasanchez/bc250-fsr4, `v3` branch](https://github.com/dmorazasanchez/bc250-fsr4/tree/v3)), verified with FSR 4.1.1 in Cyberpunk 2077 at 63 FPS (up from 58 FPS pre-V3), superseding the earlier EXP-028 selective-reassociation patch.

The patch is carried as upstream wrote it, apart from two hunks dropped while rebasing onto this tree: the GFX1013 compute-queue change and the `RADV_GFX103` override, which duplicate `0001` and `0004` byte-for-byte and would otherwise fail to apply twice. The patch header records that.

One part of it is easy to misread. `0005` raises the LDS spill-slot budget for GFX1013 compute shaders that are already spilling heavily (128–255 spill slots). That deliberately costs occupancy, because in ACO every spill slot which does not fit in LDS goes to scratch instead, and scratch on this APU is backed by shared system memory. Keeping that traffic on-die is worth more here than the lost waves: removing this override measured roughly 12 ms versus 8 ms of OptiScaler frame time on real BC-250 hardware. It is not a mistake, and it should not be "simplified" away.

`0006` and `0007` come from the downstream BC-250 FSR4 research kit dated 2026-09-06 (by "fish"), rebased onto this tree. That kit's own base patch is a squash of work this repository already carries plus its newer optimization; only the part we did not already have is kept here, so `0001`-`0005` are not duplicated. The kit ships its own measurement harness, evidence and prebuilt drivers, and its numbers below are the kit's, not ours.

`0006` is the "combined-unroll" selection and is **active by default**. It adds NIR-level pattern matching and rematerialization over FSR4's dot and convolution loops — grouped dots, loop and cooperative rematerialization, and pointwise column streaming. Every rewrite is gated on exact shader identity: the `bc250_*_expected[]` tables verify the incoming shader's constants before any `bc250_*_prepacked[]` replacement is used, so a shader that does not match is passed through untouched. It also carries two supporting changes it depends on — correct NIR metadata invalidation in `ac_nir_fixup_smem_loads_null_prt()`, and separation of the FSR4 pipeline cache key so cached shaders cannot be served across `BC250_FSR4_DISABLE` settings. The kit measures 8.015 ms to 5.843 ms per FSR4.1.1 INT8 upscale (1506x848 to 2560x1440 Balanced, 40 CU at 1850 MHz): 2.172 ms, 27.1%, against a within-window standard deviation of about 0.01 ms.

`0007` adds two candidates that are **off unless their environment variable is set**. `BC250_FSR4_IMAGEPREP=1` swaps FSR4's image-preparation shader for a rewritten SPIR-V module that interleaves the sixteen feature channels across quad phases; the arithmetic, addresses and packing are unchanged, only channel ownership moves. Selection is a whole-module `memcmp`, so any other shader passes through untouched, and the cooperative region is additionally guarded by even output dimensions. `BC250_FSR4_TEXTURE=1` groups eight output columns instead of four in the final texture shader's pointwise streaming schedule, for one shader identity only.

Treat `0007`'s numbers with more caution than `0006`'s. The kit measures imageprep alone at 0.062 ms (1.07%), texture alone at 0.057 ms (0.97%) and both together at 0.069 ms (1.19%) — they overlap rather than sum. Each arm is two launches, and the six control runs across those campaigns span 0.061 ms, which is the size of the effect being claimed. The kit's own stated next step is to replicate this with more launches on a second board. That is why these are opt-in and `0006` is not.

Both are pinned to FSR4.1.1 INT8 by exact shader identity. A different FSR4 build, or a resolution outside the matched bucket, silently produces no uplift and no warning — the same mechanism that made the upstream author's 1080p results flat until they found FSR4 ships separate shaders per resolution bucket.

`0008` is that bucket problem addressed, and is **opt-in** via `BC250_FSR4_RESOLUTION_VARIANTS=1`. It adds 24 further shader identities covering the 1080p and 4K+ buckets, each tagged with flag bit `0x40000000` so they are ignored entirely unless the switch is set.

It also carries a correctness fix rather than an optimization. The pinned INT8 8K shaders encode masked DWORD stores at byte `0x08000000`, an address inside their own 332 MB scratch allocation, where a store can overwrite a live input and race a neighbouring invocation at clipped edges. For eight exactly identified bytecodes — matched by size and FNV-1a hash, and additionally verified to hold an `OpConstant` of that value at the expected word before anything is written — the constant is rewritten so the store lands beyond any scratch buffer this provider supports. That guard can be enabled on its own with `BC250_FSR4_RESOLUTION_GUARD=1`.

`0009` flips every FSR4 candidate from opt-in to on by default — `BC250_FSR4_IMAGEPREP`, `BC250_FSR4_TEXTURE`, `BC250_FSR4_RESOLUTION_VARIANTS` and `BC250_FSR4_RESOLUTION_GUARD` all default on, with the pipeline cache key moved to `v3` so pipelines cached by an older driver are not reused. Each remains individually overridable. `BC250_FSR4_DISABLE=1` disables the profile-specific rewrites and image-preparation replacement; the generic GFX1013 lowering and independent masked-store correctness guard remain active. It does not reproduce a V3 or stock-Mesa comparison. The original kit's image-preparation and texture measurements were about 1% each at n=2 per arm. Later [v4 qualification](https://github.com/daniel-h-0/bc250-fsr4-fork/blob/v4.0.0-rc6/docs/qualification.md) and [matched game measurements](https://github.com/daniel-h-0/bc250-fsr4-fork/blob/v4.0.0-rc6/docs/performance.md) record the combined implementation's tested scope; those results do not qualify a newly built package binary.

The production patch directories are the ordered build series. The stable,
lib32 and Mesa-Git preparation scripts stage every patch from their respective
directory. Before promotion, `scripts/check-fsr4-driver.py` examines the actual
packaged RADV ELF for the compiled v4 path and verifies its architecture. This
prevents publishing only V3 while uploading unused v4 patches beside it; it is
a build-coverage check, not a replacement for GPU correctness or gameplay tests.

Upstream notes the 4K+ bucket previously failed to show an uplift and is curious whether the multi-bucket logic changes that. That is unverified here, as are `0008`'s performance effects generally.

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
It receives the same nine-patch production series and runtime gating as stable 64-bit Mesa. Source inclusion and a successful build do not by themselves extend the upstream v4 binary qualification to 32-bit workloads.

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

The Git variant carries a separately rebased copy of the same nine-patch series:

```text
patches/mesa-git/0001-gfx1013-compute-queue-fix.patch
patches/mesa-git/0002-gfx1013-mesh-task-shaders.patch
patches/mesa-git/0003-gfx1013-taskmesh-queries.patch
patches/mesa-git/0004-radv-gfx103.patch
patches/mesa-git/0005-bc250-fsr4-v3.patch
patches/mesa-git/0006-bc250-fsr4-combined-unroll.patch
patches/mesa-git/0007-bc250-fsr4-imageprep-texture.patch
patches/mesa-git/0008-bc250-fsr4-resolution-variants.patch
patches/mesa-git/0009-bc250-fsr4-production-defaults.patch
```

`0001` and `0005` remain active regardless of environment variables.  
The experimental GFX1013 mesh/task path from `0002`/`0003` is opt-in through `RADV_GFX103=1`; `0004` provides that runtime override and defaults to disabled. The same limitations as stable Mesa apply: mesh shaders are the currently tested use case, while task shaders are still not working correctly.

**The mesa-git series carries a workaround Mesa main has deleted.** GFX1013 firmware 144 hangs on `DISPATCH_TASKMESH_INDIRECT_MULTI_ACE` with a zero indirect count. RADV had a driver-side workaround for that bug, which `0002` extends for GFX1013's additional zero-dimensional ACE hang. Mesa main removed it in [`5d95a8f141d`](https://gitlab.freedesktop.org/mesa/mesa/-/commit/5d95a8f141d) and now refuses task/mesh outright on affected firmware, on the grounds that nobody should still be running four-year-old firmware — but on the BC-250 that firmware is what there is, and the path works well enough that Final Fantasy VII Rebirth runs on it. So `0002` restores the deleted code verbatim from `5d95a8f141d^` and applies the GFX1013 refinement on top, and `radv_task_enabled()` judges GFX1013 on its own capability bit instead of on `has_taskmesh_indirect0_bug`, which this path sets deliberately to select the workaround. Every other device keeps upstream's newer, stricter behaviour.

That is a maintenance cost taken on knowingly: it is roughly 58 lines of upstream code that no longer exists upstream, so it has to be re-checked whenever the surrounding RADV code moves. The stable `patches/mesa` series still carries the original form because the CachyOS Mesa commit it patches predates the removal.

There is deliberately no separate `series` file. The build script explicitly applies the five numbered patches in order through CachyOS' `mesa-userpatches` mechanism.

To switch explicitly to Git Mesa:

```bash
sudo pacman -S bc250-cachyos/mesa-git bc250-cachyos/lib32-mesa-git
```

