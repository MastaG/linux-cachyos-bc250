# BC-250 CachyOS kernels + Mesa repository

[![Build and publish BC-250 CachyOS kernels and Mesa](https://github.com/MastaG/linux-cachyos-bc250/actions/workflows/build-release.yml/badge.svg)](https://github.com/MastaG/linux-cachyos-bc250/actions/workflows/build-release.yml)

A pacman repository for the **AMD BC-250** on CachyOS: patched kernels, patched
Mesa with working FSR4, ready-made FSR4 Proton builds, and Dolby Digital audio
output. Everything is prebuilt — you add the repository and install packages.

Packages: <https://github.com/MastaG/linux-cachyos-bc250/releases/tag/repo>

## What you get

| Package | What it is |
|---|---|
| `linux-cachyos-bc250` | Stable BC-250 kernel (`-rc` and `-bore` variants also built) |
| `mesa` / `lib32-mesa` | Patched Mesa: GFX1013 async compute on by default, FSR4 support |
| `mesa-git` / `lib32-mesa-git` | Same patches on Mesa main, optional |
| `protonge-latest-bc250` | GE-Proton with FSR4 ready to go |
| `proton-cachyos-native-bc250` | CachyOS Proton with FSR4, built for Zen 2 |
| `bc250-dual-audio` | Dolby Digital 5.1 output over DisplayPort |
| `linux-cachyos-bc250-meta` | Installs the recommended set in one go |
| `nct6687d-dkms` | Fan and temperature sensors |

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

Or install [`linux-cachyos-bc250-meta`](#linux-cachyos-bc250-meta) instead, which pulls in the stable kernel, its headers, and the other BC-250 extras (currently `bc250-dual-audio` and both FSR4 Proton packages) together, and picks up any new ones added to it in the future on a normal `pacman -Syu`.

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

---

## Mesa behavior, performance and stability

The patched Mesa packages enable the GFX1013 async-compute path by default; no environment variable is required for normal use.  
Games that benefit from async compute can see a significant performance improvement. In current BC-250 community testing, Cyberpunk 2077 has shown gains of roughly 10–15 FPS.

Async compute can also increase GPU load and voltage requirements.  
Some BC-250 systems that were previously stable have shown green-screen or black-screen GPU crashes after enabling the async-compute path. Community reports indicate that some boards need a small GPU-voltage increase to remain stable, with around +25 mV being sufficient in several cases. This is not required on every BC-250: if the GPU is stable, no voltage change is needed.

`RADV_GFX103=1` is separate from async compute and should **not** be enabled globally.  
Use it only per-game for titles that need the experimental GFX10.3 mesh-shader path. It has been tested successfully with Final Fantasy VII Rebirth, which currently does not start on the BC-250 without the override in community testing. Mesh shaders work for this test case, but **task shaders are still not working correctly**. Games that depend on task shaders may render incorrectly, hang or crash when `RADV_GFX103=1` is enabled.

---

## FSR4-capable Proton (opt-in)

Two packages, same idea: a Steam compatibility tool with everything FSR 4.1.1
needs on this hardware already inside it — the AMD FSR4 provider, OptiScaler,
OptiPatcher, [fakenvapi](https://github.com/optiscaler/fakenvapi) and a
known-good OptiScaler configuration.

| package | base | build |
|---|---|---|
| `protonge-latest-bc250` | GE-Proton, repacked | minutes; tracks the newest GE release |
| `proton-cachyos-native-bc250` | CachyOS's Proton, rebuilt from source | hours; Zen 2-tuned |

```bash
sudo pacman -S protonge-latest-bc250            # or
sudo pacman -S proton-cachyos-native-bc250
```

Both can be installed at once, and both sit alongside the distro's own Proton
packages. Restart Steam, then pick **GE-Proton 11-6 (BC-250 FSR4)** or
**proton-cachyos-… (native, BC-250 FSR4)** under a game's Properties →
Compatibility.

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
PROTON_USE_OPTISCALER=fsr411b %command%   # experimental upscaler, see below
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
overlay shows `Input: FFX` and the FSR 4.1.1 upscaler running. Spoofing only
matters if you specifically want the game's DLSS path, for Reflex or because
DLSS input measures better in that game. If you try it, the overlay's frame-time
and upscaler graphs make the comparison, and we would like to hear the numbers.

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

### Experimental upscaler variants

Two opt-in payloads swap a single file — the FidelityFX bridge,
`amd_fidelityfx_upscaler_dx12.dll` — for an alternative build. Leave the
variable out and you get the normal, AMD-signed default.

```text
PROTON_USE_OPTISCALER=fsr411b %command%   # third-party 4.1.1b, RDNA2 ghosting fix
PROTON_USE_OPTISCALER=fsr411f %command%   # BC-250 FSR4 fork, RC9 (4.1.1r9)
```

| | `fsr411b` | `fsr411f` |
|---|---|---|
| Source | [fsr4xyz 4.1.1b](https://github.com/the3rdparty1917/fsr4xyz/releases/tag/4.1.1b) | [bc250-fsr4-fork v4.0.0-rc9](https://github.com/daniel-h-0/bc250-fsr4-fork/releases/tag/v4.0.0-rc9) |
| Aimed at | ghosting on RDNA2 | BC-250 specifically, 1440p performance |
| Tested on a BC-250 by its author | no | yes |

Both are genuine experiments, not recommendations:

- Neither is a provider version bump. Each binary carries its own embedded
  model, so selecting one likely moves upscaling off the provider path the RADV
  patches target, onto the model baked into the bridge.
- Both are unsigned, where the default is AMD-signed. The build pins each by
  SHA256 and writes its origin into the prefix as
  `Licenses/THIRD-PARTY-UPSCALER.txt`, so they are reproducible — not vouched
  for. `fsr411f` additionally ships its author's licence notices into
  `Licenses/<version>/`, as that release asks.

`fsr411f` needs no other change: every setting the RC9 archive's README asks for —
`Dx12Upscaler=ffx`, `Dx11Upscaler=ffx_12`, `VulkanUpscaler=ffx_12`,
`UpscalerIndex=0`, `Fsr4ForceModel=2`, `FsrNonLinearColorSpace=false`,
`FsrNonLinearSRGB=auto`, `FsrNonLinearPQ=auto`, `FrameGen.Enabled=false` — is
already exactly what this package enforces. To confirm which build is running,
add `BC250_FSR4_DEBUG=1`; the watermark identifies `4.1.1r9` for RC9.

Please report whether either helps or hurts.

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
- `protonge-latest-bc250`
- `proton-cachyos-native-bc250`

```bash
sudo pacman -S linux-cachyos-bc250-meta
```

The two Proton packages are alternatives rather than complements — the same pinned FSR4 payload over a different Proton — so having both costs roughly 3 GB and puts two entries in Steam's compatibility list. That is deliberate: a BC-250 owner gets whichever one a given game prefers without having to know the difference up front. If you would rather pick one, install it directly and skip the metapackage.

The point of it is future-proofing: as more BC-250-specific extras land in this repository (for example a VCN unlock, once upstream support for that exists), they get added to this package's `depends=` array instead of requiring users to notice and install each one by hand. Once you have `linux-cachyos-bc250-meta` installed, a plain `sudo pacman -Syu` picks up any newly added extra the next time this package's version is bumped for that — the same mechanism that already updates every other package in this repository, extended to cover the set as a whole.

Installing it does not remove the ability to manage those packages individually, and does not pull in the RC or BORE kernel variants — it only ever tracks the stable kernel.

---

## Optional tuning

Each of these is genuinely optional; the defaults are fine.

- **[40 CU unlock](docs/PATCHES.md#optional-40-cu-unlock)** — enables the 4
  disabled compute units with `amdgpu.bc250_cc_write_mode=3`. **Read the thermal
  notes first**: it raises power draw, and not every board is stable at 40 CUs.
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

---

## cyan-skillfish-governor recommendations

The 8-core telemetry decoding in this repository's kernel patches is unofficial and community-reverse-engineered; the Cyan Skillfish SMU firmware was written with 6 CPU cores in mind, and the extra decoding only applies to boards running a patched BIOS that unlocks the two extra cores.

For [cyan-skillfish-governor](https://github.com/filippor/cyan-skillfish-governor/tree/smu) users on this kernel:

- Use `set-method = "kernel"`. The widened Cyan Skillfish SMU SCLK range above exists specifically to make this option viable end to end. Setting frequency through the kernel interface avoids the extra SMU mailbox round-trips that `set-method = "smu"` requires, and excessive SMU traffic is a real crash risk on this board.
- Leave `fix-metrics = false` and `fix-freq = false`. Both bind-mount a corrected value over a sysfs file to work around inaccurate stock telemetry, but this repository's kernel patches already fix that telemetry at the source: `gpu_metrics`'s `average_gfx_activity` and `gpu_busy_percent` are populated by the same corrected kernel function, and `freq1_input` already reflects a real `GetGfxclkFrequency` SMU read. Enabling either on this kernel only adds an extra bind mount (and, for `fix-freq`, a second independent SMU connection) to duplicate a number the kernel already reports correctly.

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
| [docs/PATCHES.md](docs/PATCHES.md) | Every kernel and Mesa patch, the HDMI 2.1 backport, the 40 CU unlock, APU telemetry layouts |
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
- duggasco — BC-250 40 CU unlock: dual-register (CC + SPI) research, testing and tooling.  
  <https://github.com/duggasco/bc250-40cu-unlock>
- rw-r-r-0644 — BC-250 SMU unlock, including the 8-core metrics firmware patch this repository's kernel decoding is derived from.  
  <https://github.com/rw-r-r-0644/bc250-smu-unlock>
- Forbidden-Darkness — prebuilt BC-250 UEFI firmware bundling the 8-core unlock with the SMU telemetry patch, and the script that flashes it.  
  <https://github.com/Forbidden-Darkness/AMD-BC-250-UEFI-v2.2-Firmware-Menu-Script/releases>
