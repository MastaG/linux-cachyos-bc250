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

## `patches/0001-pinned-upscaler-manifest.patch`

Adds `PROTON_UPSCALER_MANIFEST` to protonfixes' `upscalers.py`: point it at a
local JSON manifest and artifacts are read from disk, with mandatory archive and
critical-file SHA256 verification, relative paths confined to the manifest
directory, and validation of everything requested *before* any prefix payload is
written. A local-mode failure stops the launch rather than falling back to the
network. Absent the variable, stock behaviour is unchanged.

Derived from the upstream BC-250 FSR4 work (see the repository README credits)
and rebased here onto the `upscalers.py` that results *after* proton-cachyos's
own eight `patches/protonfixes/0002-upscalers/` patches apply. Thirteen of
fifteen hunks applied unchanged; two were resolved by hand:

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

The FidelityFX SDK is MIT licensed, which permits redistribution; its notice
ships in both packages.
