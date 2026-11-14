# HDMI 2.1 adapters, 4K120 and VRR on the BC-250

The BC-250 only has DisplayPort; HDMI 2.1 TVs need an active DP-to-HDMI 2.1
adapter. This page covers getting 4K120 with full colour through one, the fixes
for adapters that lose the picture, VRR, and the optional UGREEN firmware
package. Kernel parameters mentioned here go on the kernel command line, like
the ones in the [README](../README.md).

## 4K120 at 4:4:4 over an HDMI 2.1 adapter

All three kernels carry two DCN201 display patches that let the BC-250 drive
**3840x2160 at 120 Hz with full 4:4:4 chroma** through a DisplayPort 1.4 → HDMI
2.1 FRL adapter. They are **on by default**. There is nothing to enable: boot the
kernel and the mode is offered if your hardware can carry it.

The board could always reach 4K120, but not at full colour. A TV's 4K120 timing
runs a 1188 MHz pixel clock, so RGB/4:4:4 needs 28.5 Gbit/s at 8-bit and 35.6 at
10-bit, and DP 1.4 HBR3 x4 carries 25.92 Gbit/s. Without compression that leaves
4:2:2 or 4:2:0 — and through a DP→HDMI converter it is less than that, see
below. Display Stream Compression fits RGB in at about 1.7:1. Cyan Skillfish has
two DSC engines on-die; the Linux driver simply declared it had none. It also
validated every mode through an HDMI 2.1 adapter against the adapter's *HDMI
2.0* pixel-clock limit, never reading its FRL bandwidth — so even an adapter
that was doing FRL on its own HDMI side was held to 600 MHz on the DisplayPort
side, which is exactly 4K120 at 4:2:0 8-bit and nothing more. The patches fix
both.

**Verified on hardware.** On a BC-250 into an LG G5 through a UGREEN 8K DP→HDMI
2.1 adapter, this repository's kernel negotiates the FRL PCON, engages DSC at
12 bpp and drives 3840x2160@120 **RGB** with HDR — where the same kernel with
the feature off sends the same mode as 4:2:0. The debugfs capture that shows it
is in the commit that turned the feature on by default.

What you need for it to do anything:

- an **active** DP 1.4 → HDMI 2.1 FRL protocol converter (confirmed: Cable
  Matters 102101, UGREEN 8K). A passive DP++ adapter cannot do FRL and is
  unaffected;
- a sink advertising DSC and FEC — any HDMI 2.1 TV in practice.

Nobody on a native DisplayPort monitor or a passive adapter gets anything from
the change, and nothing changes for them either: the code paths are only ever
reached through an HDMI downstream port that reports FRL.

**Switching it off.** The feature sits behind a kernel parameter that defaults
to on. Set it to `0` and every touched code path is identical to an unpatched
kernel — not "disabled", *absent*:

```bash
sudo sed -i 's|^\(KERNEL_CMDLINE\[default\]+=".*\)"$|\1 amdgpu.bc250_hdmi21=0"|' /etc/default/limine
sudo limine-mkinitcpio
```

That appends the parameter inside the quotes of the existing
`KERNEL_CMDLINE[default]+="…"` line, which is the only form
`limine-mkinitcpio` reads — a separate `KERNEL_CMDLINE[default]+=…` line is
silently ignored. To go back:

```bash
sudo sed -i 's| amdgpu.bc250_hdmi21=0||' /etc/default/limine
sudo limine-mkinitcpio
```

If a screen ever stays dark after an update, boot the previous Limine snapshot
entry — CachyOS takes one before every upgrade — or edit the boot entry and add
the parameter for that boot.

To check it engaged:

```bash
sudo grep -H . /sys/kernel/debug/dri/*/DP-1/dsc_clock_en
```

`1` means the DSC engine is running. If it does not engage, nothing breaks — the
mode falls back to what fits, which is the 4K120 4:2:0 or 4K60 4:4:4 you had
before.

