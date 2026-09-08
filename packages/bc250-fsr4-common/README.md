# BC-250 FSR4 Proton support — shared pieces

Assets shared by the two FSR4-capable Proton packages:

- `proton-cachyos-native-bc250` — patched build of CachyOS's Proton, zen2-tuned
- `protonge-latest-bc250` — GE-Proton packaged system-wide

Both install as Steam compatibility tools under
`/usr/share/steam/compatibilitytools.d/`, alongside the distro's own Proton
packages. Nothing is written to `$HOME`, and `pacman -R` removes them cleanly.

## Why this exists

FSR4 on the BC-250 needs three things, and only the first is already handled by
the distro:

1. **A Wine that will talk FSR4 to a gfx1013 iGPU.** `wine-cachyos` already
   carries the win32u change that spoofs the adapter as Navi31 when
   `FSR4_UPGRADE=1` is set — without it `NtGdiDdDDIQueryAdapterInfo` returns
   `STATUS_NOT_IMPLEMENTED` on an integrated GPU and FSR4 never initialises.
   GE-Proton carries the same change as `0165-win32u-*`. Nothing to do.
2. **The FSR4 provider and OptiScaler.** Stock protonfixes downloads these at
   launch from a remote manifest. That is not reproducible, needs network at
   game start, and pins nothing.
3. **A known-good OptiScaler configuration**, applied through
   `PROTON_OPTISCALER_CONFIG`.

## `patches/*/0001-pinned-upscaler-manifest.patch`

Adds `PROTON_UPSCALER_MANIFEST` to protonfixes' `upscalers.py`: point it at a
local JSON manifest and artifacts are read from disk, with mandatory archive and
critical-file SHA256 verification, relative paths confined to the manifest
directory, and validation of everything requested *before* any prefix payload is
written. A local-mode failure stops the launch rather than falling back to the
network. Absent the variable, stock behaviour is unchanged.

**There are two copies, because there are two different `upscalers.py` files.**
GE-Proton ships umu-protonfixes as released; proton-cachyos applies eight
patches of its own to that same file first. A patch rebased onto one does not
apply to the other — three of sixteen hunks fail — so each package uses the copy
matching its base, and `stage_fsr4_payload_sources` takes the base as an
argument rather than guessing.

### `patches/ge-proton/`

For `protonge-latest-bc250`. This is the upstream BC-250 FSR4 work's own patch,
unmodified: its declared base is GE-Proton11-6's `protonfixes/upscalers.py`, and
that file in GE-Proton11-6 hashes to the `4128896c…` the patch header names.

Rooted at the Proton tree (`a/protonfixes/upscalers.py`), because that package
applies it itself, from the extracted tarball root.

### `patches/proton-cachyos/`

For `proton-cachyos-native-bc250`. Rebased onto the `upscalers.py` that results
*after* proton-cachyos's own eight `patches/protonfixes/0002-upscalers/` patches
apply. Thirteen of fifteen hunks applied unchanged; two were resolved by hand:

- the OptiScaler config loop, whose context differs (`log.debug(e)`)
- the upscalers tuple, where **proton-cachyos hardcodes `('fsr4', …, True)`**
  and that was deliberately kept. We ship a pinned provider, so always
  validating it is what we want.

Rooted for `patch -d <protonfixes> -Np1`, which is exactly how proton-cachyos's
`Makefile.in` applies everything under `patches/protonfixes/`:

```make
$(OBJ)/.protonfixes-post-source: patches-source
	$(foreach p,$(shell find $(PATCHES_SRC)/protonfixes/ -name "*.patch" | sort),\
		patch -d $(PROTONFIXES_SRC) -Np1 -i $(p) &&) true
```

Because that glob is sorted, dropping this in as a later-sorting directory is
all the integration required — no Makefile or `prepare()` changes.

## `bc250-fsr4-launch.py` and `proton-shim.sh`

Steam runs the shim named by `toolmanifest.vdf`; the shim runs the wrapper; the
wrapper `execve()`s the real Proton. It exists so the pinned payload can be
selected without patching Proton's own launcher, and the `execve` means Steam
still ends up supervising exactly one process.

The two packages lay the tool directory out differently — protonge-latest keeps
GE under `ge/` and installs the shim as `proton`, while proton-cachyos-native
*is* the Proton tree and installs the shim as `bc250-fsr4-proton` beside
upstream's own `proton`. Rather than encode that, the wrapper reads both paths
from the config written at build time, so one wrapper serves both.

What it sets is limited to what the package owns — the manifest path, the
OptiScaler proxy name, the preset — plus the two `VK_NVX_*` names appended to
`VKD3D_DISABLE_EXTENSIONS`, which vkd3d's separate D3D12 device cannot create
once OptiScaler advertises them.

