# BC-250 CachyOS kernels + Mesa repository

[![Build and publish BC-250 CachyOS kernels and Mesa](https://github.com/MastaG/linux-cachyos-bc250/actions/workflows/build-release.yml/badge.svg)](https://github.com/MastaG/linux-cachyos-bc250/actions/workflows/build-release.yml)

A pacman repository for the **AMD BC-250** on CachyOS: patched kernels, patched
Mesa with working FSR4, ready-made FSR4 Proton builds, and Dolby Digital audio
output. Everything is prebuilt — you add the repository and install packages.

Packages: <https://github.com/MastaG/linux-cachyos-bc250/releases/tag/repo>

> **Running 8 CPU cores?** Your SMU firmware must be patched to match — there
> is no supported fallback for unlocking 8 cores on stock SMU firmware anymore.
> See [step 5](#5-running-8-cpu-cores) before you do anything else with core
> count. Everything below this applies equally either way.

## What you get

| Package | What it is |
|---|---|
| `linux-cachyos-bc250` | Stable BC-250 kernel (`-rc` and `-bore` variants also built), with the `nct6687` fan and temperature driver built in |
| `mesa` / `lib32-mesa` | Patched Mesa: GFX1013 async compute on by default, FSR4 support |
| `mesa-git` / `lib32-mesa-git` | Same patches on Mesa main, optional |
| `proton-cachyos-native-bc250` | CachyOS Proton with FSR4, built for Zen 2 |
| `proton-cachyos-slr-bc250` | The same, on the Steam Linux Runtime: the one for anti-cheat games |
| `protonge-latest-bc250` | GE-Proton with FSR4 ready to go |
| `bc250-dual-audio` | Dolby Digital 5.1 output over DisplayPort |
| `linux-cachyos-bc250-meta` | Installs the recommended set in one go |

---

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

---

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

Or install [`linux-cachyos-bc250-meta`](#linux-cachyos-bc250-meta) instead, which pulls in the stable kernel, its headers, and the other BC-250 extras (currently `bc250-dual-audio` and all three FSR4 Proton packages) together, and picks up any new ones added to it in the future on a normal `pacman -Syu`.

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

### 5. Running 8 CPU cores?

Check what your board reports:

```bash
lscpu | grep '^Core(s) per socket'
```

Skip the rest of this step if that says `6` — everything works out of the box and nothing here applies to you.

> ## ⚠️ If you unlocked 8 cores, your SMU firmware MUST also be patched
>
> **There is no supported fallback for running 8 cores on stock, unpatched SMU
> firmware.** An older kernel patch set used to offer
> `amdgpu.cs_legacy_8core_metrics=1` as a workaround for that combination — it
> has been **removed**. It only ever produced partial, gap-riddled telemetry,
> and kept people running an unsupported firmware/kernel combination without
> realizing it. If your BIOS unlocks 8 cores without also patching the SMU
> firmware, your telemetry (clocks, power, temperatures, `gpu_busy_percent`,
> MangoHud, everything) **will read as garbage**, because the kernel decodes
> the 8-core table assuming the patched layout unconditionally.
>
> Patch your SMU firmware. Two ways to do it, pick one:
>
> - **Flash a prebuilt UEFI firmware** that bundles the core unlock with the
>   SMU patch — the easiest option for most people:
>   <https://github.com/Forbidden-Darkness/AMD-BC-250-UEFI-v2.2-Firmware-Menu-Script/releases>
>   Follow that repository's own instructions — it ships a script that unpacks
>   the firmware to a USB stick and reboots you into the flashing environment.
>   Flashing firmware can brick a board if it is interrupted, so read its
>   README first and do not do it on a machine you cannot afford to lose.
> - **Patch the SMU firmware yourself from a running system**, if you would
>   rather not flash a new BIOS:
>   <https://github.com/rw-r-r-0644/bc250-smu-unlock>

The kernel picks the right decoding automatically once your firmware is patched, so there is nothing to configure:

| Your BIOS | Supported? | What you get |
|---|---|---|
| 6 cores (stock) | Yes | Normal telemetry, nothing to do |
| Unlocks 8 cores **and** patches the SMU | Yes — this is the default once you flash it | Clock, power, temperature and C0 residency for **all 8 cores** |
| Unlocks 8 cores on **stock, unpatched** SMU | **No** | Garbage telemetry — patch your SMU firmware, see above |

To confirm you are actually on the patched layout, look at per-core temperatures in `amdgpu_top`: all eight should be plausible room-temperature-and-up values. If most of them read zero or nonsense, your SMU firmware is not patched — fix that before reporting a telemetry bug.

---

## Mesa behavior, performance and stability

The patched Mesa packages enable the GFX1013 async-compute path by default; no environment variable is required for normal use.  
Games that benefit from async compute can see a significant performance improvement. In current BC-250 community testing, Cyberpunk 2077 has shown gains of roughly 10–15 FPS.

Async compute can also increase GPU load and voltage requirements.  
Some BC-250 systems that were previously stable have shown green-screen or black-screen GPU crashes after enabling the async-compute path. Community reports indicate that some boards need a small GPU-voltage increase to remain stable, with around +25 mV being sufficient in several cases. This is not required on every BC-250: if the GPU is stable, no voltage change is needed.

`RADV_GFX103=1` is separate from async compute and should **not** be enabled globally.  
Use it only per-game for titles that need the experimental GFX10.3 mesh-shader path. It has been tested successfully with Final Fantasy VII Rebirth, which currently does not start on the BC-250 without the override in community testing. Mesh shaders work for this test case, but **task shaders are still not working correctly**. Games that depend on task shaders may render incorrectly, hang or crash when `RADV_GFX103=1` is enabled.

---

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
[docs/PATCHES.md](docs/PATCHES.md#4k120-444-through-an-hdmi-21-pcon).


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

### Also: RGB turns into 4:2:2 after the TV was in standby

This one affects **correctly-reporting** CH7218 adapters too. At boot the
adapter advertises its DSC decoder and you get 4K120 RGB 12-bit. After the TV
has been off and comes back, the adapter re-detects and — on the unit this was
found on, every time — no longer advertises DSC. The driver quietly falls back
to 4K120 **YCbCr 4:2:2 10-bit**: picture still there, fine colour edges and
text slightly fringed. Check:

```bash
sudo cat /sys/kernel/debug/dri/*/DP-1/dsc_clock_en     # 1 = DSC in use, 0 = it is not
```

If it reads `0` after a TV standby cycle but `1` after a fresh boot, enable
the quirk above: its DSC-restore part fixes exactly this, and the rest of it
does nothing on an adapter that reports its port correctly.

### If 4K120 is still missing after enabling it

Check whether your TV advertises **VIC 118** in its EDID. Some sets omit it,
and no kernel option can conjure a mode the display never offered. That one is
fixed by injecting a corrected EDID, which is outside what this repository
does.

### VRR through a CH7218 on the RC kernel

Separate from the quirk: the RC kernel (`linux-cachyos-rc-bc250`) carries two
small patches so that VRR through a CH7218 works on 7.3-rc the way it already
does on 7.2. One is the allowlist entry for the chip; the other makes the
driver take the VRR range from the TV's HDMI Forum VRR block, because the
upstream 7.3 code only reads it from the AMD FreeSync block **through display
firmware the BC-250 does not have** — so on this board that path can never
produce a range, whatever the TV advertises. Nothing to enable. If VRR works on
the stable kernel but not on the RC one with the same adapter, you are on an RC
build from before build 201. To see the decision:

```bash
sudo dmesg | grep 'VRR:'          # needs drm.debug=0x2 on the kernel command line
sudo cat /sys/kernel/debug/dri/*/DP-1/vrr_range
```

Found and diagnosed by **@dejan_994**, who traced the black screen to the
adapter's DPCD misreporting its downstream port and wrote the original patch.
The version here is his work made opt-in and gated.

Technical detail, including exactly what is gated and what was deliberately
left out, is in
[docs/PATCHES.md](docs/PATCHES.md#adapters-that-misreport-themselves-the-ch7218-quirk).

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

All four can be changed at boot on the kernel command line, or written live under
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
[docs/PATCHES.md](docs/PATCHES.md#solved-black-screen-from-kernel-takeover-until-a-hotplug).

## FSR4-capable Proton (opt-in)

Three packages, same idea: a Steam compatibility tool with everything FSR 4.1.1
needs on this hardware already inside it — the AMD FSR4 provider, OptiScaler,
OptiPatcher, [fakenvapi](https://github.com/optiscaler/fakenvapi) and a
known-good OptiScaler configuration.

| package | base | anti-cheat games | notes |
|---|---|---|---|
| `proton-cachyos-native-bc250` | CachyOS's Proton, from source | no | the fastest: no runtime container |
| `proton-cachyos-slr-bc250` | the same Proton, from source | **yes** | Steam Linux Runtime build |
| `protonge-latest-bc250` | GE-Proton, repacked | yes | tracks GE's own releases within hours |

Both CachyOS packages are compiled for this hardware (`-O3 -march=x86-64-v3
-mtune=znver2`) rather than repacked from someone's generic release. They differ
only in where they run: the native one talks to the system directly, which is
quicker, while the SLR one runs inside the Steam Linux Runtime — the environment
games with EasyAntiCheat or BattlEye require, and the one the native build cannot
offer.

```bash
sudo pacman -S proton-cachyos-native-bc250      # or
sudo pacman -S proton-cachyos-slr-bc250         # or
sudo pacman -S protonge-latest-bc250
```

All three can be installed at once — `linux-cachyos-bc250-meta` pulls in all of
them — and all sit alongside the distro's own Proton packages. Restart Steam,
then pick **proton-cachyos-… (native, BC-250 FSR4)**, **proton-cachyos-…
(BC-250 FSR4)** or **GE-Proton 11-6 (BC-250 FSR4)** under a game's Properties →
Compatibility.

**Anti-cheat, and why it needs saying.** These packages inject DLLs into the
prefix, which is exactly what anti-cheat software is built to notice, and
accounts have been banned for less. FSR4 and OptiScaler therefore switch
themselves off when a game is detected as using EasyAntiCheat or BattlEye. That
detection looks for Steam's layered anti-cheat runtimes and for the files both
products leave in a game directory — it is a safety net, not a guarantee. A game
whose anti-cheat arrives on first launch, or that lays its files out unusually,
will not be caught, and VAC leaves nothing to find at all. **If you play a game
with anti-cheat, set `PROTON_FSR4_UPGRADE=0 %command%` yourself rather than
relying on the detection**, or use a Proton without this payload in it.

**That is the whole setup.** FSR4 and OptiScaler are on by default — no launch
options, no DLLs to copy into game folders, no environment variables.

**fakenvapi** is bundled and always active — there is no variable to enable it.
It stands in for `nvapi64.dll` so OptiScaler can reach AntiLag 2, Vulkan
AntiLag+, XeLL or LatencyFlex in games that would otherwise need NVIDIA Reflex.
OptiScaler picks whichever of those the hardware supports; on the BC-250 that
means the Reflex-shaped latency path works without an NVIDIA GPU. Unlike the
pinned OptiScaler build, fakenvapi is **tracked live**: a new upstream release
changes both packages' fingerprints and they rebuild with it.

Both need the `vulkan-radeon` package from this repository: the provider calls
into FSR4 support that lives in our patched RADV, not in stock Mesa. They also
work under Heroic and Lutris, which run them through umu. (Flatpak Steam cannot
see them — its sandbox has its own `/usr`.)

### Launch options

Per game, if you want them:

```text
BC250_FSR4_DEBUG=1 %command%              # FSR4 watermark + OptiScaler log + PROTON_LOG
PROTON_FSR4_UPGRADE=0 %command%           # turn the packaged FSR4 upgrade off
PROTON_USE_OPTISCALER=signed %command%    # AMD's signed bridge instead of the default, see below
BC250_OPTISCALER_EXTRA="A.B=c;D.E=f"      # override individual OptiScaler settings
PROTON_OPTISCALER_NAME=dxgi.dll %command% # load OptiScaler as dxgi instead of winmm
```

`PROTON_OPTISCALER_NAME` is for one specific symptom: FSR4 quietly does nothing
in a game that has a mod loader, an ASI loader, or anything else of its own
installed as `winmm.dll`. OptiScaler is proxied as `winmm` here, so in that game
the game's own file wins and the upscaler never loads. Point it at another
import the game does not use — `dxgi.dll` is the usual one, and is upstream
protonfixes' own default:

```text
PROTON_OPTISCALER_NAME=dxgi.dll %command%
```

Nothing else changes: the payload is the same pinned OptiScaler either way, and
the matching `WINEDLLOVERRIDES` entry follows the name automatically. Confirm it
worked with `BC250_FSR4_DEBUG=1` and look for the watermark.

OptiScaler answers to a fixed set of names — `dxgi.dll`, `winmm.dll`,
`version.dll`, `dbghelp.dll`, `d3d12.dll`, `wininet.dll`, `winhttp.dll` — so pick
one of those, and one the game does not already have a file for. Anything else
just means OptiScaler never loads.

This is unrelated to the `Spoofing.Dxgi` setting, despite the shared word. The
proxy name decides which import the loader resolves to OptiScaler; `Spoofing.Dxgi`
decides whether OptiScaler reports a spoofed GPU to the game once it is running.
This package sets that one to `false`.

`BC250_OPTISCALER_EXTRA` exists because the packaged OptiScaler configuration is
rewritten into the prefix on every launch — editing `OptiScaler.ini` by hand does
nothing. It takes `Section.Option=value` pairs separated by `;` and merges them
over the shipped preset for that game only:

```text
BC250_OPTISCALER_EXTRA="Spoofing.Dxgi=auto;FrameGen.Enabled=true" %command%
```

A key the shipped OptiScaler build does not define stops the launch and names
it, rather than being silently ignored.

**No DLSS option in a game's menu?** That is this package's doing, and it is
deliberate. The preset sets `Spoofing.Dxgi=false`, so the game is told what GPU
it is actually running on — a BC-250 — and games gate their DLSS row on seeing
an NVIDIA GPU. The OptiScaler overlay says `Spoof: Off` when this is why.
Spoofing was turned off because turning it on produced "DX12 not supported" for
a user after enabling frame generation, and because it costs performance. To
trade that back per game:

```text
BC250_OPTISCALER_EXTRA="Spoofing.Dxgi=true" %command%
```

FSR4 itself does not need this. With spoofing off the game's own FSR option is
the input and OptiScaler translates it, which is the normal path here — the
overlay shows `Input: FFX` and the FSR 4.1.1 upscaler running.

**Worth trying, though.** Turning spoofing on gives the game its DLSS path,
which OptiScaler still translates to FSR4, and brings NVIDIA Reflex with it. It
has measured faster than the game's own FSR input on a BC-250, and it is
reported working in The Last of Us Part II and A Plague Tale: Innocence. The
fuller version, which also answers the driver-version question below:

```text
BC250_OPTISCALER_EXTRA="Spoofing.Dxgi=true;Spoofing.Registry=true" %command%
```

Then pick DLSS in the game's own graphics menu. The overlay's frame-time and
upscaler graphs are what settle whether it helped — same save, same spot, both
ways — and we would like to hear the numbers, because if this behaves it is a
candidate for the default.

The spoofing keys are also the two the OptiScaler overlay is allowed to own.
Everything else in the preset is written into `OptiScaler.ini` on every launch —
so editing it, or using the overlay's *Save Settings*, does nothing for the rest
— but `Spoofing.Dxgi` and `Spoofing.VulkanExtensionSpoofing` are written only
into a prefix that has no answer yet. Change either in the overlay, save, and it
sticks from then on. A package update that ships a new OptiScaler build resets
the file and seeds them again. A launch option still beats both.

Two follow-ups, both seen on a BC-250 in The Last of Us Part II:

- The game may then warn that no graphics card was found, or that your RTX 4090
  is on the wrong driver version. DXGI spoofing only changes what the adapter
  reports; that game also reads the registry. Add `;Spoofing.Registry=true`,
  which spoofs vendor, device and driver version there, and `;Spoofing.User32=true`
  if the first complaint survives. The game runs either way — these are warnings,
  not failures.
- If spoofing brings back "DX12 not supported" in an Unreal Engine game, that is
  the error `Spoofing.UEIntelAtomics=true` exists for. Try it before giving the
  spoofing up.

`BC250_FSR4_DEBUG=1` is the one to reach for when something looks wrong — it
puts the FSR4 watermark on screen and writes a Proton log, which turns "FSR4
doesn't seem to work" into something diagnosable.

Without it the package writes no logs at all. That now includes fakenvapi, which
logs to `fakenvapi.log` beside its own DLL by default; the package ships a
`fakenvapi.ini` that turns it off. If you are chasing a Reflex or latency problem
and want it back, edit that file in the prefix — it is not checksummed, so the
change sticks:

```text
<prefix>/drive_c/windows/system32/umu/OptiScaler/fakenvapi.ini
```

### Which FidelityFX bridge you get, and the alternatives

One file in the payload — the FidelityFX bridge, `amd_fidelityfx_upscaler_dx12.dll`
— exists in three pinned builds. Each package ships all three and swaps only that
file; `PROTON_USE_OPTISCALER` picks one per game:

```text
                                          # (unset) BC-250 FSR4 fork RC11, 4.1.1r11 — the default
PROTON_USE_OPTISCALER=signed %command%    # AMD's signed 4.0.2 bridge
PROTON_USE_OPTISCALER=fsr411b %command%   # third-party 4.1.1b, RDNA2 ghosting fix
PROTON_USE_OPTISCALER=fsr411f %command%   # the default, by name
PROTON_USE_OPTISCALER=fsr411rc9 %command%  # the older RC9 build
PROTON_USE_OPTISCALER=fsr411rc10 %command% # the older RC10 build
```

RC9 and RC10 are kept selectable so their performance can be compared against
the default rather than being deleted when superseded. That is the standing
policy: a new release becomes the default, older ones stay reachable. All three
Proton packages ship the same set.

| | default (`fsr411f`) | `signed` | `fsr411b` |
|---|---|---|---|
| Source | [bc250-fsr4-fork v4.0.0-rc11](https://github.com/daniel-h-0/bc250-fsr4-fork/releases/tag/v4.0.0-rc11) | [FidelityFX SDK](https://github.com/GPUOpen-LibrariesAndSDKs/FidelityFX-SDK) | [fsr4xyz 4.1.1b](https://github.com/the3rdparty1917/fsr4xyz/releases/tag/4.1.1b) |
| Watermark shows | `4.1.1r11` | `4.1.1 / SOURCE: DRIVER` (the provider; the bridge file itself is 4.0.2) | `4.1.1b` |
| Aimed at | the BC-250 specifically | the reference | ghosting on RDNA2 |
| Tested on a BC-250 by its author | yes | — | no |
| Signed | no | AMD | no |

**The default is the BC-250 fork's build**, by daniel-h-0, because it is the one
made for and measured on this hardware. RC11 is a version-identification and
validation release over RC10: same 348 shader programs, same performance, same
underlying model — the author's own release notes describe it as passing "a
complete shader rebuild and nine synthetic image comparisons against RC10."
RC10 itself keeps RC9's model, packed arithmetic, weight guards and
synchronisation repair, and trimmed the cold shader compile — its author
measured synthetic cold upscaler setup from 22.24 s to 19.38 s, about 13%,
with the changed shaders producing the same native instructions as RC9. That
is setup time, not FPS. Every setting its README asks for —
`Dx12Upscaler=ffx`, `Dx11Upscaler=ffx_12`, `VulkanUpscaler=ffx_12`,
`UpscalerIndex=0`, `Fsr4ForceModel=2`, `FsrNonLinearColorSpace=false`,
`FsrNonLinearSRGB=auto`, `FsrNonLinearPQ=auto`, `FrameGen.Enabled=false` — is
already what this package enforces. To confirm which build is running, add
`BC250_FSR4_DEBUG=1`; the watermark identifies `4.1.1r11`.

Two things to know about the alternatives:

- Neither the default nor `fsr411b` is a provider version bump. Each binary
  carries its own embedded model, so either likely moves upscaling off the
  provider path the RADV patches target, onto the model baked into the bridge.
  `signed` is the one that leaves the provider in charge: AMD's 4.0.2 bridge is
  a shim that hands off to the payload's 4.1.1 `amdxcffx64.dll` provider, so
  with it the upscaling runs on AMD's own 4.1.1 INT8 model. None of the three
  ever uses a DLL from the game's own folder — the bridge and provider always
  come from the pinned payload, and the game's FSR/DLSS DLLs are only the API
  it talks to.
- The default and `fsr411b` are unsigned. The build pins each by SHA256 and
  writes its origin into the prefix as `Licenses/THIRD-PARTY-UPSCALER.txt`, so
  they are reproducible — not vouched for. The fork's build additionally ships
  its author's licence notices into `Licenses/<version>/`, as that release asks.

Please report whether any of them helps or hurts.

Design and packaging details are in [docs/FSR4-PROTON.md](docs/FSR4-PROTON.md)
and [packages/bc250-fsr4-common/README.md](packages/bc250-fsr4-common/README.md).

---

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

---

## linux-cachyos-bc250-meta

A pure metapackage — it installs no files of its own, it just depends on the recommended BC-250 software set:

- `linux-cachyos-bc250`
- `linux-cachyos-bc250-headers`
- `bc250-dual-audio`
- `proton-cachyos-native-bc250`
- `proton-cachyos-slr-bc250`
- `protonge-latest-bc250`

```bash
sudo pacman -S linux-cachyos-bc250-meta
```

The three Proton packages are alternatives rather than complements — the same pinned FSR4 payload over a different Proton — so having all of them costs roughly 4.5 GB and puts three entries in Steam's compatibility list. That is deliberate: a BC-250 owner gets whichever one a given game prefers without having to know the difference up front — `proton-cachyos-native-bc250` is the fastest, `proton-cachyos-slr-bc250` is the only one that can run a game with EasyAntiCheat or BattlEye, and `protonge-latest-bc250` follows GE-Proton's own releases for the games that want a GE-specific fix. If you would rather pick one, install it directly and skip the metapackage.

The point of it is future-proofing: as more BC-250-specific extras land in this repository (for example a VCN unlock, once upstream support for that exists), they get added to this package's `depends=` array instead of requiring users to notice and install each one by hand. Once you have `linux-cachyos-bc250-meta` installed, a plain `sudo pacman -Syu` picks up any newly added extra the next time this package's version is bumped for that — the same mechanism that already updates every other package in this repository, extended to cover the set as a whole.

Installing it does not remove the ability to manage those packages individually, and does not pull in the RC or BORE kernel variants — it only ever tracks the stable kernel.

---

## Optional tuning

Each of these is genuinely optional; the defaults are fine.

- **[40 CU unlock](docs/PATCHES.md#optional-40-cu-unlock)** — enables the 4
  disabled compute units with `amdgpu.bc250_cc_write_mode=3`. **Read the thermal
  notes first**: it raises power draw, and not every board is stable at 40 CUs.
- **[4K120 at 4:4:4 over HDMI 2.1](#4k120-at-444-over-an-hdmi-21-adapter)** —
  on by default; `amdgpu.bc250_hdmi21=0` switches DSC and HDMI 2.1 PCON
  negotiation off. Only does anything with an active DP→HDMI 2.1 FRL adapter.
- **[AMDGPU scheduler tuning](#optional-amdgpu-scheduler-tuning)** — `sched_policy=2`
  helps some systems and hurts others. Workload-dependent; measure it.
- **[GPU telemetry cache](docs/PATCHES.md#bc-250-apu-telemetry)** — tunables for
  how often SMU metrics are polled.
- **[ROCm / KFD](docs/ROCM.md)** — experimental compute support.

## Optional AMDGPU scheduler tuning

Do **not** add `amdgpu.sched_policy=2` as a required installation step.  
Current BC-250 testing shows that scheduler performance is workload-dependent: some systems or games are slightly faster or smoother with the default hardware scheduler (`sched_policy=0`), while others can benefit from the non-HWS path (`sched_policy=2`). Average FPS and frametime behavior can also move in different directions.

The kernel default is `amdgpu.sched_policy=0`. Test both values on your own system if you want to tune gaming performance or frametimes, and keep the setting that works best for your workload.  
To verify the active value after boot:

```bash
cat /proc/cmdline | grep -o 'amdgpu.sched_policy=[^ ]*'
```

If no value is printed, the normal kernel default (`0`) is in use.

If you previously followed an older version of this README that appended a separate `KERNEL_CMDLINE[default]+=amdgpu.sched_policy=2` line: that line never did anything — `limine-mkinitcpio` only reads the quoted `KERNEL_CMDLINE[default]+="…"` line, and a second one is silently ignored (verified against the tool on a BC-250) — so you were on the default all along. Delete it to avoid confusion:

```bash
sudo sed -i '/^[[:space:]]*KERNEL_CMDLINE\[default\]+=[[:space:]]*amdgpu\.sched_policy=2[[:space:]]*$/d' /etc/default/limine
sudo limine-mkinitcpio
```

To test `sched_policy=2` on CachyOS with Limine, append it inside the quotes of the existing line and regenerate the boot entry:

```bash
sudo sed -i 's|^\(KERNEL_CMDLINE\[default\]+=".*\)"$|\1 amdgpu.sched_policy=2"|' /etc/default/limine
sudo limine-mkinitcpio
```

To return to the default HWS policy:

```bash
sudo sed -i 's| amdgpu.sched_policy=2||' /etc/default/limine
sudo limine-mkinitcpio
```

The optional ROCm/KFD runlist-TLB workaround documented below requires hardware scheduling and therefore does **not** operate with `sched_policy=2`.

---

## cyan-skillfish-governor recommendations

The 8-core telemetry decoding in this repository's kernel patches is unofficial and community-reverse-engineered; it requires the patched SMU firmware described in [step 5](#5-running-8-cpu-cores) of the quick start — **the extra decoding is not a substitute for that firmware patch**, it only applies once you have it.

For [cyan-skillfish-governor](https://github.com/filippor/cyan-skillfish-governor/tree/smu) users on this kernel:

- Use `set-method = "kernel"`. The widened Cyan Skillfish SMU SCLK range above exists specifically to make this option viable end to end. Setting frequency through the kernel interface avoids the extra SMU mailbox round-trips that `set-method = "smu"` requires, and excessive SMU traffic is a real crash risk on this board.
- Leave `fix-metrics = false` and `fix-freq = false`. Both bind-mount a corrected value over a sysfs file to work around inaccurate stock telemetry, but this repository's kernel patches already fix that telemetry at the source: `gpu_metrics`'s `average_gfx_activity` and `gpu_busy_percent` are populated by the same corrected kernel function, and `freq1_input` is read straight from the same already-cached SMU metrics table, not a separate mailbox round-trip. Enabling either on this kernel only adds an extra bind mount (and, for `fix-freq`, a second independent SMU connection) to duplicate a number the kernel already reports correctly.
- A GPU governor makes the display more likely to go black on a mode change, but the kernels now recover from that by themselves — see [Losing the picture on a mode change](#losing-the-picture-on-a-mode-change). The governor is not the cause; what it does is make session handovers much slower (measured at 4.4 s against 0.09 s for the same switch), and a slow handover is what makes the HDMI converter drop out. If your build of cyan-skillfish-governor supports `temp-read = "sysfs"`, use it: a governor holding a DRM connection open just to read the GPU temperature is what makes the handover slow.

### Recommended `config.toml` for this kernel

Putting the above together, the settings that matter on a BC-250 running these
kernels:

```toml
[gpu-usage]
fix-metrics = false
fix-freq    = false
method      = "kernel"
flush-every = 10
temp-read   = "sysfs"   # needs governor v0.4.13 or newer -- see below

[gpu]
set-method = "kernel"
```

Everything else can stay at its default. The file lives at
`/etc/cyan-skillfish-governor-smu/config.toml`; restart the service after
editing it.

`temp-read` needs **cyan-skillfish-governor v0.4.13 or newer**. It landed in
[pull request #30](https://github.com/filippor/cyan-skillfish-governor/pull/30).
Note the quotes: `"sysfs"`, not bare `sysfs`.

**Check that your build actually has it**, because an unknown key is silently
ignored — a governor that does not understand `temp-read` will quietly keep
using DRM:

```bash
sudo journalctl -u cyan-skillfish-governor-smu | grep "temperature read"
```

A build that supports it logs `temperature read: sysfs` at startup. **No output
at all means your governor predates the option**, whatever the config file says.

If you installed the governor from the AUR or the COPR, update the package. If
some setup script or "one-click" toolkit built it from source for you, it may
never update on its own — those installs tend to be pinned to whatever commit
was current on the day they ran. In that case reinstall from the AUR/COPR, or
just leave `temp-read` out: the governor then reads the temperature over DRM,
which works fine. It only makes session handovers slower, and the kernel now
recovers from that by itself, so nothing is broken — you simply do not get the
reduction in how often the display has to be re-detected.

---

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

---

## Documentation

| Document | What's in it |
|---|---|
| [docs/PATCHES.md](docs/PATCHES.md) | Every kernel and Mesa patch, the HDMI 2.1 backport, 4K120 over DSC, the 40 CU unlock, APU telemetry layouts |
| [docs/FSR4-PROTON.md](docs/FSR4-PROTON.md) | How the FSR4 Proton packages are pinned and built |
| [docs/ROCM.md](docs/ROCM.md) | Experimental ROCm / KFD support |
| [docs/BUILDING.md](docs/BUILDING.md) | CI, ccache, the self-hosted runner, published assets, local builds, signing |

---

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
- fish / @iamastrangeloop — BC-250 FSR4 optimization beyond V3: the combined-unroll
  selection, the image-preparation and texture candidates, and the resolution-variant
  coverage with its 8K masked-store guard, together with the measurement harness,
  evidence and prebuilt drivers those results were produced with.
- daniel-h-0 — BC-250 FSR4 v4: the production defaults, and the pinned local
  upscaler manifest that lets Proton load a checksum-verified FSR4 provider and
  OptiScaler from disk instead of downloading them at launch.  
  <https://github.com/daniel-h-0/bc250-fsr4-fork>
- FilippoR / ViRazY - For the kernel GPU frequency ranges
- @dejan_994 — the CH7218 DP-to-HDMI 2.1 adapter quirk: identifying the DPCD
  misreport behind the black screen at 4K120, and the original patch this
  repository's opt-in version is derived from.
- duggasco — BC-250 40 CU unlock: dual-register (CC + SPI) research, testing and tooling.  
  <https://github.com/duggasco/bc250-40cu-unlock>
- rw-r-r-0644 — BC-250 SMU unlock, including the 8-core metrics firmware patch this repository's kernel decoding is derived from.  
  <https://github.com/rw-r-r-0644/bc250-smu-unlock>
- TeleBooth — BC-250 4K120 4:4:4 over DSC: identifying that Cyan Skillfish carries
  two usable DCN200-compatible DSC engines the Linux driver declared absent, the
  DCN201 DSC and HDMI 2.1 PCON patches this repository carries (`dcn201-hdmi21-pcon.patch`
  and `dcn201-enable-dsc.patch` — see [Kernel patch set](docs/PATCHES.md#kernel-patch-set)
  for their current numbers in each set), and the working debugfs capture that proved them.  
  <https://gist.github.com/TeleBooth/d88ef745895d444a401d0e621de9818e>
- Forbidden-Darkness — prebuilt BC-250 UEFI firmware bundling the 8-core unlock with the SMU telemetry patch, and the script that flashes it.  
  <https://github.com/Forbidden-Darkness/AMD-BC-250-UEFI-v2.2-Firmware-Menu-Script/releases>
