# FSR4 package integration review — 2026-09-08

This review compared source `738417af25c6e12cb141989ed262966459408f4c` and its
published packages with the BC250 FSR4 RC6 implementation at
`ff195cfdf7796815533ee4e408b98406e3974ed4`.
The [machine-readable record](validation-20260908.json) contains the package
hashes, source comparisons and Windows probe outcomes.

The existing Proton integration already carries the substantial shared work:
the pinned local manifest patch, all 18 OptiScaler-side critical file hashes,
the exact FSR4 provider, and the 23-key preset match the reference. Both normal
game routes set up these payloads successfully with network access forbidden.
The stable Steam-internal tool names also already contain `proton`, so they
satisfy the Windows save-root registration requirement repaired by RC6.

## Driver coverage

The published `vulkan-radeon` and `lib32-vulkan-radeon` `26.2.2-2.106` packages
record only patches 0001–0005 in their build metadata and generated PKGBUILDs.
Their actual ELFs lack all six v4 markers checked by the new package gate.
The three preparation scripts stopped at 0005 even though the fingerprint and
release-asset paths included 0006–0009.

After using the complete production series:

- Real preparation against CachyOS-PKGBUILDS
  `b6490e329d679214b5cd23d6ca733b53a844bfc4` stages all nine patches for stable,
  lib32 and Mesa-Git.
- The stable series applies with zero fuzz to the verified Mesa 26.2.2 archive
  plus CachyOS's gamescope patch. Every one of the reference's 15 modified
  source files is byte-identical.
- The Mesa-Git series applies to `c29eaf16219dc0deabe5cdae1b9bfac13220ff7f`
  using the existing packaging's patch behavior. Its existing 0005 needs
  fuzz 2; the remaining patches apply without fuzz.
- Fresh 64-bit RADV-only targets compile for both source trees with Clang and
  Zen 2 tuning. Both pass the ELF coverage check. These are local validation
  builds, not released packages.

The gate reads the library inside the final package before any old repository
package is replaced. It checks ELF architecture and compiled v4 markers.
It catches this omission without treating an uploaded patch or successful
package command as proof that the feature reached the binary.

## Launch and prefix behavior

Twelve real Windows probe launches covered the published and proposed versions
of both Proton tools. GE used Steam Linux Runtime 4; the native tool used its
normal host-library route. Each had a private prefix and display.

| Route | Published tools | Proposed tools |
| --- | --- | --- |
| Normal game launch | Loads pinned `umu/winmm.dll` | Same |
| `PROTON_FSR4_UPGRADE=0` | Still loads the OptiScaler proxy | Loads ordinary Wine `winmm.dll` by default |
| Utility call with inherited game toggles | Can request the remote upscaler manifest | Local manifest, no proxy or provider upgrade |

All 50 synthetic save-canary reads after initial prefix creation succeeded.
The opt-out preserves retained payload files and stops the default injection;
an explicit `PROTON_USE_OPTISCALER` choice remains supported. These probes
establish folder/proxy behavior, not a game's rendered FSR mode or frame rate.

## Build and regression checks

The normal `--force-fallback` selector path did not validate the INI. Payload
assembly now validates the actual extracted file, including key spelling,
case behavior and the launcher's delimiters. The native build returns a
payload-assembly failure explicitly before later commands can mask it.

All 11 tests pass. The same tests against the original implementation reproduce
the missing patch selection, opt-out/utility problems and missing validation
barriers. Both complete upstream protonfixes modules are hash-checked before
patching; only their logger/cache configuration imports are stubbed. Actual
manifest, archive and prefix operations run with networking forbidden.

This is bounded integration evidence. Full distribution package builds,
32-bit runtime checks and real-game validation remain necessary before treating
a newly published binary as GPU/performance-qualified. The review installed no
system packages and changed no live Steam selection or user save.
