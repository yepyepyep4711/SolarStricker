# Solar Striker - Top-score Save

**Top-score saving** for *Solar Striker* (Game Boy). The game is unchanged: no new
screens or menus. The top-score you saw last time is simply still there next time,
instead of resetting to 20000 whenever the console is switched off.

**Download:** see the [latest release](https://github.com/yepyepyep4711/SolarStriker/releases/latest) (BPS and IPS patches).
This repository contains no game data; you need your own copy of the ROM.

## Base ROM

The patch applies to exactly this file:

| This | Should be this |
|-------|-----|
| Name | `SolarStriker (World).gb` |
| Size | 65536 bytes |
| CRC32 | `11817103` |
| MD5 | `83BED4EBEFEECE45748258FD2EF105B3` |
| SHA-1 | `A8D6ACB026B0D0A8A2BCAEA094951E915A3DEB80` |

The BPS patch verifies this and refuses to apply to anything else; the IPS patch cannot.

## Patching

Apply the `.bps` patch (preferred) or the `.ips` patch to your ROM with the online patcher at
<https://www.romhacking.net/patch/> (it works in your browser, so there is nothing to
install) or any other IPS/BPS patcher. Your original is not modified.

## Requirements

Saving needs cartridge RAM:

- **Emulators:** anything that supports MBC1 + RAM + battery (BGB, SameBoy, mGBA, ...).
  A `.sav` file appears next to the ROM.
- **Hardware:** a flash cart or rewritable cartridge supporting MBC1 with 8 KB of save
  RAM. Battery-backed RAM and non-volatile FRAM both qualify; the DMG-GBWR-50 rewritable
  cartridge uses FRAM.

Without save RAM the game still plays, but, as in the original game, the top-score is
lost when the console is switched off. A soft reset does not wipe it, with or without
save RAM.

## Using it

- Nothing to do: the top-score is stored automatically whenever it changes.
- The game's built-in soft reset (A + B + Start + Select) still works and does not wipe
  the top-score.
- **Reset the top-score:** switch the console on while holding **Down + Select** and
  release once the game is running. The top-score goes back to the game's default of
  20000. This works at power-on only; the game's own soft reset does not trigger it.

## Limitations

- Only the top-score is saved.
- A damaged save (wrong check byte, or digits that are not valid decimal digits) is
  ignored and the game starts with its default top-score of 20000.

## How it works

Everything goes into unused space or hook points; the header is changed to MBC1+RAM+BATTERY
(`0x147` 01 to 03, `0x149` 00 to 02) and its checksums are recalculated.

| Where | What |
|---|---|
| `0x016A` | boot hook: `call $0087` (replaces `ld [$CFF3],a`, which the new code runs first) |
| `0x2C97` | save hook: the end of the game's top-score copy loop becomes `jp $00E7` |
| `0x0061`-`0x00FF` | save routine (38 bytes), load routine (96 bytes) and the end of the copy loop (8 bytes), in the unused area after the interrupt vectors |

Game RAM: top-score `$CFF1-$CFF7` (seven digits, one per byte, as on screen) plus `$CFF8`,
a marker byte that the game copies along with the score; current score `$CF88-$CF8F`.
Save RAM at `$A000`: the eight top-score bytes plus a check byte (`$A5` + their sum).

- The **load routine** runs once at boot, right after the game sets its default top-score
  (20000). A valid save replaces the default; a missing or damaged save leaves it alone.
- The **save routine** runs only when the game itself updates the top-score. The game's
  compare-and-copy routine at `$2C79` copies a higher score into `$CFF1-$CFF8`; the end of
  that loop now calls the save routine and returns exactly as the game did. Nothing runs
  every frame and no interrupt is hooked, so the game's timing is unchanged and the save
  RAM is touched only at boot and when the top-score changes.
- The game's own soft reset restarts after the boot code, so the top-score already in RAM is
  kept.

If you have Python, you can try this yourself using the scripts from the repository:
`patch_solarstriker.py` rebuilds the patched ROM from your original ROM, and
`make_release_solarstriker.py` builds the patches, READMEs and zip.

## Tested

BGB and real hardware: DMG-GBWR-50 rewritable cartridge and EZ Flash Jr, played on Game Boy,
Game Boy Color, Analogue Pocket and ModRetro Chromatic. Tested: saving, loading, top-score reset
and soft resets.

## Legal

No game data is included, only the differences. *Solar Striker* belongs to its respective
owners; this is an unofficial fan modification and is not affiliated with them.
