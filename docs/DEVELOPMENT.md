# Remote Campfire Development

Version: `0.1.1`. Runtime mod ID: `CampfirePanel`.
Supported game: Whiskerwood `0.7.209.0` for Windows, using the compatible custom
Unreal Engine 5.8 build and Whiskerwood modkit.

## Runtime

Three Blueprint assets under `/Game/Mods/CampfirePanel` provide the mod:

- `BP_MapLoad`: discovers campfires, refreshes their displayed fuel, and handles refill requests.
- `WBP_CampfirePanel`: draggable list, visibility icon, and refill-all button.
- `WBP_CampfireRow`: fuel display and individual refill button.

The list starts closed. Its visibility follows the gameplay HUD, including
loading, menus, and saving overlays. Normal simulation pauses do not hide it.
Toggling or entering a menu preserves the panel's expanded state and position
within the session. Position is not saved between sessions.

Campfires are identified from player-owned heaters with a temporary fuel source.
The interface shows fuel percentages and changes their color at low fuel levels.
It does not perform automatic refills.

Discovery still runs once per second. Membership comparison uses a temporary
set, keeping the existing row order and widgets when the campfire membership
has not changed. Adding or removing a campfire rebuilds the list as before.
Fuel-row updates stop while the list is closed or hidden by the gameplay HUD.
Opening the list, or restoring an expanded list after a menu, requests a refresh
on the next actor tick instead of waiting for the one-second interval. That
refresh still passes through the normal session and refill-safety checks.

## Localization

The interface automatically follows the game's active language. The catalog in
`Automation/CampfirePanel/translations.json` covers all 17 native language IDs:

| ID | Language |
| --- | --- |
| `en` | English |
| `fr` | French |
| `de` | German |
| `it` | Italian |
| `es` | Spanish |
| `ru` | Russian |
| `ja` | Japanese |
| `zh` | Simplified Chinese |
| `ko` | Korean |
| `tr` | Turkish |
| `pt` | Brazilian Portuguese |
| `pl` | Polish |
| `ua` | Ukrainian |
| `cs` | Czech |
| `hu` | Hungarian |
| `zh-tw` | Traditional Chinese |
| `es-mx` | Latin American Spanish |

The generator embeds the catalog into the runtime Blueprints; no external
translation file is required by the installed mod. Language lookup uses the
game's `LocManager`, normalizes case and underscores, prefers exact regional
matches, then tries a supported language prefix. Unknown languages fall back to
English.

The existing one-second refresh checks for language changes and relabels the
panel, tooltips, rows, and current status. Reformatting status messages preserves
their numeric values. Language changes preserve panel state and do not request
a refill or change refill safety checks. Fuel and refill behavior is unchanged.

Text uses the game's native Poppins composite font and its Noto fallbacks. These
remain references to the installed game rather than bundled font assets.

## Refill Workaround

The inspected modkit does not expose the native campfire refill action to
Blueprints. The mod therefore reproduces its wood-to-fuel operation using
available game types and an existing signed resource operation.

For each wood increment, the mod:

1. Checks game version, session readiness, target ownership, refill eligibility, and wood availability.
2. Finds a player-accessible granary containing physical wood.
3. Saves the current primary-warehouse reference and the affected construction-statistics entry.
4. Routes the existing resource operation to that granary and requests a debit of one wood.
5. Restores the temporary warehouse reference and statistics entry immediately.
6. Verifies the wood debit before increasing the campfire's remaining burn time.

Fuel duration accounts for the heater's overdrive and the dirty-fuel policy.
Calculations use the game's native single-precision fuel values. One request
applies up to four wood increments per campfire, stopping at the game's refill
limit or when eligible wood runs out.

An unexpected debit or fuel-write result disables further refills until the
session is reloaded. Unsupported game versions are rejected rather than trying
an unverified operation. This is a compatibility-sensitive workaround, not a
newly exposed official refill API.

The editor-only authoring helper creates the required Blueprint accessors. It
does not ship in the mod package. The release contains no runtime DLL or
diagnostic logging.

## Limits

- Only Whiskerwood `0.7.209.0` is supported. A game update requires renewed verification.
- An accessible granary with physical wood is required, even when cloud storage contains wood.
- Warehouse proximity uses actor origins; the game uses entrance positions, so the selected source can differ.
- Position and expanded state persist only within the session.
- Refilling is always requested by the player, individually or for the list.

## Build

Prerequisites are a compatible Whiskerwood modkit, its custom Unreal Engine,
and the Windows C++ build tools needed by the editor.

Copy this repository's `Plugins/CampfireProbeEditor` directory into the modkit's
`Plugins` directory and compile the modkit's editor target once. This helper is
needed for authoring, not for playing the published mod.

Run the build script from this repository, with the paths to your engine and
modkit:

```powershell
& .\Automation\CampfirePanel\Build-Mod.ps1 -EngineRoot 'D:\WWEngine' -ProjectRoot '..\Modkit'
```

The script copies only this mod's assets into the supplied modkit, generates the
runtime Blueprints, runs the focused checks, and cooks an isolated mod package.
It does not install the mod or publish an upload.

After a successful generation, `-UseGeneratedAssets` reruns every check and
packages the assets already in the modkit. Omit it after changing the generators.

The included checks are:

- `test_catalog.py`: all 17 language IDs, complete translations, regional variants, and template placeholders, without loading Unreal.
- `test_localization.py`: compiled translation lookup, regional matching, English fallback, and relabeling existing UI and status without triggering refills.
- `test_precision.py`: native fuel types and refill arithmetic.
- `test_ui.py`: compiled panel behavior, HUD visibility, and fuel presentation.
- `test_public.py`: public-build requirements, including the absence of diagnostic logging.
- `test_performance.py`: compiled closed/hidden update guards, next-tick refresh requests, and membership changes without disturbing stable row order.

These checks do not replace gameplay testing after a game update.

`benchmark_performance.py` measures compiled `RefreshList` calls for 10 through
2,000 synthetic campfires in the editor. Run it with `-ExecutePythonScript`
and `-unattended -nullrhi -nosound`. By default it loads the generated project
assets and writes JSON to `Saved/CampfirePerformance/refreshlist-benchmark.json`.
The optional `CAMPFIRE_BENCHMARK_MOUNT`, `CAMPFIRE_BENCHMARK_OUTPUT`, and
`CAMPFIRE_BENCHMARK_LABEL` environment variables select extracted cooked assets,
the output file, and a comparison label. Results include all samples and asset
hashes; they exclude rendering, rebuilding rows, refilling, and real-game FPS.

## Release Contents

`RemoteCampfire-v0.1.1.zip` contains only:

```text
CampfirePanel/
  CampfirePanel.pak
  CampfirePanel.uplugin
```

The package contains the three runtime Blueprints and their cooked sidecars.
Editor helpers, test scripts, logs, and unrelated mod assets are excluded.
Native game fonts and textures remain references to the installed game.

The Workshop upload uses the same verified two-file package. Its description
and change notes are under `workshop/`; creating a release does not submit a
Workshop item.

## Credits

Inspired by [FireWatch - Campfire Monitor](https://steamcommunity.com/sharedfiles/filedetails/?id=3807454089) by rinku.

Unofficial community mod built with the [Whiskerwood modkit](https://github.com/Whiskerwood-Modding/Whiskerwood-Project) by Buckminsterfullerene and Whiskerwood-Modding. Game assets belong to their respective owners.
