# BC-250 FSR4 Proton support — shared pieces

Assets shared by the three FSR4-capable Proton packages:

- `proton-cachyos-native-bc250` — patched build of CachyOS's Proton, zen2-tuned
- `proton-cachyos-slr-bc250` — CachyOS's Steam Linux Runtime Proton build, repacked
- `protonge-latest-bc250` — GE-Proton packaged system-wide

All three install as Steam compatibility tools under
`/usr/share/steam/compatibilitytools.d/`, alongside the distro's own Proton
packages. Package installation writes no user prefix. Proton manages prefixes
and saves normally at launch; removing the package preserves those user files.

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
GE-Proton ships umu-protonfixes as released with GE-Proton11-12; proton-cachyos
builds its own, much later revision of that module from its protonfixes
submodule. A patch rebased onto one does not apply to the other, so each package
uses the copy matching its base (both proton-cachyos packages share one), and
`stage_fsr4_payload_sources` takes the base as an argument rather than guessing.

### `patches/ge-proton/`

For `protonge-latest-bc250`. The upstream BC-250 FSR4 work's own patch, rebased
onto GE-Proton11-12 (GE-Proton11-6 to 11-11 shipped one unchanged file; 11-12
reworked the module: components, streamline, file-path versions). Its declared
base is GE-Proton11-12's `protonfixes/upscalers.py`, which hashes to the
`fb321dc2…` the patch header names. In pinned mode it also keeps OptiScaler from
implicitly enabling FSR4 and refuses file-path versions, as it already did for
DLSS, XeSS and FFX3.

Rooted at the Proton tree (`a/protonfixes/upscalers.py`), because that package
applies it itself, from the extracted tarball root.

### `patches/proton-cachyos/`

For `proton-cachyos-native-bc250` and `proton-cachyos-slr-bc250`. Applies, with
no fuzz, to the unmodified `upscalers.py` of proton-cachyos's protonfixes
submodule (umu-protonfixes `8dadc914`, 2026-10-17; the test fixture
`tests/fixtures/cachyos-native-upscalers.py` is that file). CachyOS used to
carry eight patches of its own on top of the module (`patches/protonfixes/0002-upscalers/`);
they are part of the submodule now, and on 2026-10-17 it also reorganised the
module: `check_optiscaler`/`download_optiscaler` became `check_component`/
`download_component`, `clean_upscaler` became `clean_tracked_files`, and
`__get_upscaler_items` became `_get_items`. The patch was rewritten by hand for
that (the old one still applied to fourteen of sixteen hunks, with fuzz, to code
that no longer matched what the hunks described, and the build failed on the
other two). What differs from the GE copy:

- manifest entries get a `file_description`, which the new download path logs;
- in local mode Streamline is neither fetched nor cleaned (it is not in a pinned
  manifest, and nothing unpinned is fetched);
- the manifest lookup cache is cleared when the manifest changes;
- the upscalers tuple: proton-cachyos always stages the FSR4 provider. That
  upstream behavior remains when no local manifest is selected. In the package's
  local mode, the `fsr4` compatibility setting controls staging, so explicit
  opt-outs and utility calls do not request a provider.

When the submodule moves and the patch stops applying, the build log lists the
failed hunks (see `tests/fixtures/README.md` for replacing the test base).

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
once OptiScaler advertises them, and a `winmm=n,b` DLL override.

That override is not cosmetic. Wine chooses native or builtin by a module's base
name, and its hardcoded default for a DLL it implements itself — `winmm` among
them — is builtin first. Proton's loader hack redirects the proxy's *path* to
`system32/umu/winmm.dll` but does not touch that decision, so a Wine that counts
anything below `system32` as a system directory maps OptiScaler and then drops it
for its own `winmm`. Nothing reports an error: protonfixes logs the payload as
installed, the redirect is logged, and the game just runs with no upscaler. This
is what made proton-cachyos-native-bc250 measure like a plain driver while
protonge-latest-bc250 was visibly faster on the same prefix, and it reproduces
with nothing but the shipped Wine:

    WINE_OPTISCALER_NAME=winmm.dll WINEDEBUG=+loaddll wine rundll32 winmm.dll,x

