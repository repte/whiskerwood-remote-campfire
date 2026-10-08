<div align="center">

<img src="docs/images/remote-campfire-1024.png" alt="Remote Campfire" width="360">

# Remote Campfire

**Check and refill Whiskerwood campfires from one small panel.**

</div>

- See fuel levels, with amber and red warnings as fuel runs low.
- Refill one campfire or all listed campfires using your wood.
- Drag the panel where you need it; hide or show it with the campfire icon.
- Use it while paused. It stays hidden in menus.

Refills only when you click.

## Download

Download `RemoteCampfire-v0.1.0.zip` from [Releases](https://github.com/repte/whiskerwood-remote-campfire/releases).
Close the game and extract its `CampfirePanel` folder into:

```text
%LOCALAPPDATA%\Whiskerwood\Saved\mods\
```

Use either a local installation or a Workshop copy, never both.

## Compatibility

**Windows, Whiskerwood 0.7.209.0.** Refilling is disabled on other game versions.

- Requires wood in a player-accessible granary. Cloud-only wood is not supported.
- Panel position is remembered for the current session only.
- The current in-game interface is in German.

## How Refilling Works

The modkit does not expose the campfire's refill action. The mod deducts wood
through an existing game resource operation, verifies the debit, then adds the
matching fuel. It ships as ordinary Workshop Blueprints, without a runtime DLL.

[Implementation and build instructions](docs/DEVELOPMENT.md)

---

Inspired by [FireWatch - Campfire Monitor](https://steamcommunity.com/sharedfiles/filedetails/?id=3807454089) by rinku.

Unofficial community mod built with the [Whiskerwood modkit](https://github.com/Whiskerwood-Modding/Whiskerwood-Project) by Buckminsterfullerene and Whiskerwood-Modding. Game assets belong to their respective owners.

[![DuoQueue](docs/images/duoq-workshop-banner-autoday.png)](https://duoqueue.app/en/)