Two deliberate choices about the rest:

- **FSR4 and OptiScaler default to on but stay overridable.** `get_version()`
  maps both `0` and `1` to `'default'`, and the pinned manifest holds exactly
  one entry per upscaler, so `PROTON_FSR4_UPGRADE=0` in a game's launch options
  cleanly turns FSR4 off and `=1` still resolves to what we ship. The upstream
  runtime scrubs these instead; a distro package should not ignore a launch
  option a user set on purpose.
- **DLSS, XeSS, FFX3, FFX4 and MLFG are scrubbed**, because those we genuinely
  cannot honour: the pinned manifest ships none of them, and pinned mode refuses
  a launch rather than falling back to the network. Left in place, a stale launch
  option from another Proton build becomes a game that will not start.

It also decides what counts as a game launch, which needs both the verb
(`run`/`waitforexitandrun`) and a non-zero Steam id. Steam runs the tool for path
conversion, installers and GPU queries too, and those can inherit a game identity
from the session; testing the id alone applies the whole FSR4 environment to
them. Upstream fixed the same bug in rc5 ("Keep Steam utility calls and zero-ID
launches out of game upscaler injection").

`BC250_FSR4_DEBUG=1` adds the FSR4 watermark, OptiScaler file logging and
`PROTON_LOG=1` — useful for confirming FSR4 is actually the active upscaler.

## `../../scripts/build-fsr4-payload.py`

Assembles the payload at build time and writes both the manifest and the
wrapper's config, so the versions the wrapper asks for and the versions the
manifest offers come out of one run and cannot drift.

It has to run at build time rather than shipping a static manifest: the patch
above requires a per-file SHA256 for every non-`.ini` entry of the OptiScaler
build, so the manifest can only be computed from the archive actually selected.

The OptiScaler tree it lays out is not the archive as shipped —
`OptiScaler.dll` becomes the `winmm.dll` proxy, the pinned NVIDIA NGX surrogate
and the older 4.0.2 FidelityFX bridge are added (the bundled 4.1.1 SDK would
otherwise shadow the equally versioned provider our RADV drives), OptiPatcher
goes into `plugins/`, and upstream's interactive `.bat`/`.sh` installers are
removed. The archive is written deterministically, since its SHA256 is both its
filename and its manifest entry.

## `optiscaler-preset.json`

The 23-key OptiScaler configuration, applied via `PROTON_OPTISCALER_CONFIG`.

**This file is coupled to the OptiScaler build.** The patch above makes an
unknown key *fatal* in pinned mode, so a build that renames or drops an option
turns into a game that will not start. `scripts/select-optiscaler.py` therefore
validates the preset against a candidate build's `OptiScaler.ini` before that
build is used, and falls back to the mirrored known-good one otherwise.

If you add a key here that no OptiScaler build defines, that check fails the
selection at build time instead of at a customer's launch.

## Payload

The pinned third-party artifacts are mirrored in this repository's
`bc250-fsr4-payload` release, not committed here — they are ~71 MB, and git
keeps them forever.

Mirroring is not gratuitous. OptiScaler nightlies are pruned after roughly a
month, so a pinned nightly URL 404s within weeks, and the FSR4 provider is
served from a GitHub Pages site that can change without versioning. The mirror
makes the build reproducible; the selector still tracks upstream when it can.

Two pinned artifacts are *not* mirrored, because they are served from immutable
commit-addressed URLs and cannot change under us: the FidelityFX SDK bridge and
the NVIDIA NGX surrogate.

## `licenses/`

The notices that ship beside the redistributed binaries, byte-identical to the
upstream files at the commits pinned in the PKGBUILDs.

The FidelityFX SDK is MIT licensed, so redistribution is straightforward.

`nvngx_dlss.dll` is the one that needed a decision. The upstream BC-250 FSR4
project deliberately does not redistribute it — its installer downloads it at
install time — and GE-Proton does not bundle it either, which is why stock
protonfixes fetches it at launch. A pacman package cannot do that: whatever the
build pulls in ends up inside the `.pkg.tar.zst`. It is shipped here as a
conscious call, under the NVIDIA RTX SDK licence's clause 1(c), which permits
distributing SDK material in object form as incorporated into an application
with material additional functionality. Without it, games whose DLSS input path
checks for an NVIDIA-signed library lose the OptiScaler hook entirely; the
FSR/XeSS/Vulkan input paths and the whole ffx upscaler chain are unaffected.

It is used only as a signature surrogate beside the proxy. No DLSS upscaler is
installed, and no DLL is ever taken from a game directory.
