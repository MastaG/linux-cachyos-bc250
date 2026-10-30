# FreeFG recipes and per-game recovery

The Proton packages consume FreeFG releases and recipe data; the integration
lives in this repository. They do not run FreeFG's standalone installer or
change a game installation. Package installation still writes no prefix.

FreeFG variants default to 2× frame generation. The launcher selects an
applicable recipe before Proton starts, then prepares a candidate payload in a
temporary prefix. The actual GE or CachyOS protonfixes routine validates the
candidate. Only then does the integration commit its files and settings.

This is a draft integration. Automated tests exercise both maintained Proton
bases with disposable prefixes. They establish configuration and recovery
behavior, not gameplay, picture quality, latency, or frame pacing on this
Proton/provider combination.

## What a player sees

The existing launch menu still chooses the upscaler, GPU spoofing and FG on/off.
It now keeps choices per game, shows the FreeFG version and recipe revision,
and links to the FreeFG project. A few lines under that say what the catalogue
does for this game, for example:

```text
Verified on BC-250: RoboCop: Rogue City (DLSS FG input; generates)
Guided by the OptiScaler wiki: Neverness to Everness (NTE)
OptiScaler wiki (God of War Ragnarok) reports OptiFG input broken: frame generation starts off
Left to OptiScaler’s own fix for this game: Hotfix.RestoreComputeSignature
```

After the first managed launch it also offers:

- **Use recommended integration settings**: adopt the current package/recipe
  values for managed keys. Other settings remain yours. This does not alter
  graphics quality, game configuration files or saves.
- **Use previous version**: select the previous retained generation. Its
  payload, provider, defaults, recipe and launch arguments take effect together
  on the next launch. Later player edits remain in place.
- **Resume package updates**: release the rollback pin so the next launch uses
  the installed package again.

A rollback remains pinned across later launches and package upgrades. The
necessary archives are retained inside the prefix, rather than pointing back
at files a package upgrade can remove. This rolls back the upscaler payload,
not Proton, Wine, Mesa or the kernel.

The effective settings order is:

```
package defaults → catalogue for this game → saved player edits → launch options
```

Saved overlay changes, menu FG on/off choices, unknown INI keys, comments and
newline style survive variant switches. Frame-generation wiring and the upscaler
pick (`FrameGen.*` other than `Enabled`, `Upscalers.*`) are the exception: they
name a generator or upscaler of the variant they were saved in, so a switch to
another variant drops them, as a switch reset the whole INI before. Switching to
No upscaling and back is not a switch. Explicit `BC250_OPTISCALER_EXTRA` and
debug settings apply for that launch; removing them reveals the saved setting
again. A changed package default updates a key only while it remains owned by
the integration. Saving the same value that was already present is not an
observable edit; use an explicit launch option when that distinction matters.

An existing prefix is adopted conservatively: its current INI values, including
`auto`, initially count as player choices; a menu choice made on that first
launch still wins. Use the recommendation action to allow managed defaults and
recipe values to replace those keys. Unreadable or ambiguous INIs stop the
launch instead of being reset.

## Optional wiki INI prefills

The **Wiki settings** expander shows the selected FreeFG variant's proposed INI
values, current values, sources and conditions. Nothing starts selected. Select
the values to save for this game, then start it; the existing prefix transaction
applies them. Switching variants clears the selections so they cannot silently
move to another provider. Saved overlay/menu choices and explicit launch options
still take precedence over defaults.

Unknown symptoms and title-only matches require confirmation of the displayed
conditions. Known wrong conditions, missing dependencies, unsupported keys,
conflicting applicable sources, recipe/runtime-owned keys and generator policy
are not selectable. Dependencies and other requirements remain visible. Selecting
a quality preference is an explicit player choice, not an automatic recommendation.
The adapter passes the effective FG input/output, provider, API, loader and
available dependency paths to the upstream planner. No game configuration file,
anti-cheat setting or graphics-quality preset is changed automatically.

After one managed launch, the CLI can preview and save the same choices:

```sh
BC250_FREEFG_GAME_ID=steam:1836730 ./proton freefg-wiki-plan
BC250_FREEFG_GAME_ID=steam:1836730 ./proton freefg-wiki-apply \
  --wiki-setting ROW_ID --wiki-plan-digest DIGEST [--wiki-confirm ROW_ID]
```

Use the normal `STEAM_COMPAT_DATA_PATH` or `WINEPREFIX` environment. Repeat the
setting/confirmation options for multiple rows. The digest is from the displayed
plan; changed plans refuse. The CLI saves per-game overrides for the next launch
and does not start Proton or modify the currently installed payload. It uses that
game's retained catalogue/planner and variant, including a pending rollback.
Selections record source provenance. They are player overrides, so they survive
payload rollback just like later overlay edits; remove or change them in the
OptiScaler menu or through an explicit launch override as appropriate.

