# Remote Campfire v0.1.2

This update reduces panel overhead in settlements with many campfires.

- Fuel-row updates stop while the list is closed or hidden by menus.
- Opening the list, or returning to an expanded list after a menu, refreshes it
  on the next game tick instead of waiting for the one-second interval.
- Campfire membership checks now scale linearly with the number of campfires.
  Unchanged lists keep their row order and existing widgets.

All 17 game languages remain supported. Fuel display, refill behavior, and
Whiskerwood `0.7.209.0` compatibility are unchanged.

## Compatibility

- Windows, Whiskerwood `0.7.209.0`; refilling is disabled on other versions.
- Requires wood in an accessible granary; cloud-only wood is not supported.
- Manual refilling, session-only panel position.
- No diagnostic logging in this release.

## Installation

[Subscribe on Steam Workshop](https://steamcommunity.com/sharedfiles/filedetails/?id=3815611495),
then restart the game after Steam finishes downloading.

For manual installation, close the game and extract `RemoteCampfire-v0.1.2.zip` into
`%LOCALAPPDATA%\Whiskerwood\Saved\mods\`. The resulting `CampfirePanel` folder
contains `CampfirePanel.pak` and `CampfirePanel.uplugin`.
Use either this local package or a Workshop copy, never both.

Inspired by [FireWatch - Campfire Monitor](https://steamcommunity.com/sharedfiles/filedetails/?id=3807454089) by rinku.
