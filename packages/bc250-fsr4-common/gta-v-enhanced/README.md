# GTA V Enhanced: Social Club swapchain fix

This is a draft integration of a locally verified OptiScaler fix for GTA V
Enhanced (Steam 3240220, game 1.0.1158.16). The package recipes still use the
published FreeFG 1.1.6 archive. The optional builder input below lets a maintainer
package the fixed DLL before a FreeFG release contains it. It is not enabled by
the three PKGBUILD generators yet, and no replacement binary is downloaded here.

## Failure and fix

Social Club creates an auxiliary D3D12 swapchain. The reported descriptor was
0×0: DXGI obtains its dimensions from the window. Sending it through XeFG
reproduced a read at address `0x58`, at offset `0x2123AA` in the unmodified Intel
runtime. Turning interpolation off did not prevent XeFG context creation.

Resolving zero dimensions alone did not fix the actual game: its Social Club
client area was 119×100, outside OptiScaler's existing below-100-pixel heuristic.
`DxgiFactoryWrapping=true` avoided the crash but stalled at **Initializing** on
this stack. We do not recommend that workaround.

The patch marks factories created by `SocialClubD3D12Renderer.dll` using DXGI
private data. The regular and DLSSG swapchain hooks pass those factories through
to native DXGI before touching the game's FG state. The marker follows the
factory's COM lifetime and interface aliases. The existing small-window guard
also resolves zero axes from the HWND, without changing the supplied descriptor.
This keeps Social Club available while the game's own swapchain uses XeFG.

## Source and tested binary

`0001-social-club-auxiliary-swapchains.patch` is a complete `git format-patch`
export, including the source-level regression harness. Apply it to the published
[FreeFG OptiScaler base](https://github.com/daniel-h-0/OptiScaler/tree/25db192b1c1ebf42ae7cd6615bc6288b39121c5b).
It produces source commit `273e8d449763d0e9e051dee831dc42badcd15d00` when applied
with the original committer identity and author date as committer date:

```sh
git clone https://github.com/daniel-h-0/OptiScaler.git OptiScaler-gta
cd OptiScaler-gta
git switch --detach 25db192b1c1ebf42ae7cd6615bc6288b39121c5b
git -c user.name=Daniel \
    -c user.email=22757158+daniel-h-0@users.noreply.github.com \
    am --committer-date-is-author-date /absolute/path/to/0001-social-club-auxiliary-swapchains.patch
git submodule update --init --recursive
python tools/test-window-swapchain-size.py
```

Build with the fork's `tools/bc250-build.py`; its header documents the MSVC and
Windows SDK setup. `optiscaler-fix.json` records the exact compiler/SDK versions,
base source, unchanged INI, source patch and tested DLL:

```text
SHA256  044cac6be344a6619e02af9cb0930eed4165ec606dc74486a1d28a573242ec87
Bytes   29394944
```

A different toolchain or commit identity may produce different bytes. Validate
that build and update the reviewed record deliberately; do not suppress the
checksum check. The record binds packaging inputs, not an independent proof
that an arbitrary DLL was built from the stated source.

## Packaging in this repository

Add this to an existing `scripts/build-fsr4-payload.py` invocation that already
supplies `--freefg`, `--freefg-ini` and the other normal inputs:

```sh
--freefg-optiscaler-fix /absolute/path/to/OptiScaler.dll \
  /absolute/path/to/optiscaler-fix.json \
  /absolute/path/to/0001-social-club-auxiliary-swapchains.patch
```

The builder checks the replacement DLL, base DLL from the FreeFG archive,
matching INI, and source patch. Only `freefg` and `freefg-hlxfsr4` get the new
OptiScaler; the stock nightly and HelixSR Scaler keep their own DLLs. The FreeFG
proxy, Intel runtime, shader profile and provider selection remain the existing
package inputs. Both affected versions receive a DLL-hash suffix, including the
default variant, so protonfixes installs the change in an existing prefix.
The packaged notices include the patch, record and base-source pointer.

For a distributable package, add the DLL, record and patch as checksummed
`source=()` inputs, list them in `noextract`, and pass the three `$srcdir` paths
to the builder in each route:

- `packages/protonge-latest-bc250/PKGBUILD.in`
- `packages/proton-cachyos-slr-bc250/PKGBUILD.in`
- `scripts/prepare-proton-cachyos-native-pkgbuild.sh`

Alternatively, move those routes together to a published FreeFG runtime/source
pair containing this fix and remove the temporary override. Before enabling it
by default, verify normal launches through the resulting MastaG packages: the
game evidence below uses plain GE-Proton and the standalone FreeFG layout.

## Settings and scope

Use **FreeFG + FSR4 RC12** for comparison with the tested setup. In the MastaG
menu, select **Enable frame generation** and save the selection. His intentional
fresh-prefix default remains off; needing that choice is separate from the
Social Club crash. The working OptiScaler settings were:

```ini
[FrameGen]
Enabled=true
FGInput=upscaler
FGOutput=xefg
[XeFG]
InterpolationCount=1
ForceBorderless=true
[Spoofing]
DxgiFactoryWrapping=false
```

Remove an old explicit `DxgiFactoryWrapping=true` workaround. `auto` also worked
on the tested route, where it resolves to false. Keep the package's library
paths; the standalone game's relative DLL paths are not appropriate for the
prefix layout. Enable an in-game upscaler and use borderless mode. This is Story
Mode evidence with BattlEye disabled using Rockstar's supported setting; GTA
Online was not tested. The existing anti-cheat guard remains in force.

## Evidence, October 30, 2026

On an AMD BC-250 with plain GE-Proton11-11, FreeFG 1.1.6 and AMD FSR 4 RC12:

| Trial | Result |
|---|---|
| Unmodified game | Story prologue, movement and Social Club open |
| Public OptiScaler, FG off, wrapping off | Social Club crash at Intel offset `0x2123AA` |
| Public OptiScaler, wrapping on | Crash avoided; initialization stalled for the bounded 307-second run |
| Window-size-only candidate | Actual game still crashed; measured client 119×100 |
| Auxiliary-factory candidate | Story Mode and sustained 2× after enabling XeFG |
| Fresh start, final DLL, FG already enabled | Story prologue, movement, Social Club open/close, sustained 2× |

The final game run lasted 546.6 seconds, peaked at 84 °C, and recorded no GPU
faults. Representative final log lines:

```text
hkCreateDXGIFactory Auxiliary factory bypasses frame generation: SocialClubD3D12Renderer.dll
MFG_PRESENT enabled=1 status=0 presents=2
```

The applied source harness passes 16 window-size cases and 10 marker/ownership
checks under ASan/UBSan. Seven final D3D12 probe runs pass, covering vanilla,
legacy CreateSwapChain, HWND creation, explicit and zero axes, the 119×100
overlay, a smaller overlay, and overlay-first creation with a window-sized main
swapchain. The original failing and size-only trials remain failed evidence.

These are bounded functional checks. They do not qualify all games, the
MastaG prefix/Proton variants, HLX FSR 4 in GTA, 3×/4×, HDR, resize/minimize,
frame pacing or image quality. Package builders can test the fix without
changing the host's installed Proton or game library.

To undo a trial build, rebuild without the explicit override and reinstall that
package. The version changes back through the normal protonfixes path. This
restores the old binary, including its known GTA failure; use the menu's
**No upscaling** choice for an unmodified-game fallback.