## How the catalogue tempers the default

These packages give every game the same default; FreeFG's installer configures
a game its user picked. The pinned catalogue holds per-game
evidence, applied in the order of FreeFG's `compat.py`:

| Layer | Source | Applied here |
| --- | --- | --- |
| Curated recipe | 19 rows observed on a BC-250 | Input, keys and DX12 argument, with `generates`/`gameplay` evidence |
| OptiScaler's own fixes | `quirk_keys`, `leave_auto`: 218 executables, from the shipped OptiScaler build | The key is left `auto`, where the fix acts |
| Reviewed wiki item | `promoted`: 6 items | Its key, on a strong match whose conditions hold here |
| Wiki veto | `fg_advice` broken/avoid | Frame generation starts off when the default input is reported broken, on a strong match |
| Other wiki items | 761 entries, including 295 INI instructions in total | Selectable prefills where applicable; otherwise source-backed advice |

The asymmetry is deliberate. Nobody chose this default per game, so evidence
that it is wrong for a game removes it; evidence gathered on other hardware
(mostly Windows and NVIDIA) never adds a setting by itself. A preferred input,
a DX12 launch option or a proxy name stays advisory. An applicable listed INI
setting can be selected explicitly through the shared planner.

OptiScaler applies a per-game fix only while its key is `auto`. The shared
preset writes `Hotfix.RestoreComputeSignature=false` and
`Hotfix.ExtendedStateRestore=false`, which the shipped `OptiScaler.ini`
documents as what `auto` means anyway, so their only effect was to switch off
OptiScaler's fix for the 15 executables that have one: Monster Hunter Wilds,
Rise and Stories 3, Dragon's Dogma 2, Resident Evil 9 Requiem, Pragmata,
Onimusha: Way of the Sword, Kunitsu-Gami, Dead Rising Deluxe Remaster and 007
First Light, with demos (several fixes apply to non-NVIDIA GPUs only). For those
executables the key is left `auto`. FreeFG's own installer keys
(`XeFG.ForceBorderless` and the FG wiring) are not given back: FreeFG writes
them regardless, for measured reasons. The package's documented
`Spoofing.VulkanExtensionSpoofing=false` also stands; where OptiScaler's fix
for a game would turn it on, the launch log says so and how to try it.

A strong match is FreeFG's: a store ID, or the executable together with the
game's title or one of its folders. The October 30 review adds official Steam
identities for all five games covered by the six promoted values, plus Ragnarök's
broken-input warning. Other entries use Steam's appmanifest title and executable
context. A title alone is weak: it cannot automatically write a value, but an
explicit prefill is available after confirming the game and conditions. Curated
recipes and known runtime fixes outrank wiki prefills.

## Identity and recipe limits

Real Steam AppIDs are used directly. Heroic/Lutris users can specify a store
identity, for example:

```text
BC250_FREEFG_GAME_ID=gog:1423049311
BC250_FREEFG_GAME_ID=steam:1836730
```

The accepted forms are `steam:ID`, `gog:ID`, and `epic:NAME`. Without a real
store ID, the adapter requires both a recognized executable and a matching
installation-directory name. A shortcut's generated Steam ID and `umu-0` are
not catalogue identities. Unknown titles retain the package defaults, and so
does an ambiguous match, with the reason in the launch log. A launch with
neither a store ID nor an `.exe` (a `.bat`, for one) keeps one identity for its
prefix; no game is refused for want of a name.

Only curated rows with `generates` or `gameplay` evidence are applied
automatically. The current upstream snapshot has 19 curated rows, 13 with that
evidence. Installed-only, startup-only and failed observations remain distinct.
Known failed and native-XeFG-only routes default OptiScaler FG off; explicit
player choices still win. The adapter does not infer support for another store
edition that the source recipe does not name.

The adapter translates FG input/output, route mechanics, provider-specific
INI fixes and supported launch arguments. It checks keys against the selected
OptiScaler build. Relative game-folder library/plugin paths require manual
review and are reported rather than copied into the prefix layout. Recipe
arguments are added only to the matched game executable, never a launcher;
an explicit DX11/Vulkan/OpenGL choice wins over a suggested DX12 argument.

Game-setting prerequisites are exposed in status and launch diagnostics. The
adapter does not write those files. For example, Deadzone's FSR Native
requirement changes the rendering workload and remains a player decision.
Cyberpunk's imported HLX reactive-mask workaround changes an upscaler input;
its upstream evidence does not establish image equivalence or qualify HelixSR
3.2.0 in this Proton integration. The imported recipe source and evidence stay
visible in the generation record.

