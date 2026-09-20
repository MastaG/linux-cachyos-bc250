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

The two sets carry the same BC-250 patches with the same content — but not
always at the same file number, and not always the same *count*. Each set
regenerates its shared patches against its own kernel base, and each also
carries a small number of series-specific patches the other does not need (see
[patches that exist in one set only](#patches-that-exist-in-one-set-only)
below), which shifts everything after them in whichever set has more of them.
Two tests keep this from drifting apart silently: `KernelPatchSetTests`
compares the two directories by patch *content name* (ignoring the `NNNN-`
number) and asserts the shared ones are byte-identical in substance — the
files touched and the lines changed — and that any patch existing in only one
set is on an explicit, reasoned allow-list. A patch added to one set and
forgotten in the other fails before CI ever builds it.

### Kernel patch set

The stable and BORE kernels carry these twelve BC-250 patches, twelve patches in `patches/linux-cachyos` — used by `linux-cachyos-bc250` and `linux-cachyos-bore-bc250` (7.2). The RC kernel carries the same twelve patches plus its own two series-specific carries, fourteen in total:

```text
0001-bc250-8core-telemetry-gpu-activity.patch
0002-nct6687d-hwmon.patch
0003-gfx1013-pasid-tlb-invalidation.patch
0004-gfx1013-compute-gfxoff-guard.patch
0005-bc250-kfd-flush-tlb-by-runlist.patch
0006-amdgpu-ttm-null-page-guard.patch
0007-cyan-skillfish-sclk-range.patch
0008-bc250-40cu-unlock.patch
0009-dcn201-hdmi21-pcon.patch
0010-dcn201-enable-dsc.patch
0011-cs-relink-after-long-blank.patch
0012-ch7218-pcon-quirk.patch
```

`patches/linux-cachyos-rc` carries the same twelve patches (content-identical, renumbered around its own series-specific carries) plus the two RC-only entries below:

```text
0001-bc250-8core-telemetry-gpu-activity.patch
0002-nct6687d-hwmon.patch
0003-gfx1013-pasid-tlb-invalidation.patch
0004-gfx1013-compute-gfxoff-guard.patch
0005-bc250-kfd-flush-tlb-by-runlist.patch
0006-amdgpu-ttm-null-page-guard.patch
0007-cyan-skillfish-sclk-range.patch
0008-bc250-40cu-unlock.patch
0009-gud-bound-tv-mode-count.patch
0010-dcn201-hdmi21-pcon.patch
0011-dcn201-enable-dsc.patch
0012-cs-relink-after-long-blank.patch
0013-ch7218-pcon-quirk.patch
0014-ch7218-vrr-allowlist.patch
```

`dcn201-hdmi21-pcon.patch` and `dcn201-enable-dsc.patch` are the DCN201 display patches described in [4K120 4:4:4 through an HDMI 2.1 PCON](#4k120-444-through-an-hdmi-21-pcon) below. **On by default**; `amdgpu.bc250_hdmi21=0` gives an unpatched kernel back.

The display going dark on a mode change is a **known, unfixed** issue — see [Losing the picture on a mode change](#solved-black-screen-from-kernel-takeover-until-a-hotplug) below. A fix was shipped briefly and withdrawn; the patch is in `disabled/`.

#### Patches that must be regenerated together

`cs-relink-after-long-blank.patch` and `ch7218-pcon-quirk.patch` both touch
`amdgpu_dm.c`, so **changing the relink patch shifts the quirk's hunk** and the
quirk starts applying with an offset. It still applies — `patch` absorbs it —
but an offset is the drift that eventually becomes a failed apply after an
upstream change, so regenerate both whenever either changes.

That is cheap and needs no container round trip: applying the new relink patch
to the saved pre-relink `amdgpu_dm.c` reproduces exactly the tree the quirk
sees, so the quirk can be regenerated against it locally. A full build then
confirms the result, and **our patches applying silently is the pass condition**
— any `Hunk #N succeeded ... (offset ...)` line naming one of them means they
have drifted apart again.

`ch7218-vrr-allowlist.patch` (RC only) touches `amdgpu_dm_helpers.c` and
`ddc_service_types.h`, which no other patch in either set touches, so it
cannot drift against the others.

Known pre-existing noise that is *not* a regression: `cyan-skillfish-sclk-range`
applies with `offset 1` on stable, `gud-bound-tv-mode-count` with `fuzz 1` on
RC, and upstream's own `dkms-clang.patch` with `offset -5` on both.

#### Disabled patches

`patches/linux-cachyos/disabled/` and `patches/linux-cachyos-rc/disabled/` hold five `cs-*` patches that are **not applied**. The build only globs `*.patch` at the top level of a patch set, so a patch in `disabled/` ships to nobody; they are kept in-tree because the analysis behind them is sound and they will be needed again.

```text
cs-defer-od-during-frl-link-training.patch
cs-defer-od-during-pcon-frl-training.patch
cs-defer-od-during-dp-link-training.patch
cs-release-gfx-override-during-link-bringup.patch
cs-map-unforce-gfxfreq.patch
```

**Six** patches now sit here, including `cs-release-gfx-override-at-modeset.patch`, which was shipped and then withdrawn — see the status box in [Losing the picture on a mode change](#solved-black-screen-from-kernel-takeover-until-a-hotplug) below for why. Two of the older five were also shown to be *ineffective*: their release path went through `RequestGfxclk` (0xE), which has no counterpart and does not actually un-force the clock. They are all kept because the analysis behind them is sound and will be needed again.

There is intentionally no `0002-bc250-audio.patch` (by that old name) here. That Cyan Skillfish DP spread-spectrum fix (disabling `ignore_dpref_ss`) was required on the older Linux 7.1 series this repository previously built, but it has been upstream since Linux 7.2, so applying it again would fail to patch cleanly.

#### Patches that exist in one set only

- `gud-bound-tv-mode-count.patch` — RC only, as of this writing. A FORTIFY_SOURCE workaround for a `drm/gud` bug (`da1ea35fea67`) that trips `__read_overflow` at `-O3` with ThinLTO:

  ```text
  ld.lld: error: call to __read_overflow marked "dontcall-error": detected
  read beyond size of object (1st parameter)
  ```

  Upstream **reverted** the commit that causes this on the branch the stable/BORE kernels track, so the vulnerable code is gone there and the workaround was dropped from `patches/linux-cachyos` — confirmed by reading the reverted-to state directly, not by assuming a version bump fixed it. The 7.3-rc branch still carries the vulnerable code verbatim, confirmed the same way and by a real `-O3`/ThinLTO build that reproduces the failure without this patch and passes with it, so it stays in `patches/linux-cachyos-rc` until 7.3 either reverts it too or lands its own fix. **Do not drop this from the RC set on a version bump alone** — verify with `git apply --check -R gud-bound-tv-mode-count.patch` against the new tree (should fail cleanly if the patch is still needed) and, ideally, a real build.

- `ch7218-vrr-allowlist.patch` — RC only. One line: the Chrontel CH7218 (DPCD branch OUI `2B:02:F0`) added to `dm_freesync_pcon_whitelist`, plus its `DP_BRANCH_DEVICE_ID_2B02F0` define. CachyOS's 7.2 kernel already has this through its `7.2/hdmi` branch, which is why VRR through a CH7218 works on `linux-cachyos-bc250`; its `7.3/hdmi` branch was rebuilt on a different VRR series (HF-VSDB / ALLM / passive VRR, Aug 2026) and dropped the entry, so on 7.3-rc the same adapter fails the allowlist and DC refuses to pass FreeSync through — VRR silently absent on `linux-cachyos-rc-bc250`, identical hardware. Unconditional on purpose: a static table cannot be gated, and the entry only states that this converter may carry FreeSync-over-HDMI, which the chip does. Unrelated to the opt-in `ch7218-pcon-quirk.patch`, which is about capability *misreporting*. **Drop it when the RC source carries the ID itself** — the duplicate define then fails the build, which is the intended signal.

This patch set contains:

> The telemetry/activity and tunable activity/metrics cache logic is consolidated in `bc250-8core-telemetry-gpu-activity.patch`.  
> Both cache windows default to 25 ms and can still be changed at runtime or disabled with `0`.

- automatic 6-core / 8-core Cyan Skillfish SMU metrics layout detection — **8-core boards must run the patched SMU firmware; see the warning at the top of this document**;
- GPU activity reporting through GPU Metrics and `GPU_LOAD` derived from the GFX ring's emitted-fence count (Cyan Skillfish's `GRBM_STATUS` register reads back all-ones regardless of GPU state, which previously pegged `gpu_busy_percent` at 100% even at idle), with a tunable per-device cache (`amdgpu.cs_activity_cache_ms`, default 25 ms, `0` disables it) and a real sleep (not a busy-wait) between ring samples;
- GFX clock read directly from the SMU metrics table (no separate SMU mailbox round trip — see below);
- a tunable cache (`amdgpu.cs_metrics_cache_ms`, default 25 ms, `0` disables it) for the bulk SMU metrics table refresh backing temperature, power, voltage, socclk/vclk/dclk/uclk, GFX clock and throttler-status reads. Upstream's own internal debounce for that transfer is only 1 ms, so every distinct hwmon attribute a monitoring tool polls in one cycle could otherwise trigger its own SMU mailbox round trip;
- corrected `gpu_metrics` CPU-power reporting and overflow-safe 16-bit power export;
- optional full BC-250 APU telemetry through `pp_dpm_socclk` (`amdgpu.cs_full_telemetry=1`), disabled by default so the normal sysfs clock ABI is preserved;
- the v33 merged GFX1013 PASID TLB invalidation fix;
- the GFX1013 compute GFXOFF guard;
- an **opt-in** KFD/HWS runlist rebuild workaround for stale ROCm compute TLB translations (`amdgpu.bc250_flush_by_runlist=1`);
- a defensive AMDGPU TTM NULL-page guard so partially populated BO cleanup cannot dereference a missing page;
- a widened Cyan Skillfish SMU SCLK range (350–2230 MHz, up from the stock 1000–2000 MHz) so userspace SMU-based governors such as [filippor/cyan-skillfish-governor](https://github.com/filippor/cyan-skillfish-governor/tree/smu) can drive the full clock range;
- integration of the external `nct6687` hwmon/PWM driver;
- an **opt-in** 40 CU unlock for the harvested shader engines (`amdgpu.bc250_cc_write_mode=3`), described below;
- HDMI 2.1 PCON negotiation and the two on-die DCN201 DSC engines, **on by default** (`amdgpu.bc250_hdmi21=0` switches them off) — see [4K120 4:4:4 through an HDMI 2.1 PCON](#4k120-444-through-an-hdmi-21-pcon) below;

## HDMI 2.1 VRR and ALLM backport (removed)

The RC kernel used to carry `hdmi21-vtem-on-tmds.patch` (upstream
`640fd039dc8b`, "Emit VTEM for HF-VSDB VRR on TMDS links"), supporting HDMI 2.1
Variable Refresh Rate for sinks that advertise it through the HDMI Forum VSDB
rather than AMD's own FreeSync VSDB.

**It is no longer carried.** It was the last survivor of an eight-patch
backport: CachyOS merged its `7.3/hdmi` branch into `7.3/base`, so seven of the
eight arrived in `cachyos-7.3-rc2-1` and were dropped here at the time, and this
one came from `drm-next` directly. It is queued for **Linux 7.4** — it landed in
`drm-next` on 2026-09-02, one day after 7.3-rc1 was tagged — so it arrives on its
own with the next series.

It also only ever applied through a **passive** DP++ adapter, where the GPU
drives HDMI TMDS directly. The BC-250 is DisplayPort-only, so through an
**active** DP→HDMI converter the GPU speaks DisplayPort and this code never ran.
For active adapters the relevant path is the DCN201 display patches below, which
negotiate FRL and compress the stream with DSC — a different and much
higher-bandwidth path than anything this patch touched.

## 4K120 4:4:4 through an HDMI 2.1 PCON

Two patches, `dcn201-hdmi21-pcon.patch` and `dcn201-enable-dsc.patch` — `0009`
and `0010` in the stable/BORE set, `0011` and `0012` in the RC set (the RC set
carries two extra series-specific patches ahead of these; see [patches that
exist in one set only](#patches-that-exist-in-one-set-only)). Called `0012`
and `0013` below for brevity, meaning "the hdmi21-pcon patch" and "the
enable-dsc patch" respectively, whatever number they actually have in the set
you are looking at. Together they make 3840x2160@120Hz at full 4:4:4
chroma reachable on a BC-250 through a DisplayPort 1.4 → HDMI 2.1 FRL protocol
converter. **Both are on by default**, behind one parameter that exists as an
off switch:

```text
amdgpu.bc250_hdmi21=0
```

Verified on a BC-250 into an LG G5 through a UGREEN 8K adapter — FRL PCON
negotiated, DSC at 12 bpp, 3840x2160@120 RGB with HDR, against 4:2:0 on the same
hardware with the switch off.

These were briefly shipped off-by-default while a display blackout on a mode
change was suspected to be a DSC problem. It was then reproduced on hardware
with `amdgpu.bc250_hdmi21=0`, on an uncompressed 4-lane HBR2 link, with none of
our display workarounds applied — so DSC was not the cause and the default went
back on. The blackout is a separate, still-unfixed issue -- see the status box in [Losing the picture on a mode change](#solved-black-screen-from-kernel-takeover-until-a-hotplug) below.

`0012` defines the parameter in `amdgpu_drv.c` (default 0), `amdgpu_dm.c`
copies it into `dc_init_data.flags`, and it arrives in the resource pool as
`dc->config.bc250_hdmi21` — the same route DC already uses for its other
OS-side switches. With it at `0`, the default, every touched path is identical
to an unpatched kernel: the stock `res_cap_dnc201` (num_dsc = 0) is selected, the DSC
create and destroy loops run zero times, `.add_dsc_to_stream_resource` stays
NULL, `dcn201_ip.num_dsc` is assigned the zero it already held, and
`dp_hdmi21_pcon_support` is never set.

Both are the work of **TeleBooth**, who published them at
<https://gist.github.com/TeleBooth/d88ef745895d444a401d0e621de9818e> along with
the debugfs capture proving DSC engaged on real hardware — a Cable Matters 102101
PCON into an LG CX — and several other BC-250 owners have reported them working
since. The patch files themselves are signed "Anonymous". They are not upstream.
The logic is theirs unchanged; the parameter gating around it is this
repository's.

### Why it needs both

DP 1.4 HBR3 x4 is 8.1 Gbit/s per lane raw, 32.4 Gbit/s over four lanes, and
25.92 Gbit/s after 8b/10b. A TV advertises 4K120 as CTA-861 VIC 118, a 1188 MHz
pixel clock, which costs:

| 4K120 encoding | 8-bit | 10-bit | fits 25.92 Gbit/s? |
|---|---:|---:|---|
| RGB / 4:4:4 | 28.5 | 35.6 | **no, at any depth** |
| 4:2:2 | 19.0 | 23.8 | yes |
| 4:2:0 | 14.3 | 17.8 | yes |

So uncompressed 4K120 over this link is 4:2:2 at best, and full-colour 4K120
needs DSC no matter the bit depth. DSC compresses roughly 1.7:1 (the working
capture runs at 224/16 = 14 bpp) and RGB fits.

That table is the DisplayPort link's own limit, which is what applies when the
adapter presents as a plain DP sink. A DP→HDMI converter that reports itself as
an HDMI downstream port is held to a second, tighter check — its TMDS clock cap
— and that is what `0012` is about.

`0012`, when enabled, sets `dc->caps.dp_hdmi21_pcon_support = true`. DCN201 is the only
DCN2-class resource pool in the tree that leaves it false. What the flag gates
is more specific than "FRL on or off": it decides **which ceiling the driver
validates modes against**. With it set, `link_dp_capability.c` reads the
converter's FRL link bandwidth from DPCD and `link_validation.c` checks each
mode against that. Without it, that field stays zero and every mode is checked
against the converter's *TMDS* pixel-clock limit instead — one DPCD byte times
2.5 MHz, so 637.5 MHz at the absolute most and typically 600.

That ceiling is why an FRL-capable adapter still behaves like HDMI 2.0 on an
unpatched kernel even though its own HDMI side is happily doing FRL. The check
halves the clock for 4:2:0, takes two thirds for 4:2:2 and scales by 10/8 for
10-bit, so against 600 MHz: 4K120 4:2:0 8-bit is 594 MHz and passes, 4K120
4:2:0 10-bit is 742 MHz and is refused, 4K60 4:4:4 10-bit is 742 MHz and is
refused, 4K60 4:2:2 10-bit is 495 MHz and passes. A "4K120 HDR" desktop on the
old kernel is therefore 8-bit on the wire with HDR10 metadata attached — which
looks correct, since the metadata does not depend on wire depth — and 4K60 HDR
is most likely riding 4:2:2 to get its 10 bits. `0012` removes that ceiling for
the adapter; `0013` then supplies the bandwidth to use the headroom at 4:4:4.

`0013`, when enabled, turns on the DSC hardware. Cyan Skillfish carries two DSC
engines on-die, but the DCN201 pool ships with `num_dsc = 0`, creates no DSC
objects and leaves `.add_dsc_to_stream_resource` NULL, so DC can never select
DSC. The patch does four things, and all four are required:

- select a second `resource_caps` with `num_dsc = 2` (the stock one is left
  untouched for the default case);
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
- `amdgpu.bc250_hdmi21=1` on the kernel command line. Without it these patches
  are inert and the board behaves like an unpatched kernel.
- Beyond that, nothing: DC uses DSC when a mode needs it, and only then, so with
  a stream that fits uncompressed DSC stays off even with the switch on.

To confirm it engaged, with debugfs mounted:

```bash
sudo grep -H . /sys/kernel/debug/dri/*/DP-1/dsc_clock_en \
                /sys/kernel/debug/dri/*/DP-1/dsc_bits_per_pixel
```

`dsc_clock_en: 1` with a `dsc_bits_per_pixel` of `192` (12 bpp, the HDMI-spec
value for a CTA 4K120 timing) is the working state seen on the LG G5; the gist's
LG CX capture shows `224` (14 bpp). If DSC is not engaged the mode simply falls
back to what fits — 4K120 4:2:0 or 4K60 4:4:4 — rather than failing visibly.

### Adapters that misreport themselves: the CH7218 quirk

`ch7218-pcon-quirk.patch` (`0012` stable, `0013` RC). **Opt-in, default off**,
behind `amdgpu.bc250_ch7218_quirk=1`.

Some DP→HDMI 2.1 adapters built on a **Chrontel CH7218** ship firmware that
misreports the downstream port. It clears `DP_DOWNSTREAMPORT_PRESENT`, or
reports the detailed downstream port as DP, while the device identity and the
EDID describe a DP→HDMI 2.1 PCON. DC then classifies the adapter
`DISPLAY_DONGLE_NONE`, never runs FRL negotiation, and sends 4K90/4K120 as DP
RGB that the adapter cannot emit over TMDS. The sink stays black.

**4K60 still works**, which is what makes it look like a mode problem rather
than a detection problem.

Found and diagnosed by **@dejan_994**, who traced it to the DPCD misreport and
wrote the original patch; the version here is his work made opt-in and gated.
Reported against a UGREEN DP→HDMI 2.1 adapter, DPCD branch OUI `2B:02:F0`,
branch name `CH7218`. A Cable Matters 102101 on the same board does not need
it — that one already identifies as an HDMI converter.

#### Why it is off by default, and must stay that way

**Healthy CH7218 units report themselves correctly, and nothing in the DPCD
distinguishes an affected unit from a healthy one.** The OUI and the branch
name are identical either way. Applying the quirk to everyone with a CH7218
would override correct information coming from a working adapter — trading one
group's broken 4K120 for another group's working setup.

So the requirement is stronger than "it has a switch": with
`amdgpu.bc250_ch7218_quirk` unset, **nothing the patch adds may take effect**.
Every function that mutates link state begins with the same gate:

```c
static bool bc250_ch7218_quirk_wanted(const struct dc_link *link)
{
	if (!link || !link->dc)
		return false;

	if (!link->dc->config.bc250_ch7218_quirk ||
	    !link->dc->caps.dp_hdmi21_pcon_support)
		return false;

	return link->dpcd_caps.branch_dev_id == BC250_CH7218_BRANCH_DEV_ID &&
	       !memcmp(link->dpcd_caps.branch_dev_name, "CH7218", 6);
}
```

`bc250_hdmi21` is required as well, since the quirk restores HDMI 2.1 PCON
ceilings that mean nothing when PCON support is off.

`test_ch7218_quirk_is_opt_in_and_every_change_is_behind_the_switch` pins all of
this: the default, the gate at the top of each mutating helper, and the absence
of any static-table edit. **A static table entry cannot be gated at runtime**,
which is why the patch adds none.

#### What it does when enabled

1. Forces `DISPLAY_DONGLE_DP_HDMI_CONVERTER` at the two points where the
   firmware's misreport would otherwise produce `DISPLAY_DONGLE_NONE` — no
   downstream port present, and detailed downstream port reported as DP.
2. Restores the documented ceilings: 12 bpc, FRL 48 Gbps, YCbCr 4:2:2 and 4:2:0
   pass-through.
3. Re-asserts those ceilings **after** the DFP capability extension is parsed,
   which would otherwise overwrite them with the firmware's own wrong values.
4. Restores `DP_DSC_SUPPORT` when firmware clears the bit while still returning
   a populated DSC decoder capability block — and only then, so a genuinely
   DSC-less adapter is left alone even with the quirk on.

#### What was deliberately left out

The version this was adapted from also added `DP_BRANCH_DEVICE_ID_2B02F0` to
`ddc_service_types.h` and an entry to the FreeSync PCON allowlist. Neither
ships here:

- **The branch-ID define**: 7.2 **already defines it**, 7.3-rc does not.
  Touching that header would either duplicate a define on one series or make
  the two patch sets diverge. A file-local constant in `link_dp_capability.c`
  avoids both.
- **The FreeSync allowlist entry**: 7.2 already lists the ID in
  `dm_helpers_is_vrr_pcon_allowlist()`; 7.3-rc uses a different structure
  (`dm_freesync_pcon_whitelist[]`) for the same thing. It is also an
  ungateable change to a static table, and the reporter states VRR does not
  work on this adapter regardless (`vrr_capable=0`, no Ignore-MSA / Adaptive
  Sync SDP). No observed benefit, so no entry.

#### Not a kernel problem

If 4K120 is still missing from the mode list after enabling the quirk, check
the sink EDID for CTA **VIC 118**. Some TVs omit it, and injecting EDID is a
userspace matter rather than something that belongs in this kernel.

### Solved: black screen from kernel takeover until a hotplug

> **Status: mode 2 is FIXED. Mode 1 remains withdrawn, and is falsified as the
> operative mechanism anyway.**
>
> **Mode 2 — the converter dropping its HDMI side — is fixed** by
> `cs-relink-after-long-blank.patch` (`0011` stable, `0012` RC). It times how
> long the display stream has been off, and if it returns after more than
> `amdgpu.cs_relink_ms` (default 3000) it runs the `trigger_hotplug` sequence
> a quarter second after the commit, instead of letting DC bring the stream
> back on cached converter state. All of it lives in `amdgpu_dm.c`: no new SMU
> message, no DPCD polling, no DC core change.
>
> Runtime-writable parameters: `cs_relink_ms` (3000; 0 disables),
> `cs_relink_delay_ms` (250), `cs_relink_cooldown_ms` (10000, a hard loop
> breaker), `cs_relink_at_boot` (0, off), `cs_relink_debug` (on).
>
> **`cs_relink_at_boot` covers a gap and is OFF by default.** The timestamp is
> only set when *we* observe a stream go down, so the first bring-up of a boot
> has nothing to measure and is skipped — a machine that boots with the
> converter already dropped gets no help at all. Reported from the field: black
> across several reboots, then clearing on its own, which fits the adapter
> holding state across a warm reboot since it stays powered from the DP side.
>
> It stays off because adversarial review established that the cost is higher
> than first assumed and the benefit remains unproven:
>
> - **It is not a passive probe.** `dc_link_detect()` does
>   `dc_sink_release(link->local_sink); link->local_sink = NULL;` and recreates
>   the sink, so `amdgpu_dm_update_connector_after_detect()` sees a new sink and
>   drives a real modeset plus a hotplug uevent.
> - **It may be redundant.** Every capture shows DC already running a full
>   detect at boot, about three seconds before the first mode:
>
>   ```text
>     t=6.24  retrieve_link_cap
>     t=6.41  link_detect
>     t=9.18  first dpms_on
>   ```
>
>   and the DPCD readiness bits cannot tell a dropped converter from a healthy
>   one (`0x00` either way).
>
> Two defects found in review and fixed before shipping, both worth knowing if
> the feature is ever revisited:
>
> 1. **It must not start the cooldown.** `cs_relink_work_fn` stamps
>    `cs_relink_last_run` on every exit as a loop breaker. A speculative boot
>    detect at ~9 s would then refuse every genuine recovery until ~19 s — and
>    the real 9.8 s boot blank in our own captures lands inside that window. The
>    boot run is one-shot by construction, so it is exempt from stamping.
> 2. **It must expire.** Without a bound, `boot_pending` is spent on whatever
>    commit first carries a converter stream. A board powered up before its TV
>    would hold the shot for hours and then force a redundant modeset 250 ms
>    after the user's picture finally arrives. Bounded to
>    `CS_RELINK_BOOT_WINDOW_MS` (60 s of uptime), which also stops a runtime
>    parameter toggle from arming a live re-detect long after boot.
>
> **Mode 1 — a held GFX override — is still withdrawn**, and is also no longer
> believed to be what breaks bring-up. `cs-release-gfx-override-at-modeset.patch`
> sits unapplied in `patches/<set>/disabled/` because it **broke boot on a
> machine with no governor running at all**: the release is guarded on
> `cyan_skillfish_user_settings.vddc != CYAN_SKILLFISH_VDDC_MAGIC`, but that
> struct is `static`, so `vddc` starts at **0**, and 0 != MAGIC — on a fresh
> boot with nothing forced the guard is true and the release fires anyway,
> sending `UnForceGfxFreq`/`UnforceGfxVid` during every modeset including the
> boot ones. `amdgpu.cs_od_unforce_ms=0` (making it inert) was what recovered
> the machine. If it is ever revived: track whether *we* forced with our own
> flag, never infer it from `user_settings.vddc`, and test with the governor
> **disabled** as well as enabled — that case was never tested before shipping,
> which is how this escaped.
>
> **The mode 1 A/B is now considered confounded.** The `cs_od_unforce_ms`
> 3000 → 0 → 3000 result (pass → fail → pass) was read as proof that a held
> override breaks bring-up. It is not: in a single boot with the governor
> running throughout, a 0.73 s handover passed and a 4.44 s handover failed,
> so a held override is not sufficient. The window lengths differed across
> those A/B runs, and blank length is the variable that actually tracks the
> fault.
>
> **What remains true from the analysis below:**
>
> - `RequestGfxclk` (0xE) has no release counterpart; only the matched
>   `ForceGfxFreq`/`UnForceGfxFreq` (0x39/0x3A) pair genuinely un-forces.
> - It is **not** a DSC problem — reproduced with `amdgpu.bc250_hdmi21=0` on an
>   uncompressed 4-lane HBR2 link.
> - A governor is not the cause but is a strong aggravator: it lengthens
>   session handovers (0.09 s without, 4.44 s with, same switch), and a long
>   handover is what makes the converter drop out.
>
> **There is no clean blank-length threshold.** Below ~3.4 s the fault has never
> occurred; above ~4.4 s it is probabilistic — 6 blanks went dark, 2 came back
> unaided. An earlier revision of this document claimed a clean split with zero
> overlap across 19 transitions; that was overfitting to a sample containing no
> surviving long blank. A long blank is necessary, not sufficient.
>
> **How well the fix is verified:** it arms on every blank over the threshold,
> recovers each time, leaves shorter blanks alone, and has not looped. It is
> *not* verified that each recovery was necessary — with the patch enabled the
> counterfactual cannot be observed. `amdgpu.cs_relink_ms=0` at runtime turns it
> off for an A/B.
>
> **If you still lose the picture:** re-seat the cable, or trigger a software
> hotplug:
> `echo 0 > /sys/kernel/debug/dri/*/DP-1/trigger_hotplug; sleep 3; echo 1 > ...`

Not caused by the DCN201 display patches above, but found while testing them,
and anyone with a DP→HDMI 2.1 adapter (active PCON, e.g. a Chrontel CH7218) or
a native HDMI 2.1 FRL output could hit it. Symptoms varied with how governor
software was configured, from a screen that stayed black indefinitely until a
physical hotplug, to one that eventually synced but late enough to miss the
boot splash and the SteamOS intro video.

**Root cause: a GPU clock/voltage commit landing while the HDMI FRL link is
still training.** `cyan_skillfish_od_edit_dpm_table()`'s commit path
(`cyan_skillfish_ppt.c`) sends `SMU_MSG_RequestGfxclk` and
`SMU_MSG_ForceGfxVid`/`UnforceGfxVid` — forced, immediate hardware clock and
voltage overrides, not soft requests — whenever userspace writes to
`pp_od_clk_voltage`. `cyan-skillfish-governor` does exactly that on its very
first frequency-adjustment cycle, which fires within seconds of boot,
regardless of `gpu-usage.method` or `gpu-set-method` — the OD commit path is
the same either way. If that forced override lands while the CH7218 (or any
HDMI FRL sink) is still mid link-training, the transient disturbance is enough
to desync the link. Confirmed by isolation on real hardware: with the governor
fully masked, a single manual write of `vc 0 <freq> <vddc>` + commit to
`pp_od_clk_voltage`, timed to land during boot, reproduced the same symptom on
its own — no governor code, no polling, no D-Bus involved.

Two extra factors, established the same way:

- The `0001-bc250-8core-telemetry-gpu-activity.patch` telemetry rework earlier
  in this repository's history was never the cause — it only changes metrics
  *decode*, a completely different code path from the OD-commit write path
  above. It does very plausibly make the symptom *worse* by keeping the SMU
  busier around boot (a bigger periodic metrics transfer, before this rework
  removed the extra `GetGfxclkFrequency` mailbox call — see [above](#kernel-patch-set)),
  stretching an otherwise brief, invisible glitch into one long enough to
  desync the link. Kernels without it still take the same forced commit; they
  just usually recover before anyone notices.
- On an **active DP→HDMI PCON** (as opposed to a native HDMI FRL output), the
  PCON trains HDMI FRL to the actual display autonomously — DC only ever reads
  its status via DPCD (`read_and_intersect_post_frl_lt_status()` in
  `link_dp_capability.c`), it never drives or waits on that training itself.
  That means there was no existing "training in progress" signal for the fix
  below to hook for this specific case, unlike a native HDMI FRL output where
  DC's own `hdmi_frl_perform_link_training_with_retries()` /
  `hdmi_frl_poll_start()` bracket the whole operation.

**The fix** is four patches (`0011`–`0014` in the stable/BORE set, `0013`–`0016`
in the RC set — see [Kernel patch set](#kernel-patch-set) above). Three of them
*defer* GPU clock/voltage commits while a link is being brought up; the fourth
*releases* an override that is already held, which is what a runtime mode
change actually needs.

The three `cs-defer-*` patches feed one lock-free interlock: a flag that DC
sets while a link is coming up, which `cyan_skillfish_od_edit_dpm_table()`'s
commit path checks before sending `RequestGfxclk`/`ForceGfxVid`, returning
`-EBUSY` rather than landing the override mid-training. The governor retries
its next cycle roughly 100 ms later, so a deferred commit is not a lost one.
They cover three different windows:

- `cs-defer-od-during-dp-link-training.patch` — **DP link training itself**, by
  bracketing `perform_link_training_with_retries()`. This runs on every mode
  change on a DP-out board.
- `cs-defer-od-during-frl-link-training.patch` — **native HDMI FRL** output:
  the boot-time training call and the async SCDC-triggered retrain that
  `hdmi_frl_status_polling_work` can fire at any point while an FRL link stays
  up. A DP-out board never runs this path; it is here for boards with a native
  HDMI output or a passive adapter.
- `cs-defer-od-during-pcon-frl-training.patch` — the **active DP→HDMI PCON**'s
  own autonomous HDMI-side training, which starts only after the stream
  unblanks and which DC has no signal for. It arms a deadline
  (`amdgpu.cs_pcon_frl_defer_ms`, default 2000 ms; `0` disables it) and the
  commit path defers while the clock is before it. It never blocks the modeset.

### Deferring commits is not sufficient on its own

Boot is fixed by the deferral patches. A **runtime** mode change is not, and
the reason is that the damage is not done by the commit — it is done by the
override being **held**.

Isolated on hardware with `cyan-skillfish-governor-smu` **stopped in both
cases**, so the governor process was not a variable and no commit occurred
during either run. The only difference was whether a `ForceGfxVid` override was
in effect:

| override | GFX state | KDE ↔ gamescope |
| --- | --- | --- |
| held | 1000 MHz / 799 mV | **loses sync** |
| released | SMU defaults (1500 MHz / ~890 mV) | **works** |

Supporting evidence from the same board: governor never started since boot
(nothing ever forced) is 3/3 reliable; governor running (override held) is
0/3. Three consecutive failures had no OD commit within 37 s, 41 s and 94 s of
the modeset — which is what rules out commit timing, and with it any deferral
window at any length. Forcing a *higher* clock does not help either: pinning
the governor's floor to 1500 MHz, the same clock the passing runs sat at,
still failed, and failed at boot.

So `cs-release-gfx-override-during-link-bringup.patch` takes the override off
for the bring-up and puts it back afterwards. `cs_od_force_suspend()` sends the
same `RequestGfxclk` + `UnforceGfxVid` pair that `PP_OD_RESTORE_DEFAULT_TABLE`
followed by `PP_OD_COMMIT_DPM_TABLE` does — that exact sequence, issued by
hand, is what was shown to fix a live failure:

```bash
printf 'r' | sudo tee /sys/class/drm/card1/device/pp_od_clk_voltage
printf 'c' | sudo tee /sys/class/drm/card1/device/pp_od_clk_voltage
```

A delayed work restores the user's settings once the window closes, rather
than a matching "link is up" callback, because no such signal exists for a
PCON — it trains its HDMI side autonomously and DC never learns when it
finished. Every modeset re-arms the timer, so back-to-back modesets hold the
release open instead of restoring between them.
`amdgpu.cs_od_unforce_ms` tunes the window (default 3000 ms; `0` disables the
release and restores the previous behaviour). A commit arriving while the
release is open is refused, but its settings are already recorded — the
restore applies whatever is current when it fires, so such a commit is delayed
rather than lost.

### The clock override could not be released at all

There is a second, more basic reason the deferral and release above were not
enough: **the driver could force the GFX clock but never un-force it.**

`PP_OD_COMMIT_DPM_TABLE` sends `RequestGfxclk`, which is a manual request
whatever value it carries — PMFW keeps honouring it until told otherwise, and
there is no "request nothing". `PP_OD_RESTORE_DEFAULT_TABLE` did not tell it
otherwise either: it simply requested the *default* clock, still a manual
request. Only the voltage was ever genuinely released, via `UnforceGfxVid`.

The missing message was in the firmware header the whole time.
`smu_v11_8_ppsmc.h` declares `PPSMC_MSG_UnForceGfxFreq` (`0x3A`) directly
beside the `ForceGfxVid`/`UnforceGfxVid` pair the driver does map — it was
simply never added to `cyan_skillfish_message_map`. `cyan-skillfish-governor`'s
own SMU backend sends `0x3A` on both startup and shutdown, which is where this
came to light.

`cs-map-unforce-gfxfreq.patch` maps it and makes a release an actual release:
when `PP_OD_RESTORE_DEFAULT_TABLE` has selected `CYAN_SKILLFISH_VDDC_MAGIC`,
the commit sends `UnForceGfxFreq` + `UnforceGfxVid` and skips `RequestGfxclk`
entirely. The forcing path is unchanged.

This is consistent with the one condition that has been reliable across
*every* affected board: a boot where the governor never ran, and
`RequestGfxclk` was therefore never sent, switches modes fine. Once it has
been sent, releasing the voltage alone does not recover — the clock is still
latched, and until this patch nothing short of a reboot could unlatch it.


**The PCON patch used to wait, and that was a mistake worth recording.** Its
first version polled the PCON's own completion bits
(`DP_PCON_HDMI_TX_LINK_STATUS` / `DP_PCON_HDMI_POST_FRL_STATUS`) from the
modeset path for up to 10 s, holding the interlock flag until they reported
ready. They never do. With `amdgpu.cs_od_defer_debug=1` on a BC-250 into an LG
G5 through a UGREEN 8K adapter, every invocation ran the full timeout and
returned `ready=0` — two invocations per boot, 10000 ms each:

```text
[    9.626492] cs_od_defer: DP-HDMI21 PCON FRL wait started
[   20.030431] cs_od_defer: DP-HDMI21 PCON FRL wait finished after 10000ms (ready=0)
[   29.867259] cs_od_defer: DP-HDMI21 PCON FRL wait started
[   40.270402] cs_od_defer: DP-HDMI21 PCON FRL wait finished after 10000ms (ready=0)
```

It cost roughly 20 s of added boot time and the same again on shutdown, both
reported from the field as "boots and shuts down noticeably slower".

**And the poll was not merely useless — it was destroying the training it was
waiting for.** Those 200 AUX DPCD reads (two every 100 ms for 10 s) go out
while the PCON is trying to train its HDMI side, which is why they always read
back `ready=0`: the polling is what stopped it finishing. Established by a
three-way A/B on one board into an LG G5 through a UGREEN 8K adapter, at
3840x2160@120 with VRR and **12-bit** HDR:

| kernel | poll | defer | boot | 12-bit 4K120 |
| --- | --- | --- | --- | --- |
| 1.171 (pre-patch) | no | no | black until cable replug | works |
| 1.177 (10 s poll) | yes | 10 s | clean | **corrupts, sink loses sync** |
| 1.178 (deadline) | no | 2 s | clean | works |

The 1.177 and 1.178 runs negotiated byte-identical link and DSC parameters —
4 lanes at HBR2, DSC at 12.0 bpp, `max_requested_bpc=12`, same slice and chunk
sizes — so nothing about the mode's bandwidth explains the difference. What
separates them is a second
`read_and_intersect_post_frl_lt_status: PCON TX link training has not finished`
appearing at the modeset on 1.177 and not on 1.178. (One such line at boot, from
the capability probe before video flows, is normal and appears on every kernel
including 1.171.)

So the deadline does the one thing the wait was actually there to do, and stops
doing the thing that broke it.

**One more thing worth knowing if you go looking at the code.** The PCON
patch's async-retrain coverage is intentionally narrower than the native-FRL
one: it has not been established whether a plain, same-resolution
compositor-to-desktop handoff re-triggers PCON training the way it can for
native FRL, so if a *runtime* (not boot) desync is ever reported specifically
on an active-PCON setup, that gap is the place to look first.

A module parameter aids debugging without needing a debugger: enable
`amdgpu.cs_od_defer_debug=1` (or `echo 1 | sudo tee /sys/module/amdgpu/parameters/cs_od_defer_debug`
at runtime) and dmesg logs when link training starts/ends and whenever an OD
commit is actually deferred because of it.


## Optional 40 CU unlock

The BC-250 is a salvaged PS5 APU and ships with **24 of its 40 RDNA2 compute units enabled**. The remaining 16 were fused off by firmware policy rather than because they are defective: they still have power, clocks and matching CGTS configuration, and no power gating is active on them.

`bc250-40cu-unlock.patch` (`0008` in both sets) re-enables them by writing two hardware registers during CU enumeration, based on the research and testing in [duggasco/bc250-40cu-unlock](https://github.com/duggasco/bc250-40cu-unlock).

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

If you enable this, cap the clocks. With [cyan-skillfish-governor](https://github.com/filippor/cyan-skillfish-governor/tree/smu), the widened SCLK range from `cyan-skillfish-sclk-range.patch` (`0007` in both sets) makes 1500 MHz / 900 mV reachable as a safe point, and that is the combination the author recommends. Watch temperatures on the first few runs rather than assuming your board behaves like theirs.

### Not every board may be healthy at 40 CUs

Harvest patterns vary. Boards whose disabled CUs are contiguous appear to be policy-harvested, but a scattered pattern may indicate genuinely defective silicon. The upstream project ships tooling to map your own board and to mask individual WGPs through `amdgpu.disable_cu=SE.SH.WGP` if some of the unlocked units turn out to be unstable. Masking works at WGP granularity, so disabling one CU disables its partner.

This patch is carried unmodified apart from one rebase: upstream Linux added an `adev` argument to `amdgpu_gfx_parse_disable_cu()` after the patch was written, so its context needed updating. The register writes themselves are untouched.

## BC-250 APU telemetry

> **8-core boards must run the patched SMU firmware. There is no fallback.**
> The Cyan Skillfish SMU firmware was written for 6 CPU cores; unlocking the
> two extra cores in the BIOS without also patching the SMU firmware to
> understand them leaves the metrics table in a shape this kernel does not
> know how to decode, and telemetry (`gpu_busy_percent`, clocks, power,
> temperatures, `gpu_metrics`, and anything reading them — MangoHud included)
> **will be garbage** on such a board. There used to be an
> `amdgpu.cs_legacy_8core_metrics=1` opt-in that decoded the old, unpatched
> 8-core layout; it has been **removed**, because it only ever produced
> partial, gap-riddled telemetry and made it easy to end up running an
> unsupported firmware/kernel combination without realizing it. If you are
> unlocking 8 cores, patch the SMU firmware first, with either:
>
> - a **prebuilt, easy-to-flash UEFI firmware** that bundles the core unlock
>   with the SMU patch:
>   <https://github.com/Forbidden-Darkness/AMD-BC-250-UEFI-v2.2-Firmware-Menu-Script/releases>
> - or the **userspace unlocker/patcher tool**, if you would rather not flash
>   new firmware:
>   <https://github.com/rw-r-r-0644/bc250-smu-unlock>
>
> Either one gets you a real, fully-populated 8-core metrics table. See
> [step 5 of the quick start](../README.md#5-running-8-cpu-cores) for the
> full instructions and a way to check which firmware you are currently on.

The main telemetry patch includes the additional Cyan Skillfish metrics work while keeping the normal interfaces safe by default.  
GPU activity sampling and the 25 ms activity/metrics caches are unchanged.

### 6-core and 8-core metrics layouts

On a BIOS that unlocks all 8 cores **and** carries the SMU metrics patch, the firmware's metrics table changes shape, and the kernel decodes it differently. The layout is selected automatically from the number of physical cores the CPU reports, so nothing normally needs configuring:

| Cores detected | Layout used |
|---|---|
| 6 | Stock Cyan Skillfish table |
| 8 | 8-core table as produced by the patched SMU firmware |

The 8-core layout matches the SMU metrics patch in [rw-r-r-0644/bc250-smu-unlock](https://github.com/rw-r-r-0644/bc250-smu-unlock), which is carried by the current community BIOS ([prebuilt firmware here](https://github.com/Forbidden-Darkness/AMD-BC-250-UEFI-v2.2-Firmware-Menu-Script/releases); see [step 5](../README.md#5-running-8-cpu-cores) of the quick start). That firmware widens every per-core array to eight entries and keeps its own slot for each remaining field, so **all eight cores report clock, power, temperature and C0 residency**, with no gaps. The struct offsets in the kernel patch are taken directly from that firmware patch's store instructions rather than guessed, and the total export length is asserted at compile time against the 0x11c bytes the firmware actually DMAs.

**An 8-core board without that firmware patch is not supported.** The kernel assumes the patched layout unconditionally once it sees 8 cores; an unpatched 8-core board's table is read as if it were that layout and the result is garbage — not incomplete-but-labeled telemetry, actual garbage. Patch your SMU firmware (see the warning at the top of this section) rather than relying on the kernel to work around it. If you are unsure which firmware you are on, compare per-core temperatures in `amdgpu_top`: on the patched firmware all eight are plausible; on unpatched firmware read as 8 cores, they are nonsense.

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
Its first line names the active layout (`6-core stock` or `8-core`), which is the quickest way to confirm what the kernel decided.

While `cs_full_telemetry=1` is active, `pp_dpm_socclk` is intentionally used as the diagnostic output instead of its normal single-clock listing. Return to the standard behavior at runtime with:

```bash
echo 0 | sudo tee /sys/module/amdgpu/parameters/cs_full_telemetry
```

## GPU telemetry cache tunables

Reading GPU telemetry on Cyan Skillfish means talking to the SMU firmware, and doing that too often is a real stability risk on this board. This is also why some userspace SMU-based governors, such as [cyan-skillfish-governor](https://github.com/filippor/cyan-skillfish-governor/tree/smu), offer a `set-method = "kernel"` option to set clocks through the kernel interface instead of the SMU directly.

Two independent caches bound how often the kernel talks to the SMU for telemetry:

| Parameter | Default | Covers |
|---|---|---|
| `amdgpu.cs_activity_cache_ms` | 25 ms | `gpu_busy_percent` / `GPU_LOAD` sampling |
| `amdgpu.cs_metrics_cache_ms` | 25 ms | The bulk SMU metrics table: temperature, power, voltage, GFX clock, socclk/vclk/dclk/uclk and throttler status |

Both default to 25 ms, matching [MangoHud](https://github.com/flightlessmango/MangoHud)'s default telemetry poll interval, since that is the most common way BC-250 users watch these values live while gaming. Each is independently tunable and `0` disables that cache (every read then hits the SMU directly). There used to be a third, `amdgpu.cs_gfxclk_cache_ms`, for a separate `GetGfxclkFrequency` SMU mailbox message; that message has been removed entirely — GFX clock is now always read straight from the same already-cached bulk metrics table `cs_metrics_cache_ms` covers, so there is nothing left for a third cache to throttle.

Change either at runtime:

```bash
echo 50 | sudo tee /sys/module/amdgpu/parameters/cs_activity_cache_ms
echo 50 | sudo tee /sys/module/amdgpu/parameters/cs_metrics_cache_ms
```

Or set them permanently at boot, the same way as the other `amdgpu.*` parameters documented above:

```text
amdgpu.cs_activity_cache_ms=50 amdgpu.cs_metrics_cache_ms=50
```

`gpu_busy_percent` itself no longer touches the SMU or any hardware register at all: it is derived purely from the GFX ring's existing software fence-tracking, the same activity signal that already backs `fdinfo`'s `drm-engine-gfx`, sampled with a real sleep between reads rather than a busy-wait. `cs_activity_cache_ms` only bounds how often that essentially free sample is retaken, not SMU traffic.

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

