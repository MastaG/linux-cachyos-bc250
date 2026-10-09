# Disabled patches

Patches in this directory are **not applied**. The build globs `*.patch` at the
top level of a patch set only (`find -maxdepth 1` in `scripts/prepare-pkgbuild.sh`,
and a plain `*.patch` glob in `scripts/build-package.sh`), so nothing here reaches
a kernel or a release asset.

They are kept in-tree because the analysis behind them is sound and they will be
needed again — not because they are broken.

## Why these six are disabled

All six work around display faults around HDMI FRL link bring-up. Those faults
were first suspected to need DSC, but the blackout later reproduced with
`amdgpu.bc250_hdmi21=0` (DSC is on by default; that is the off switch), and the
approach was superseded by the active `cs-relink-after-long-blank.patch`.
`cs-release-gfx-override-at-modeset.patch` was shipped and then withdrawn: it
broke boot with no GPU governor running.

There is also a correctness reason not to ship two of them as-is:

- `cs-release-gfx-override-during-link-bringup.patch` releases a held GPU
  clock/voltage override by requesting the firmware's default clock through
  `RequestGfxclk` (0xE). Later hardware A/B showed that does **not** actually
  un-force anything — 0xE is a manual request with no release counterpart, so the
  clock stays under manual control and the link still dies on a runtime mode
  change. A release only works through the matched `ForceGfxFreq` (0x39) /
  `UnForceGfxFreq` (0x3A) pair, which these patches never use for the force path.
- `cs-map-unforce-gfxfreq.patch` maps 0x3A but leaves the force path on 0xE, so
  the pair is still mismatched.

The boot-time black screen these patches were written for *was* genuinely fixed
by the three `cs-defer-*` patches; that result stands.

A second, independent failure mode -- after a long stream-off the PCON drops its
HDMI side and DC never re-detects the link, so the bring-up reports success
while the sink stays dark -- is fixed by the active
`cs-relink-after-long-blank.patch`.

See `docs/PATCHES.md` for the full write-up, including which earlier conclusions
proved overstated.

## Re-enabling

Move the files back up one directory and renumber them to follow the last active
patch. Check `docs/PATCHES.md` (the fenced patch lists and the patch
counts) and `tests/test_fsr4_packaging.py::KernelPatchSetTests` — both assert the
shipped set, and both will fail until updated.


## bc250-vcn.patch (parked 2026-10-09)

Port of the PS5 VCN 2.0 patch (ps5-linux-patches PR #38) to the BC-250
(device 0x13fe), behind `amdgpu.bc250_vcn=1`. **On the BC-250 it freezes the
machine**: with the VCN firmware loaded directly (the BC-250's PSP refuses
`ps5_vcn.bin`, status 0xFFFF0008) every IP block initialises, and the first
register read of the VCN block (`UVD_POWER_STATUS`) never returns. The IP
discovery bases (0x7800, 0x7E00, 0x02403000) are the same as the PS5's
hard-coded ones, so the addresses are right; the block does not answer, and
nothing in the driver powers it up. Others who tried more drastic hardware
means report it appears to be disabled on purpose. The patch carries
`bc250-vcn:` breadcrumbs that name the last step reached. It is kept, with the
`bc250-vcn-fw` firmware package, for anyone who wants to continue.

Test loop that found this: amdgpu.ko built alone against the CI kernel's
config (clang 23, no MODVERSIONS) in an Arch container, copied to a board and
loaded by hand with netconsole on, `modprobe.blacklist=amdgpu` on the command
line so a freeze comes back to a reachable system after a power cycle.