## Command-line recovery

Use the installed tool's `bc250-fsr4-launch.py`, with the same prefix and compat
data path the game uses. Commands finish without starting Proton. For Steam:

```sh
STEAM_COMPAT_DATA_PATH=/path/to/steamapps/compatdata/1836730 \
BC250_FREEFG_GAME_ID=steam:1836730 \
python3 /usr/share/steam/compatibilitytools.d/protonge-latest-bc250/bc250-fsr4-launch.py freefg-status
```

Replace `freefg-status` with `freefg-rollback`, `freefg-update` or
`freefg-recommend`. For umu, also pass its actual `WINEPREFIX`. The three
mutation commands report that the selection applies on the next game launch.
A conflicting explicit variant choice must be removed or the rollback pin
released before choosing a different variant.

State is under `<WINEPREFIX>/.bc250-freefg/`. It contains per-game settings,
retained generations, selected archives, and an initial payload backup when
adopting an existing prefix. It contains no saves or whole-game copies. Archives
can be large; this initial implementation retains generations until explicitly
removed outside the tool and has no automatic pruning. Do not remove the state
while a game is running or while a journal exists.

Every managed launch stages, verifies and commits the whole payload, even when
nothing changed. With a 96 MiB test payload on ext4, an unchanged launch read
about ten times and wrote about three times the payload's size, in 1.5 to 2.6
seconds; on btrfs and XFS the copies are reflinks, so mostly the reads remain.
Staging only a changed payload, and journalling only the INIs otherwise, would
remove most of that cost.

A prefix-wide lease lasts until the Proton child exits. A second launch using
this integration in the same prefix refuses to change files while the first
runs; separate prefixes are independent. The supervisor forwards termination
signals and returns Proton's exit status. Other launchers that bypass this
integration do not participate in the lease.

An interrupted commit leaves a write-ahead journal. The next launch or recovery
command restores the previous payload and tracking record before proceeding.
Modified managed DLLs, unknown DLL collisions and unsafe symlinks cause a
conflict instead of being overwritten. A retained baseline is recovery evidence,
not an automatic downgrade of unrelated Proton state.

## Maintainer updates

[`freefg-upstream.json`](../packages/bc250-fsr4-common/freefg-upstream.json) is
the dependency record consumed by all three package builders. It pins the
runtime ZIP, matching GPL source companion, OptiScaler INI, and an unchanged
recipe snapshot and `compat.py` planner at exact FreeFG commits, with SHA-256
checks. The MIT notice is retained in the same record. The runtime stays at
MastaG's 1.1.5; the refreshed catalogue/planner are commit `a7ebfe3`, prepared for
FreeFG 1.2.0. The 19 curated BC-250 rows are unchanged. No different runtime is
promoted. The catalogue's OptiScaler quirk effects were checked against both the
1.1.5 and 1.1.6 source builds.

Check the committed inputs without network access:

```sh
python3 scripts/update-freefg.py --check
```

Prepare a runtime refresh and retain its source companion for the release mirror:

```sh
python3 scripts/update-freefg.py --runtime-version 1.1.6 \
  --download-dir build/freefg-mirror --dry-run
```

Remove `--dry-run` to update the dependency record in the checkout. A recipe-only
refresh uses `--recipes-commit FULL_40_CHARACTER_COMMIT` and fetches the matching
shared planner, retaining both unchanged. The runtime pin stays unchanged. Runtime refreshes verify GitHub's asset digests, the source hash
recorded inside the runtime, and the INI at the exact OptiScaler source commit.
No dependency is fetched at game launch. The optional `gh` fallback handles
release-asset download routes blocked by a GitHub proxy.

The package builds fetch the runtime ZIP from the payload mirror, like every
pinned archive, and check it against the pin; the pin's upstream URL is
provenance. Upload the ZIP and its source companion from `--download-dir` to
the mirror before a changed pin is built.

`freefg_compat.py` is the unchanged upstream planner, not a second policy
implementation. `bc250_freefg_recipes.py` translates its results into prefix
settings and package-specific defaults. Retained bundles include both the
catalogue and planner, and verify them before use. A changed planner format or
recipe schema requires adapter review.

Review the pin and recipe diff, run `python3 -B -m unittest discover -s tests`,
then build all affected packages and perform runtime qualification before
promotion. Publish the matching source companion alongside the package inputs
for as long as the binaries are offered. A changed recipe schema, runtime
layout or missing OptiScaler key needs adapter review; passing a checksum is
not compatibility evidence. CI can call the refresh tool from a separate,
maintainer-controlled dependency PR workflow; this change adds no automatic
publication or end-user updater.
