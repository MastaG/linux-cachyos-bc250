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
and links to the FreeFG project. After the first managed launch it also offers:

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
package defaults → applicable recipe → saved player edits → launch options
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
not catalogue identities. Unknown titles retain the package defaults;
ambiguous matches stop with an error.

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
recipe snapshot at an exact FreeFG commit. The recipe's MIT notice is retained
in the same record. The initial runtime stays at MastaG's 1.1.5; recipes are
imported from FreeFG 1.1.6. This PR does not silently promote a different runtime.

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
refresh uses `--recipes-commit FULL_40_CHARACTER_COMMIT`; the runtime pin stays
unchanged. Runtime refreshes verify GitHub's asset digests, the source hash
recorded inside the runtime, and the INI at the exact OptiScaler source commit.
No dependency is fetched at game launch. The optional `gh` fallback handles
release-asset download routes blocked by a GitHub proxy.

Review the pin and recipe diff, run `python3 -B -m unittest discover -s tests`,
then build all affected packages and perform runtime qualification before
promotion. Publish the matching source companion alongside the package inputs
for as long as the binaries are offered. A changed recipe schema, runtime
layout or missing OptiScaler key needs adapter review; passing a checksum is
not compatibility evidence. CI can call the refresh tool from a separate,
maintainer-controlled dependency PR workflow; this change adds no automatic
publication or end-user updater.
