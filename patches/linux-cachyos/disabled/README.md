# Disabled patches

Patches in this directory are **not applied**. The build globs `*.patch` at the
top level of a patch set only (`find -maxdepth 1` in `scripts/prepare-pkgbuild.sh`,
and a plain `*.patch` glob in `scripts/build-package.sh`), so nothing here reaches
a kernel or a release asset.

They are kept in-tree because the analysis behind them is sound and they will be
needed again — not because they are broken.

## Why these five are disabled

All five work around display faults that occur while an HDMI FRL link is being
brought up. Those faults only happen with DSC enabled, and DSC is now **off by
default** (`amdgpu.bc250_hdmi21`, opt-in with `=1`), so a default install cannot
hit them. Shipping workarounds for a path nobody is on adds risk for no benefit.

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

A second, independent failure mode is also still open: after a long stream-off,
the PCON drops its HDMI side and DC never re-detects the link, so the bring-up
reports success while the sink stays dark. Nothing here addresses that.

See `docs/PATCHES.md` for the full write-up, including which earlier conclusions
proved overstated.

## Re-enabling

Move the files back up one directory and renumber them to follow the last active
patch. Check `docs/PATCHES.md` (the fenced patch lists and the "ten patches"
counts) and `tests/test_fsr4_packaging.py::KernelPatchSetTests` — both assert the
shipped set, and both will fail until updated.