**A separate issue, also fixed.** Losing the picture on a mode change is a
different problem, and **not** a DSC one — see
[Losing the picture on a mode change](#losing-the-picture-on-a-mode-change) below.

Credit goes to **TeleBooth**, who did the work of finding that the DSC engines
were there, getting them running on a real BC-250 and
[publishing the patches](https://gist.github.com/TeleBooth/d88ef745895d444a401d0e621de9818e)
with the debugfs evidence to back them up — several other owners have reported
them working since. (The patch files themselves are signed "Anonymous".)

They are **not upstream**, and the DSC power islands are never explicitly
ungated by the DCN201 code — it works because they come up powered on this
part. Every call site was checked to NULL-guard before this was carried, so the
failure mode if a future kernel changes that is a mode that does not appear, not
a crash. Details in
[docs/PATCHES.md](PATCHES.md#4k120-444-through-an-hdmi-21-pcon).


---

## Black screen at 4K120 on a UGREEN / CH7218 adapter (opt-in fix)

**Only turn this on if it describes your symptom.** It is off by default and
should stay off unless you need it.

### Does this apply to you?

All of these have to be true:

- you use a **DP→HDMI 2.1 adapter**, and
- **4K60 works fine**, but
- **4K90 or 4K120 gives a black screen** — no picture at all, not a glitchy one

Then check which chip your adapter uses:

```bash
sudo dmesg | grep -i 'branch\|CH7218'
```

If the branch name is **`CH7218`** (OUI `2B:02:F0`), this is probably your
problem. If your adapter reports something else, this will not help you and you
should leave it alone.

### What is going wrong

Some adapters built on the Chrontel **CH7218** ship firmware that describes
itself incorrectly. It tells the driver it has no HDMI output — or that its
output is DisplayPort — when it is in fact a DP-to-HDMI 2.1 converter.

The driver believes it, so it never sets up the HDMI 2.1 high-bandwidth mode
and instead sends 4K120 as plain DisplayPort video. The adapter physically
cannot put that out over an HDMI cable, so the TV shows nothing. 4K60 is low
enough bandwidth to work either way, which is why only the high modes break.

### Turning it on

Add this to your kernel command line:

```
amdgpu.bc250_ch7218_quirk=1
```

(Keep `amdgpu.bc250_hdmi21=1` as well — it is the default, and the quirk needs
it.) Reboot, and check it took effect:

```bash
cat /sys/module/amdgpu/parameters/bc250_ch7218_quirk   # 1 = the parameter reached the kernel
sudo dmesg | grep 'CH7218 quirk'
```

`forced HDMI 2.1 FRL PCON identity, 48 Gbps` appears **only when the adapter
actually misreported itself** in that detection, and `restored cleared
DSC_SUPPORT` only when it dropped its DSC bit. On an adapter that reports
correctly the quirk stays silent and changes nothing — that is by design, so
no output with the parameter at `1` just means your adapter behaved on that
boot.

### Why it is not on by default

**Plenty of CH7218 adapters work perfectly**, and there is no way for the
driver to tell a good one from a bad one — they identify themselves
identically. Switching this on for everybody would mean ignoring what
correctly-working adapters report about themselves, and would break setups
that are currently fine.

So it is strictly opt-in. With the parameter unset, the kernel behaves exactly
as it would without the patch — not "mostly", but literally: every part of the
workaround checks the switch before doing anything at all.

### VRR with CH7218 firmware 07.00.69 (opt-in)

UGREEN's 07.00.69 firmware no longer tells the driver that it supports
Adaptive-Sync, so KDE and Gamescope offer no VRR although the TV does (07.00.54
does report it). `amdgpu.bc250_ch7218_vrr=1` makes the driver assume the
adapter supports it. **Off by default.** Tested on one setup (`ugreen-69`
straight into an LG OLED G5): VRR works with it. If the picture misbehaves
with VRR on, remove the parameter. It is
independent of `bc250_ch7218_quirk`, needs `amdgpu.bc250_hdmi21=1`, and does
nothing on an adapter that already reports Adaptive-Sync.

```bash
cat /sys/module/amdgpu/parameters/bc250_ch7218_vrr
sudo cat /sys/kernel/debug/dri/*/DP-1/vrr_range     # Min/Max of 0 = none; the TV's range = working
```

### Also: RGB turns into 4:2:2 after the TV was in standby

**This one is already fixed for you — nothing to enable.** It is worth knowing
about because it affects **correctly-reporting** CH7218 adapters too, the ones
that need none of the quirk above.

At boot the adapter advertises its DSC decoder and you get 4K120 RGB 12-bit.
After the TV has been off and comes back, the adapter re-detects and — on the
unit this was found on, every time — no longer advertises DSC, while still
reporting the decoder's revision, slice capabilities and bits-per-pixel. The
driver used to believe the missing bit and quietly fall back to 4K120 **YCbCr
4:2:2 10-bit**: picture still there, fine colour edges and text slightly
fringed, nothing logged.

Since build 1.207 a separate patch puts that bit back whenever the rest of the
block contradicts it, with no parameter — it cannot affect an adapter that
reports its DSC support honestly, so there is nothing to opt into.
`amdgpu.bc250_hdmi21=0` turns it off along with the rest of the HDMI 2.1 path.
Check it is working with:

```bash
sudo cat /sys/kernel/debug/dri/*/DP-1/dsc_clock_en   # 1 = DSC in use, after a standby cycle too
sudo dmesg | grep 'restored cleared DSC_SUPPORT'     # prints when it actually had to step in
```

### If 4K120 is still missing after enabling it

Check whether your TV advertises **VIC 118** in its EDID. Some sets omit it,
and no kernel option can conjure a mode the display never offered. That one is
fixed by injecting a corrected EDID, which is outside what this repository
does.

### VRR through a CH7218

Separate from the quirk: every kernel here carries the two small patches so that
VRR through a CH7218 works on Linux 7.3 the way it did on 7.2 — CachyOS's own
`7.2/hdmi` branch used to provide them and 7.3 does not, so they are ours to
carry now. One is the allowlist entry for the chip; the other makes the
driver take the VRR range from the TV's HDMI Forum VRR block, because the
upstream 7.3 code only reads it from the AMD FreeSync block **through display
firmware the BC-250 does not have** — so on this board that path can never
produce a range, whatever the TV advertises. Nothing to enable. If VRR works on
one of our kernels but not on another with the same adapter, you are on a build
from before the Linux 7.3 bump (stable and BORE) or before build 201 (RC). To
see the decision:

```bash
sudo dmesg | grep 'VRR:'          # needs drm.debug=0x2 on the kernel command line
sudo cat /sys/kernel/debug/dri/*/DP-1/vrr_range
```

Found and diagnosed by **@dejan_994**, who traced the black screen to the
adapter's DPCD misreporting its downstream port and wrote the original patch.
The version here is his work made opt-in and gated.

Technical detail, including exactly what is gated and what was deliberately
left out, is in
[docs/PATCHES.md](PATCHES.md#adapters-that-misreport-themselves-the-ch7218-quirk).

---

## 4:2:2 instead of RGB at 4K120 on a Cable Matters / VMM7100 adapter (experimental)

**Experimental. Off by default. Expect it to either work or give you a black
screen at 4K120 — and be ready to remove it again.**

Some DP→HDMI 2.1 adapters tell the driver they have no DSC decoder even though
the chip has one. The Cable Matters 102101 (Synaptics VMM7100, firmware
7.02.120) does this on the BC-250: it reports no DSC and no FEC at all, so the
driver — which cannot fit 4K120 RGB through a DP 1.4 link uncompressed — builds
the picture as **4K120 YCbCr 4:2:2 10-bit**. Check:

```bash
sudo dmesg | grep -E 'DSC_Basic_Sink_Support|FEC_Sink_Support'   # both "no"
sudo cat /sys/kernel/debug/dri/*/DP-1/dsc_clock_en                # 0
```

`amdgpu.bc250_pcon_force_dsc=1` makes the driver advertise a DSC 1.2a decoder
and FEC on the adapter's behalf and drive it as if it had said so. It only
touches an adapter that reports **nothing** — a CH7218, which reports a decoder
and merely clears one bit, is never affected (that case is the quirk above).
After boot:

```bash
sudo dmesg | grep pcon_force_dsc      # says which adapter it overrode
sudo cat /sys/kernel/debug/dri/*/DP-1/dsc_clock_en    # 1 = it worked
```

If instead 4K120 is black or garbled, the adapter's firmware genuinely cannot
decode DSC: drop the parameter, you are back to 4:2:2. Either outcome is
useful to know — tell us which you got and the adapter's firmware version
(`sudo dmesg | grep pcon_force_dsc` prints it).

---

## Losing the picture on a mode change

**Fixed.** The kernels now recover from this on their own; you should not have to
do anything.

The symptom: the screen goes black when the display switches mode — most often
moving between your desktop session and gamescope, or on the first gamescope
start after boot — and stays black. Re-seating the cable brings it back.

### What was going wrong

The BC-250 reaches your TV through a DisplayPort-to-HDMI 2.1 converter. When the
picture is switched off for more than a few seconds — which is what a slow
session handover looks like — the converter drops its HDMI side and stops
driving the TV.

The driver does not notice. From its point of view nothing was unplugged, so it
brings the picture back using what it **remembers** about the connection rather
than looking again. The DisplayPort side trains, the mode is set, every step
reports success, and the screen stays dark.

Re-seating the cable worked because it forced the driver to look at the
connection again instead of trusting its memory.

### What the kernels do now

`cs-relink-after-long-blank.patch` measures how long the picture has been off. If
it comes back after more than three seconds, the driver re-detects the
connection instead of trusting cached state — the same thing re-seating the
cable does, done automatically a quarter of a second after the mode is set.

Normal switches are untouched. A quick session handover blanks the screen for
about a tenth of a second, and even a slow one measured in the field only
reached 2.1 seconds, so nothing happens. The threshold sits deliberately
between those and the shortest blank ever observed to go dark (4.4 seconds),
because a re-detect is not free — it costs a real mode change, so firing when
it was not needed is worse than not firing.

### Settings

All five can be changed at boot on the kernel command line, or written live under
`/sys/module/amdgpu/parameters/`.

| Parameter | Default | What it does |
| --- | --- | --- |
| `amdgpu.cs_relink_ms` | `3000` | How long the picture must have been off before the connection is re-detected. `0` turns the whole thing off. |
| `amdgpu.cs_relink_delay_ms` | `250` | How long after the mode is set to run the re-detect. |
| `amdgpu.cs_relink_cooldown_ms` | `10000` | Shortest time allowed between two re-detects. Stops any possibility of it retriggering itself in a loop. |
| `amdgpu.cs_relink_at_boot` | `0` | **Off.** Also re-detect once on the first screen of a boot, for the case where the adapter was already stuck before the machine started. Experimental — see below. |
| `amdgpu.cs_relink_debug` | `1` | Log what it does. Off with `0`. |

To turn it off without rebooting:

```bash
echo 0 | sudo tee /sys/module/amdgpu/parameters/cs_relink_ms
```

To see what it has been doing:

```bash
sudo dmesg | grep 'bc250 relink'
```

A normal short switch logs `blank was 110 ms, under the 3000 ms threshold`. A
recovery logs `arming a forced re-detect` followed by `forced re-detect: done`.

### The boot case (experimental, off by default)

The check above measures how long the picture was off. That only works while
the machine is running — if your adapter was **already** stuck before you
switched the machine on, there is no blank to measure and nothing to react to.

That happens: it has been reported surviving several reboots in a row and then
clearing on its own, which fits the adapter holding its state across a warm
reboot (it keeps power from the DisplayPort side, so restarting the machine
does not reset it).

`amdgpu.cs_relink_at_boot=1` re-detects once on the first screen of a boot as
well. **It is off by default and you should leave it off unless you are
chasing exactly that symptom.**

Two reasons it is not on for everyone:

- **We do not know that it helps.** The driver already does a full detection
  during startup, about three seconds before the first picture appears, so this
  may simply be doing the same thing twice. Nothing can tell a stuck adapter
  from a healthy one — it reports itself as healthy either way.
- **It is not free.** Re-detecting releases and recreates the connection state,
  so it drives a real mode change and a hotplug event, not a quiet probe.

If you want to try it, add `amdgpu.cs_relink_at_boot=1` and then read what it
decided:

```bash
sudo dmesg | grep 'bc250 relink'
```

You will see one line for the first screen of the boot, saying either that it
forced a re-detect or that it left the link alone, followed by the result:

```text
  bc250 relink: first bring-up of this boot at 9180 ms, forcing a re-detect (cs_relink_at_boot=1)
  bc250 relink: running the boot re-detect in 250 ms
  bc250 relink: boot re-detect: done
```

With it off — the default — that first line reads `cs_relink_at_boot=0,
leaving the link alone`, so you can always tell which way it went.

Two details worth knowing if you do enable it. The boot attempt only counts
during the **first 60 seconds of uptime**, so a machine switched on before its
TV does not spend it hours later when you finally turn the TV on. And it
deliberately does not start the cooldown timer, so it cannot swallow the first
genuine long blank of the boot — which is the case the main mechanism exists
for.

### If you still lose the picture

Re-seat the DisplayPort cable, or force a hotplug over SSH:

```bash
d=$(ls -d /sys/kernel/debug/dri/*/DP-1 | head -1)
sudo sh -c "echo 0 > $d/trigger_hotplug; sleep 3; echo 1 > $d/trigger_hotplug"
```

If that is happening often, two things make long blanks less likely in the first
place:

- **Run the GPU governor with `temp-read = "sysfs"`** if your build of
  cyan-skillfish-governor supports it. A governor that keeps a DRM connection
  open for temperature readings makes session handovers dramatically slower —
  measured at 0.09 s versus 4.4 s for the same switch on this hardware — and a
  slow handover is what trips the converter.
- **Running without a GPU governor at all** removes the effect entirely.

Neither is required now that the kernel recovers by itself; they just reduce how
often it has to.

It is **not** a DSC problem, despite appearances. It reproduces with
`amdgpu.bc250_hdmi21=0` on an uncompressed 4-lane HBR2 link with no display
patches applied.

Full analysis, including the hardware measurements and the approaches that were
ruled out, is in
[docs/PATCHES.md](PATCHES.md#solved-black-screen-from-kernel-takeover-until-a-hotplug).

## UGREEN DP-to-HDMI 2.1 adapter firmware (optional)

The UGREEN DisplayPort to HDMI 2.1 adapter (DP134 / DP135, a Chrontel CH7218A) has a firmware problem that shows up as a **black picture that never comes back**: a few minutes after the picture starts, the adapter stops resending the HDMI scrambling setup, so anything that resets the TV or receiver's HDMI state without dropping the link for long (an AV receiver input switch, a TV standby and wake) leaves no signal while the DisplayPort side still looks healthy. See the [package README](../packages/bc250-ch7218-fw/README.md) for the analysis.

`bc250-ch7218-fw` ships UGREEN's own Linux updater, UGREEN's `07.00.54` firmware unchanged (`original`, the last version with VRR support), UGREEN's latest `07.00.69` (`ugreen-69`, without VRR support), and two copies with a one-byte watchdog timer fix (`tmds` on 54, `tmds-69` on 69; and an untested `tmds-frl`). Use a `tmds` image if you get link or picture loss after equipment has been turned off, or after the adapter's input was inactive for a while. Nothing in it runs by itself and it is **not** part of `linux-cachyos-bc250-meta`. You flash by hand, from SSH:

```bash
sudo pacman -S bc250-ch7218-fw
sudo bc250-ch7218-flash status                 # finds the adapter and reads its firmware version
sudo bc250-ch7218-flash flash tmds --dry-run   # every check, no write
sudo bc250-ch7218-flash flash tmds             # or: original | tmds-frl | ugreen-69 | tmds-69
```

It only touches an adapter on firmware `07.00.xx` (`07.00.54` or an older build, which it then also brings up to 54, as UGREEN's own update does), checks the image against its checksum first, and asks you to type `flash`. The new firmware runs after the adapter is power-cycled; `flash original` goes back to UGREEN's. Flashing firmware carries a small risk of leaving a device unusable if the write is interrupted, so do not cut power while it runs. This package is not endorsed by UGREEN or Chrontel.
