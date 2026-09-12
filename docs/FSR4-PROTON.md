# FSR4-capable Proton — details

How the two FSR4 Proton packages are built and why. For installing and using
them, see the [README](../README.md#fsr4-capable-proton-opt-in).

---

### What "pinned" means here

Stock protonfixes downloads the provider and OptiScaler from a remote manifest when a game starts. That needs network at launch, pins nothing, and OptiScaler nightlies are pruned after about a month — so a URL that worked in testing 404s for a customer weeks later.

This package ships those artifacts inside itself and points protonfixes at a local manifest instead. Every archive and every extracted file is SHA256-verified before it reaches a prefix, and a mismatch **refuses the launch** rather than quietly falling back to the network. The same strictness applies to the OptiScaler configuration: a preset key the shipped build does not define fails the launch, which is why the build validates the preset against the build's own `OptiScaler.ini` before selecting it.

### Launch options

FSR4 and OptiScaler are on by default, but they are still yours to set per game:

```text
PROTON_FSR4_UPGRADE=0 %command%      # disable the packaged FSR4 upgrade and default proxy
BC250_FSR4_DEBUG=1 %command%         # FSR4 watermark + OptiScaler log + PROTON_LOG
PROTON_OPTISCALER_NAME=dxgi.dll      # proxy OptiScaler as dxgi, for games that use winmm
```

The opt-out also defaults OptiScaler to off, so it cannot load a provider retained
from a prior launch. Explicit `PROTON_USE_OPTISCALER` choices remain available;
prefix payloads and saves are preserved. Steam utility calls use the local
manifest with both upgrades disabled, including when game settings are inherited.

The preset is rewritten into `OptiScaler.ini` on every launch, which is what
makes a launch reproducible from its launch options alone, with no invisible
state in a prefix deciding what you get. `Spoofing.Dxgi` and
`Spoofing.VulkanExtensionSpoofing` are the exception, declared as `seed_once` in
`optiscaler-preset.json`: they are written into a prefix that has no answer of
its own, and left alone afterwards, so a player can own them from the OptiScaler
overlay. OptiScaler ships every spoofing key as `auto`, so "not auto" is what
marks a prefix as having been decided — by this package on the first launch, or
by the player after that. A packaged OptiScaler bump re-extracts the ini, which
resets it to `auto` and re-seeds. Anything unreadable keeps the enforced value,
because the safe way to be wrong is a launch that behaves as documented.
`BC250_OPTISCALER_EXTRA` is merged last and so still wins over both. The
`seed_once` list is checked against the preset at build time: a name the preset
does not set would quietly hand the default to OptiScaler instead of us.

`PROTON_OPTISCALER_NAME` is the one variable in the owned set a caller may still
supply. Everything else there addresses the pinned payload by path or by name, so
a caller-supplied value would either break the launch or swap in something
unverified; the proxy name does neither. It selects which import the game resolves
to OptiScaler, not which DLL is loaded — the manifest pins that either way — so the
worst a wrong name can do is leave OptiScaler unloaded. The package proxies
`winmm` because that is what has been tested on the BC-250, but a game that ships
its own `winmm.dll` (mod loaders and ASI loaders do) gets its own file back and
the upscaler silently never appears; `PROTON_OPTISCALER_NAME=dxgi.dll` moves it to
an import such a game does not use, and upstream protonfixes defaults to that name
anyway. The value is normalised (a bare `dxgi` becomes `dxgi.dll`) and checked for
shape, because it reaches Wine's loader as a name to match; the matching
`WINEDLLOVERRIDES` entry is derived from whatever name ends up in effect, since a
`winmm=n,b` left behind next to a `dxgi` proxy would load Wine's own builtin and
reproduce the original bug. OptiScaler itself accepts `dxgi.dll`, `winmm.dll`,
`version.dll`, `dbghelp.dll`, `d3d12.dll`, `wininet.dll` and `winhttp.dll`; the
value is not checked against that list, because it is OptiScaler's to grow and a
name outside it fails visibly as "no upscaler" rather than dangerously.

Note that this has nothing to do with `Spoofing.Dxgi`, which the preset sets to
`false`. The proxy name decides which import resolves to OptiScaler; the spoofing
key decides whether OptiScaler reports an NVIDIA vendor/device ID and GPU name to
the game once loaded. The two are independent, and the shared word is a trap when
reading a bug report.

`PROTON_DLSS_UPGRADE`, `PROTON_XESS_UPGRADE`, `PROTON_FFX3_UPGRADE`, `PROTON_FFX4_UPGRADE`, the older `PROTON_FSR3_UPGRADE` spelling and `PROTON_MLFG_UPGRADE` are cleared: this package ships none of those upscalers, and in pinned mode a request for one that is absent stops the game from starting. A stale launch option left over from another Proton build would otherwise become a game that will not launch.

### Which Proton, and which OptiScaler

`protonge-latest-bc250` tracks the newest GE-Proton release automatically; `pkgver` follows it (`GE-Proton11-6` → `11.6`). The Steam-internal tool name stays `protonge-latest-bc250` across upgrades on purpose — Steam stores that name per game, so a name carrying the version would reset everyone's per-game choice on every update.

`proton-cachyos-native-bc250` follows CachyOS's `proton-cachyos-native` PKGBUILD, pinned to the same `CachyOS-PKGBUILDS` commit as the Mesa packages. Rather than carrying a diff of that PKGBUILD, the prepare step rewrites it and asserts on every anchor it touches, so an upstream change fails the build naming what moved instead of a patch applying at an offset and quietly meaning something else.

The OptiScaler build is pinned rather than tracked. Nightlies publish most days, and following them would rebuild a ~700 MB package daily for a payload nobody asked to move. Moving it forward requires updating `FALLBACK_TAG`, `FALLBACK_ASSET` and `FALLBACK_SHA256` together in `scripts/select-optiscaler.py`, which changes the component fingerprint. `BC250_FSR4_TRACK_OPTISCALER=1` checks the newest nightly instead. Payload assembly validates the preset against the actual extracted INI on every route, including the mirrored fallback.

Run the packaging and launch regression checks with
`python3 -B -m unittest discover -s tests -v`. They exercise both real upstream
protonfixes modules, block network access, and check opt-outs, utility calls,
payload integrity, preset validation and the generated production patch series.

The design notes, including why the OptiScaler payload is rearranged the way it is and why two separate copies of the protonfixes patch exist, are in [packages/bc250-fsr4-common/README.md](../packages/bc250-fsr4-common/README.md).

Either package can also be built locally into a tarball that unpacks into
`~/.local/share/Steam/compatibilitytools.d`, under its own name and with your own
patches applied, for handing to a tester without publishing anything: see
[Local Proton builds for private distribution](BUILDING.md#local-proton-builds-for-private-distribution).


