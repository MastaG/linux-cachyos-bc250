# bc250-vcn-fw

The firmware file `amdgpu/ps5_vcn.bin` for the BC-250's Video Core Next (VCN 2.0)
block. It is parked: see below.

It installs one file, `/usr/lib/firmware/amdgpu/ps5_vcn.bin`, plus AMD's licence
text. Nothing runs and nothing is configured.

## Do you need it

**No.** No shipped kernel uses this file. The kernel patch that did
(`bc250-vcn.patch`, now parked in `patches/linux-cachyos-rc/disabled/`) freezes the
BC-250 on the first register read of the VCN block, so it was taken out of the
RC kernel. The package is kept so that anyone who wants to continue that work
has the firmware to hand.

## Where the file comes from

The BC-250 reports a VCN 2.0.3 block in its IP discovery table, but mainline
Linux never switches it on and linux-firmware has no firmware for it. This
file is the one the **ps5-linux** project ships for the same silicon family
(`ps5-linux/ps5-linux-patches`, pull request #38, "Add VCN for PS5"), together
with the AMD licence file included here. This repository did not produce it and
cannot say how it was obtained.

| | |
| --- | --- |
| file | `ps5_vcn.bin`, 404544 bytes |
| sha256 | `bbd15ab65e76178c2918e8224b6ab4ab1711f1b59d935ee131ab188a9712e596` |
| licence | `LICENSE.amdgpu` (AMD's redistribution licence for amdgpu microcode, binary form only, reproduce the notice) |

The file name keeps `ps5_vcn` so the same file works with either project's
kernel patch, and so it can never collide with a file in linux-firmware.

It is not endorsed by AMD. If a rights holder asks for the file to be removed,
it will be.

## Status

Experimental. The kernel patch and this file have not run on a BC-250 for long;
see the repository README for the current state.