logging `umu\winmm.dll ... : builtin` without the override and `: native`
followed by the proxy's own chain-load of `system32\winmm.dll` with it. An
override the caller supplied for the proxy name is left alone.

Two deliberate choices about the rest:

- **FSR4 and OptiScaler default to on but stay overridable.** The documented
  `PROTON_FSR4_UPGRADE=0` opt-out also defaults the OptiScaler proxy to off.
  This matters in a previously used prefix: leaving the proxy active lets it
  rediscover a retained provider. Retained files are preserved. An explicit
  `PROTON_USE_OPTISCALER` setting remains a separate user choice. `=1` selects
  the package's pinned version; an unavailable explicit version is rejected.
- **DLSS, XeSS, FFX3, FFX4 and MLFG are scrubbed**, because those we genuinely
  cannot honour: the pinned manifest ships none of them, and pinned mode refuses
  a launch rather than falling back to the network. Left in place, a stale launch
  option from another Proton build becomes a game that will not start.

It also decides what counts as a game launch, which needs the verb
(`run`/`waitforexitandrun`) and then either a non-zero Steam id or a `UMU_ID`.
Steam runs the tool for path conversion, installers and GPU queries too, and
those can inherit a game identity from the session; testing the id alone applies
the whole FSR4 environment to them. Upstream fixed the same bug in rc5 ("Keep
Steam utility calls and zero-ID launches out of game upscaler injection").

`UMU_ID` is there because the id test alone is wrong in the other direction for
umu, which is how Heroic and Lutris run this tool. umu derives `SteamAppId` from
its own `GAMEID` and overwrites `SteamGameId` to match, so a non-Steam title
arrives with both set to `"0"` — Heroic's `GAMEID` for a GOG game is literally
`umu-0`. That reads as a utility call, and the launch silently loses FSR4.
Lutris happened to escape it only because its default `GAMEID` is `umu-default`,
which yields the id `"default"`. umu always sets `UMU_ID` and Steam never does,
so it separates the two cases without weakening the Steam-side rule.

Utility calls retain the local manifest but explicitly disable both upgrades
and clear inherited proxy settings. This prevents CachyOS's default provider
setup from fetching its remote manifest during a path query, and prevents an
inherited game setting from re-enabling the proxy in either tool.

`BC250_FSR4_DEBUG=1` adds the FSR4 watermark, OptiScaler file logging and
`PROTON_LOG=1` — useful for confirming FSR4 is actually the active upscaler.

### One payload with five upscalers (`freefg-all`)

Since 2026-11-08 (owner) the package ships one OptiScaler payload: FreeFG with
all five upscalers side by side, picked with `[Upscalers] Dx12Upscaler` from
OptiScaler's own overlay (*Save Settings* writes it) or from the launch menu,
which reads that key back so it shows the overlay's pick. Until then each
upscaler was a variant (a whole archive) of its own, `PROTON_USE_OPTISCALER`
picked one, and switching started the prefix's `OptiScaler.ini` over.

FreeFG's OptiScaler lists every folder under `OptiScaler/custom/` by name
(`misc/CustomProviders.h`: `custom/<name>/ffx` is a DX12 FFX upscaler,
`custom/<name>/dlss` an NGX runtime, the DLL in it under any name), so each
upscaler that shares a file name with another gets a folder:

| `Dx12Upscaler` | Files | From |
|---|---|---|
| `ffx` (index 0) | `OptiScaler/amd_fidelityfx_upscaler_dx12.dll` = HLX FSR 4, AMD's FSR beside it as `.amd.dll` | `--helixsr-ngx` (`HLX-FSR4/`), `--helixsr-full` (the `.amd.dll`) |
| `hlx-dlss` | `OptiScaler/custom/hlx-dlss/dlss/` = Model E's `helixsr.dll` and its `helixsr.ini` (`Int8 = off`) | `--helixsr-ngx` (`HelixSR/`) |
| `HLX DLSS Preset K` | `OptiScaler/custom/HLX DLSS Preset K/dlss/` = K's four files | `--helixsr-ngx` (`HelixSR/k/`) |
| `FSR 4 RC12` | `OptiScaler/custom/FSR 4 RC12/ffx/amd_fidelityfx_upscaler_dx12.dll` | `--fsr4-bridge` |
| `HLX FSR 4 Full` | `OptiScaler/custom/HLX FSR 4 Full/ffx/` = Full and its `hlx_fsr4.ini` | `--helixsr-full`, or `--helixsr-full-dll` |

- **`hlx-dlss` is a fixed name.** FreeFG's OptiScaler passes HLX DLSS the game's
  input API (`HelixSR.Upscale.Input.API`, `DLSSFeature_Dx12.cpp`) only for a
  custom folder of exactly that name, as FreeFG's own installer lays it out for
  `--upscaler hlx-dlss`. Model E's DLL reads it; Preset K's carries no such
  string, so a folder of its own costs K nothing. The overlay therefore lists
  Model E as `hlx-dlss`; the menu shows the two as one HLX DLSS row with a DLSS
  Model E / DLSS Preset K choice (owner). They cannot share one overlay entry:
  swapping files in a folder at launch breaks protonfixes' checksums.
- **HLX FSR 4 keeps the FidelityFX slot** because it looks for AMD's DLL beside
  itself (`<name>.amd.dll`; without one it logs "HLX FSR 4 only"), and Full finds
  the same file three folders up. Direct3D 11 games take OptiScaler's `ffx_12`
  route through that slot, so they get HLX FSR 4 whatever DX12 upscaler is
  picked (the HLX DLSS variants used to give them RC12). The `.amd.dll` is AMD's
  FSR SDK 2.4.0 upscaler (FSR 4.1.2.4555, signed) from the Scaler part of
  HelixSR 3.3.0 (the same file as 3.2.1's), the version both HLX DLLs are built from. The builder refuses
  HLX FSR 4 unless its shaders end with the `HLXFSR4D` trailer, an HLX DLSS DLL
  without the setup's `HXSRNET1` network trailer, an incomplete `HelixSR/k/`,
  and a Full DLL without its `HLXFULL1` trailer.
- **Full and #187.** 3.2.1's Full DLL showed a black image on R10G10B10A2
  outputs (Ghost of Tsushima; log: `kernel dispatch failed` every frame, HelixSR
  issue #187): its fast post pass writes only RGBA16F and R11G11B10F. HelixSR
  3.3.0 carries the fix (AMD's post pass for the other formats), so the recipes
  no longer pass `--helixsr-full-dll`; the builder keeps the option for the next
  fix posted ahead of a release (a lone DLL that replaces only the release's,
  refused when its `hlx_fsr4.ini` differs).
- **The upscaler is the prefix's.** The shared preset seeds `Dx12Upscaler=ffx`
  and `FSR.UpscalerIndex=0` into a fresh ini, like every key it has; from then
  on the ini decides. The menu hands back `Dx12Upscaler` (and index 0 for `ffx`)
  only when the player picks another upscaler than the ini has, so a pick does
  not reset anything else. An upscaler the menu does not list (XeSS, or another
  FidelityFX provider at index 1 or up) gets a "Keep the overlay's choice" row.
- **Old names.** The config's `optiscaler_upscalers` maps each one-upscaler
  variant name to its `Dx12Upscaler` (`freefg-hlxfsr4` `ffx`, `freefg-hlxdlss`
  `hlx-dlss`, `freefg-hlxdlssk` `HLX DLSS Preset K`, `freefg` `FSR 4 RC12`,
  `freefg-hlxfsr4full` `HLX FSR 4 Full`, and the retired names of
  `RETIRED_VARIANTS` as the one they became). Every name is an alias of the
  payload's version. As a launch option one also sets its upscaler on every
  launch, as the variant did. A prefix last launched with one (protonfixes'
  `upscaler_files` records `<version>-<variant>`; the launcher's
  `previous_upscaler`, longest name first) starts fresh on the move, since its
  files change, and is seeded with that upscaler under the menu's pick; the menu
  gets it as `BC250_MENU_PREVIOUS` to pre-select it. Preset K's kernels and
  weights, which `freefg-hlxdlssk` kept in `hlx-dlss/`, are `RETIRED_FILES`.
- **No default to choose.** `--default` is gone; the payload takes the bare
  OptiScaler version, so an unset `PROTON_USE_OPTISCALER`, `1`, `default` and
  `freefg-all` all reach it.
- **A new prefix starts on No upscaling** (owner, 2026-11-10). "New" is the
  launcher's `new_prefix`: no `bc250-fsr4-menu.json` and no payload record in
  `upscaler_files`, so a prefix of an older package keeps its upscaler. The
  player's `~/.config/bc250-fsr4/settings` (`read_settings`, `key = value`)
  can change that: `default = off | freefg-all | <one-upscaler name>` and
  `menu = 0 | 1`. The launcher hands them to the menu as `BC250_MENU_DEFAULT`
  (`off` or the payload's menu name), `BC250_MENU_AUTO` and, for a new prefix,
  the default's upscaler as `BC250_MENU_PREVIOUS`; it seeds that upscaler
  itself, and falls back to No upscaling when the menu cannot be asked.
  `PROTON_OPTISCALER_MENU=0` skips the menu for one launch and keeps the
  prefix's choice; `=1` shows it (also over `menu = 0`) and clears a save.

- **The FreeFG tree** — built with `--freefg` from FreeFG's
  release zip (mirrored unchanged as `freefg-1.3.0.zip`, its GPL source zip
  beside it).
  [FreeFG](https://github.com/daniel-h-0/freefg) speeds up Intel's XeSS frame
  generation on the BC-250. The tree is the nightly's with FreeFG's OptiScaler
  build as the proxy, the RC12 bridge in `freefg` (`--fsr4-bridge`, what FreeFG
  pins), and FreeFG's own layout for XeFG on the OptiScaler route,
  with `umu/` in the role of the game folder: OptiScaler loads `libxess_fg.dll`
  from its library folder (`Libraries.OptiDllPath`, `umu/OptiScaler`), so
  FreeFG's wrapper goes in under that name and Intel's runtime beside it as
  `bc250_xefg_original.dll`, where the wrapper looks for it; its shaders and
  Vulkan layer go in `OptiScaler/BC250-XeFG/`, also beside the wrapper. Intel's
  runtime is the nightly's own `libxess_fg.dll`, and the builder checks it
  against the hash in FreeFG's `dependencies.json`: the wrapper checks it too,
  at load, and leaves XeFG unavailable on a mismatch, which a player would only
  see as no frame generation. `BC250-XeFG/settings.ini` is left out, because
  the wrapper reads it beside the game's `.exe`. The variant preset is what
  FreeFG's installer writes for its OptiScaler route at 2×, except that frame
  generation starts off (`FrameGen.Enabled = false` until the menu or overlay
  turns it on, `FGInput = upscaler`, `FGOutput = xefg`,
  `XeFG.InterpolationCount = 1`, `XeFG.ForceBorderless = true`,
  `fakenvapi.ForceReflex = 2`). The frame-gen keys and the multiplier are seeded
  on the variant's first launch only, so a 3× or 4× picked in the overlay
  stays. `XeFGPath` and
  `XeLLPath` are left alone, because this OptiScaler reads `XeFGPath` into its
  XeSS library path. The config's `freefg` map, keyed by version, tells the
  launcher where the layer is, and the launcher then sets what FreeFG's
  installer puts in a game's launch options: `VK_LAYER_PATH` and
  `VK_INSTANCE_LAYERS` (prepended, pointing into the prefix, which
  pressure-vessel maps at the same path), `XEFG_WAVE_CONFIG`, and
  `no_staggered_submit` added to `VKD3D_CONFIG` unless
  `BC250_XEFG_NO_STAGGERED_SUBMIT=0`. It also prepends
  `C:\windows\system32\umu\OptiScaler` to `WINEPATH`: 49 of the wrapper's 57
  exports are forwarders to the module `bc250_xefg_original`, which the loader
  looks up by name on the DLL search path. FreeFG's own layout has it beside
  the game's `.exe`; in OptiScaler's library folder nothing finds it, OptiScaler
  gets NULL for every forwarded export, and Spider-Man 2 crashed calling
  `xefgSwapChainSetLoggingCallback` while creating its swapchain.
  With `--mfg-unlocker`, the payload also carries
  [MFG Unlocker](https://github.com/dashdogy/MFG-Unlocker) (MIT, by dashdogy;
  1.7.0, the newest; FreeFG's 3×/4× checks on the BC-250 used 1.6.0) as the OptiScaler
  plugin `OptiScaler/plugins/MFGUnlocker.asi`, loaded through the shared
  `LoadAsiPlugins = true`. Without it Intel's runtime generates one frame per
  real frame on this GPU; with it OptiScaler's XeFG menu offers 3× and 4×. The
  shipped `OptiScaler.ini` gains `[XeFG] XeFGModel=default`, as FreeFG's
  installer writes it: MFG Unlocker reads that key (OptiScaler does not), and
  unset it runs its own model, on which FreeFG's shaders cover only 7 of their
  13 programs. It goes into the ini rather than the preset because protonfixes
  refuses a preset key the ini does not have. MFG Unlocker's license, which its
  zip does not carry, is pinned by the tag's commit.
- **Frame generation** starts off: `FrameGen.Enabled = false`
  is seeded on the payload's first launch (FG_DEFAULT under FREEFG_PRESET's XeFG
  wiring), so the menu's "Enable frame generation" box shows the prefix's own
  value and only the switch itself is ever written.
- **Retired names** — `RETIRED_VARIANTS` in the builder keeps every name an
  older package had before the one-upscaler variants, as the one it became: the
  HelixSR ones (`helixsr`, `helixsr-ffx`, `freefg-helixsr`) `freefg-hlxdlss`,
  `hlxdlssk` `freefg-hlxdlssk`, `hlxfsr4` `freefg-hlxfsr4`, the stock nightly and
  its bridges (`optiscaler`, `signed`, `fsr412f`, `fsr411f`, `fsr411b`,
  `fsr411rc9`, `fsr411rc10`) `freefg`; each then stands for that one's upscaler
  (see Old names above). The menu maps any saved old name to the payload.

Moving to another payload cleans up after the previous one. protonfixes replaces the
payload when the version changes, but it only removes the files it checksums:
`.ini` files and anything written at run time stay. So on every game launch the
launcher (`clean_other_variants`) removes each file the manifest lists for some
variant but not the selected one, every folder only other variants use (with
whatever was written into it, such as `HelixSR/` and its logs), every folder
of `RETIRED_FOLDERS` (folders an older package left that no manifest names any
more: Scaler 1.1.0's `HelixSR-fsrfg/` and the Scaler 2.x's `HelixSR/`), the
files of `RETIRED_FILES` (HelixSR 2.0's `OptiScaler/amd_fidelityfx_dx12.dll` and
`OptiScaler/helixsr.ini`, a prefix with them also starting fresh since its
`OptiScaler.ini` points `FfxDx12Path` at that DLL; `OptiScaler/hlx_fsr4.ini`,
where the first `freefg-hlxfsr4full` had HLX FSR 4 Full), and
FreeFG's logs when FreeFG is not selected. Files the selected variant shares are
left to protonfixes, nothing outside `system32/umu` is touched, and nothing at
all while OptiScaler is off.

Neither HLX FSR 4 nor the RC12 bridge is a provider bump: each carries its own
model, so upscaling runs on that rather than through the pinned `amdxcffx64`
provider, which stays in the payload for OptiScaler's FSR4 path.

Two consequences of pinning are worth stating, because they are what make this
mechanism necessary at all:

- A tester cannot simply drop the DLL into a prefix or a game directory.
  `check_optiscaler` verifies every file's SHA256 before launch and refuses to
  start otherwise, and OptiScaler loads its libraries from
  `Libraries.OptiDllPath` rather than from the game. Trying an alternate binary
  requires a build.
- A variant would be a whole second archive rather than a patch, because
  protonfixes installs an OptiScaler entry all-or-nothing against one set of
  hashes (about 78 MB per variant in each package). That is why the upscalers
  share one payload in folders of their own instead.

The payload ships `Licenses/THIRD-PARTY-UPSCALER.txt` into the prefix
naming the origin URL and SHA256, so an unsigned DLL is never sitting there
unexplained.

## Game presets (`../../scripts/build-game-presets.py`)

Per-game OptiScaler settings are data, not package content:
`.github/workflows/game-presets.yml` builds `game-presets.json.gz` every night
from FreeFG's `packaging/recipes/recipes.json`, the OptiScaler wiki's git
repository and two reference `OptiScaler.ini` files (upstream's and FreeFG's
build, which say which section a bare wiki key belongs to), and uploads it to the
`bc250-game-presets` release when its content changed. Nothing in the source
fingerprint refers to it, so it never starts a package build.

The launcher (`load_presets`, `find_game`, `game_preset`, `apply_game_preset`)
downloads it at most daily into `~/.cache/bc250-fsr4/`, matches the game by Steam
app id, `.exe` or normalised title, and on a fresh `OptiScaler.ini` merges the
selected settings as a layer between the package seeds and the menu's choices.
Every setting is filtered against `optiscaler_ini_keys` of the variant being
launched, because protonfixes refuses a launch on a key that build's ini lacks,
and against `PRESET_LOCKED` (the package's wiring). Any error in this path is
logged and the launch goes on without a preset. `BC250_GAME_PRESETS_FILE=<path>`
reads a local database instead, to try one before it is published.

The wiki half keeps every condition it can: FreeFG's structured reading where it
has one, otherwise the sentence around a `Key=value` span, classified as a GPU or
an input condition or kept as text that never matches. "Matching" applies what
has no condition or one that holds on a BC-250; "everything" ignores conditions.
README.md, "Game presets", is the player's side.

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

The 24-key OptiScaler configuration, applied via `PROTON_OPTISCALER_CONFIG` to a
prefix that has no answer of its own: OptiScaler ships every key as `auto`, a key
still at `auto` counts as nobody's answer, and anything else the prefix wrote —
from the overlay's *Save Settings* or from this preset on the launch before —
stands. Only the variant presets below, the debug keys and
`BC250_OPTISCALER_EXTRA` are applied on every launch.

**This file is coupled to the OptiScaler build.** The patch above makes an
unknown key *fatal* in pinned mode, so a build that renames or drops an option
turns into a game that will not start. `scripts/build-fsr4-payload.py` validates
the preset against the actual extracted `OptiScaler.ini` on every build,
including the normal mirrored fallback. The candidate selector additionally
checks keys before choosing a newer nightly.

If you add a key here that no OptiScaler build defines, that check fails the
selection at build time instead of at a customer's launch.

## Payload

The pinned third-party artifacts are mirrored in this repository's
`bc250-fsr4-payload` release, not committed here — they are about 1 GB by now,
and git keeps them forever.

Mirroring is not gratuitous. OptiScaler nightlies are pruned after roughly a
month, so a pinned nightly URL 404s within weeks, and the FSR4 provider is
served from a GitHub Pages site that can change without versioning. The mirror
makes the build reproducible; optional tracking can select a newer nightly.

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

It is used only as a signature surrogate beside the proxy: NVIDIA's DLSS
upscaler itself never runs (HLX DLSS in the Scaler is HelixSR's own
implementation), and no DLL is ever taken from a game directory.
