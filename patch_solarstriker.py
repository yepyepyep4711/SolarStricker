#!/usr/bin/env python3
"""Add top-score saving (cartridge RAM) to "SolarStriker (World).gb".

Usage:  python patch_solarstriker.py "roms\\SolarStriker (World).gb"
Output: same folder, "<name> (top-score save).gb". The original is not modified.

Diagnostics (to find out which part of the patch causes a problem):
  --header-only   "<name> (header only).gb": only the cartridge header is changed
                  (RAM declared), no code at all.
  --load-only     "<name> (load only).gb": header + the boot hook (restores a saved
                  top-score), but nothing is ever saved.
  --save-only     "<name> (save only).gb": header + the update hook (saves the
                  top-score), but nothing is ever restored.

What it changes
  header 0x147   01 -> 03   MBC1 -> MBC1+RAM+BATTERY
  header 0x149   00 -> 02   8 KB cartridge RAM
  0x016A         "ld [$CFF3],a" -> "call Load"   (boot: restore the top-score)
  0x2C97         end of the game's top-score copy loop -> "jp NewTail"   (save it)
  0x0061         SaveTop, Load and NewTail (unused area after the interrupt vectors)

Game RAM
  top-score  $CFF1-$CFF7: seven decimal digits, one per byte (0-9), shown on the title
            screen. $CFF8 is NOT a digit (the score's own eighth byte, $CF8F, has been
            seen holding $0B, probably an end marker); the game's update routine at
            $2C79 compares and copies all eight bytes, so all eight are saved and
            restored, which gives back exactly the state the game had.
  The game sets its default top-score (20000: $CFF3 = 2) at $016A, after clearing
  $CFF0-$CFFF. Load runs at that point, so a valid save replaces the default and a
  missing or damaged save leaves it untouched.

How saving works
  The game updates the top-score in exactly one place: the routine at $2C79 compares the
  current score ($CF88) with the top-score ($CFF1) and, if it is higher, copies it with a
  small loop at $2C94. The last instructions of that loop are redirected to NewTail,
  which finishes the loop exactly as the game did and then calls SaveTop, so the new
  top-score is written to cartridge RAM at the moment it changes. Nothing runs every
  frame and nothing is hooked into an interrupt: an earlier version that saved from
  the VBlank interrupt delayed the game's own VBlank handling just enough to make its
  restart code (which waits for a narrow range of scanlines) wait forever.

Reset: hold Down + Select while the console is switched on and the saved top-score is
ignored; the game starts with its default (20000), which is written back to the save so
that the reset sticks. Change RESET_BUTTONS / RESET_DPAD to pick others; all selected
buttons must be held together.

SRAM layout at $A000:  8 top-score bytes, then a check byte = $A5 + sum of the 8 bytes.
Load also rejects a record whose first seven bytes are not digits (0-9); the eighth
byte is not checked, because it is not a digit.
"""
import sys
from pathlib import Path

TOP_SCORE = 0xCFF1                # first byte of the top-score
TOP_LEN = 8                       # bytes saved ($CFF1-$CFF8: 7 digits + 1 marker byte)
DIGITS = 7                       # the first bytes that must be decimal digits
SRAM = 0xA000
BOOT_HOOK = 0x016A               # ld [$CFF3],a  (EA F3 CF), A = 2 at this point
UPDATE_LOOP = 0x2C94             # start of the game's copy loop (ldi a,(hl) ; ld (de),a ; ...)
UPDATE_END = 0x2C97              # dec c ; jr nz,2C94 ; ret   (0D 20 FA C9)
UPDATE_ROUTINE = (0x2C79, bytes.fromhex(
    "0E 08 11 88 CF 21 F1 CF 1A BE D8 20 06 13 23 0D 20 F6 C9 "
    "0E 08 21 88 CF 11 F1 CF 2A 12 13 0D 20 FA C9".replace(" ", "")))
REGION = (0x0061, 0x0100)        # unused area after the interrupt vectors

# Held together at boot -> ignore the save. Bit values:
RESET_BUTTONS = 0x04             # A=1, B=2, Select=4, Start=8   (here: Select)
RESET_DPAD = 0x08                # Right=1, Left=2, Up=4, Down=8 (here: Down; 0 = unused)
VALIDATE_DIGITS = True           # set False if a legitimate top-score ever fails to restore


def le(v):
    return bytes([v & 0xFF, v >> 8])


def asm(org, prog):
    """Tiny two-pass assembler: bytes, 'label:' strings, ('jr', opcode, label)."""
    labels, pos = {}, org
    for it in prog:
        if isinstance(it, bytes):
            pos += len(it)
        elif isinstance(it, str):
            labels[it.rstrip(":")] = pos
        else:
            pos += 2
    out, pos = bytearray(), org
    for it in prog:
        if isinstance(it, bytes):
            out += it
            pos += len(it)
        elif isinstance(it, tuple):
            _, op, lab = it
            off = labels[lab] - (pos + 2)
            assert -128 <= off <= 127, "jr out of range"
            out += bytes([op, off & 0xFF])
            pos += 2
    return bytes(out)


def build_savetop(org):
    """Write the top-score ($CFF1-$CFF8) and its check byte to cartridge RAM.
    Preserves every register and the flags."""
    return asm(org, [
        b"\xF5", b"\xC5", b"\xD5", b"\xE5",   # push af / bc / de / hl
        b"\x3E\x0A",                          # ld a,$0A
        b"\xEA\x00\x00",                      # ld [$0000],a      enable SRAM
        b"\x21" + le(TOP_SCORE),               # ld hl,$CFF1
        b"\x11" + le(SRAM),                   # ld de,$A000
        b"\x06" + bytes([TOP_LEN]),            # ld b,8
        b"\x0E\xA5",                          # ld c,$A5          running check byte
        "w:",
        b"\x2A",                              # ld a,[hl+]
        b"\x12",                              # ld [de],a
        b"\x13",                              # inc de
        b"\x81",                              # add a,c
        b"\x4F",                              # ld c,a
        b"\x05",                              # dec b
        ("jr", 0x20, "w"),                    # jr nz,w
        b"\x79",                              # ld a,c
        b"\x12",                              # ld [de],a         check byte
        b"\xAF",                              # xor a
        b"\xEA\x00\x00",                      # ld [$0000],a      disable SRAM
        b"\xE1", b"\xD1", b"\xC1", b"\xF1",   # pop hl / de / bc / af
        b"\xC9",                              # ret
    ])


def build_load(org, savetop_addr):
    code = [
        b"\xEA\xF3\xCF",                      # ld [$CFF3],a      the instruction we replaced
        b"\xC5", b"\xD5", b"\xE5",            # push bc / de / hl
        b"\x3E\x10",                          # ld a,$10          select buttons
        b"\xE0\x00",                          # ldh [$FF00],a
        b"\xF0\x00",                          # ldh a,[$FF00]     (read twice: lets the
        b"\xF0\x00",                          # ldh a,[$FF00]      lines settle on hardware)
        b"\xE6" + bytes([RESET_BUTTONS]),     # and RESET_BUTTONS  pressed reads as 0
    ]
    if RESET_DPAD:
        code += [
            b"\x47",                          # ld b,a
            b"\x3E\x20",                      # ld a,$20          select d-pad
            b"\xE0\x00",                      # ldh [$FF00],a
            b"\xF0\x00",                      # ldh a,[$FF00]
            b"\xF0\x00",                      # ldh a,[$FF00]
            b"\xE6" + bytes([RESET_DPAD]),    # and RESET_DPAD
            b"\xB0",                          # or b              zero only if all held
        ]
    code += [
        b"\x3E\x30",                          # ld a,$30          deselect (flags untouched)
        b"\xE0\x00",                          # ldh [$FF00],a
        ("jr", 0x20, "normal"),               # jr nz,normal      combo not held
        b"\xCD" + le(savetop_addr),            # call SaveTop       combo held: write the default
        ("jr", 0x18, "done"),                 #                   (CFF1-8 still hold it) and stop
        "normal:",
        b"\x3E\x0A",                          # ld a,$0A
        b"\xEA\x00\x00",                      # ld [$0000],a      enable SRAM
        b"\x21" + le(SRAM),                   # ld hl,$A000
        b"\x0E\xA5",                          # ld c,$A5
        b"\x06" + bytes([TOP_LEN]),            # ld b,8
        "sum:",
        b"\x2A",                              # ld a,[hl+]
        b"\x81",                              # add a,c
        b"\x4F",                              # ld c,a
        b"\x05",                              # dec b
        ("jr", 0x20, "sum"),
        b"\x7E",                              # ld a,[hl]         stored check byte
        b"\xB9",                              # cp c
        ("jr", 0x20, "done"),                 # jr nz,done        invalid -> keep default
    ]
    if VALIDATE_DIGITS:
        code += [
            b"\x21" + le(SRAM),               # ld hl,$A000
            b"\x06" + bytes([DIGITS]),        # ld b,7
            "dig:",
            b"\x2A",                          # ld a,[hl+]
            b"\xFE\x0A",                      # cp 10
            ("jr", 0x30, "done"),             # jr nc,done        not a digit -> reject
            b"\x05",                          # dec b
            ("jr", 0x20, "dig"),
        ]
    code += [
        b"\x21" + le(SRAM),                   # ld hl,$A000
        b"\x11" + le(TOP_SCORE),               # ld de,$CFF1
        b"\x06" + bytes([TOP_LEN]),            # ld b,8
        "cp:",
        b"\x2A",                              # ld a,[hl+]
        b"\x12",                              # ld [de],a
        b"\x13",                              # inc de
        b"\x05",                              # dec b
        ("jr", 0x20, "cp"),
        "done:",
        b"\xAF",                              # xor a
        b"\xEA\x00\x00",                      # ld [$0000],a      disable SRAM
        b"\xE1", b"\xD1", b"\xC1",            # pop hl / de / bc
        b"\xC9",                              # ret
    ]
    return asm(org, code)


def build_newtail(org, savetop_addr):
    """Replaces "dec c ; jr nz,2C94 ; ret" at the end of the game's copy loop."""
    return asm(org, [
        b"\x0D",                              # dec c
        b"\xC2" + le(UPDATE_LOOP),            # jp nz,$2C94       next byte of the copy
        b"\xCD" + le(savetop_addr),            # call SaveTop       copy finished: save it
        b"\xC9",                              # ret               (state exactly as the game left it)
    ])


def fix_checksums(rom):
    c = 0
    for b in rom[0x134:0x14D]:
        c = (c - b - 1) & 0xFF
    rom[0x14D] = c
    g = (sum(rom) - rom[0x14E] - rom[0x14F]) & 0xFFFF
    rom[0x14E], rom[0x14F] = g >> 8, g & 0xFF


def expect(rom, addr, want, what):
    got = bytes(rom[addr:addr + len(want)])
    if got != want:
        sys.exit(f"Refusing to patch: {what} at 0x{addr:04X} is {got.hex(' ')}, "
                 f"expected {want.hex(' ')}. Wrong ROM version?")


def main(path, header_only=False, only=None):
    """only: None (full patch) or a diagnostic build: 'load' or 'save'."""
    src = Path(path)
    rom = bytearray(src.read_bytes())
    if len(rom) != 0x10000:
        sys.exit("Expected a 64 KB ROM.")

    expect(rom, 0x134, b"SOLARSTRIKER", "title")
    expect(rom, 0x147, b"\x01", "cartridge type")
    expect(rom, 0x149, b"\x00", "RAM size")
    expect(rom, 0x14D, b"\x3F", "header checksum")
    expect(rom, 0x14E, b"\x26\x06", "global checksum")
    expect(rom, 0x168, b"\x3E\x02", "boot code (ld a,2)")
    expect(rom, BOOT_HOOK, b"\xEA\xF3\xCF", "boot hook (ld [$CFF3],a)")
    expect(rom, UPDATE_ROUTINE[0], UPDATE_ROUTINE[1], "top-score update routine")

    if header_only:
        rom[0x147] = 0x03
        rom[0x149] = 0x02
        fix_checksums(rom)
        dst = src.with_name(src.stem + " (header only).gb")
        dst.write_bytes(rom)
        print(f"Written: {dst}  (header only, no save code)")
        return dst

    savetop_addr = REGION[0]
    savetop = build_savetop(savetop_addr)
    load_addr = savetop_addr + len(savetop)
    load = build_load(load_addr, savetop_addr) if only in (None, "load") else b""
    tail_addr = load_addr + len(load)
    tail = build_newtail(tail_addr, savetop_addr) if only in (None, "save") else b""
    end = tail_addr + len(tail)
    if end > REGION[1]:
        sys.exit(f"The new code needs {end - savetop_addr} bytes, only {REGION[1] - savetop_addr} available.")
    print(f"SaveTop : {len(savetop)} bytes at 0x{savetop_addr:04X}")
    if load:
        print(f"Load   : {len(load)} bytes at 0x{load_addr:04X}")
    if tail:
        print(f"NewTail: {len(tail)} bytes at 0x{tail_addr:04X}  ({REGION[1] - end} bytes of the area left)")

    rom[savetop_addr:end] = savetop + load + tail
    if load:
        rom[BOOT_HOOK:BOOT_HOOK + 3] = b"\xCD" + le(load_addr)                 # call Load
    if tail:
        rom[UPDATE_END:UPDATE_END + 4] = b"\xC3" + le(tail_addr) + b"\x00"     # jp NewTail ; nop
    rom[0x147] = 0x03        # MBC1+RAM+BATTERY
    rom[0x149] = 0x02        # 8 KB RAM
    fix_checksums(rom)

    suffix = {None: "top-score save", "load": "load only", "save": "save only"}[only]
    dst = src.with_name(f"{src.stem} ({suffix}).gb")
    dst.write_bytes(rom)
    print(f"Written: {dst}" + ("" if only is None else "  (diagnostic build, not the full patch)"))
    return dst


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if len(args) != 1:
        sys.exit(__doc__)
    flags = {"--load-only": "load", "--save-only": "save"}
    only = next((v for k, v in flags.items() if k in sys.argv), None)
    main(args[0], header_only="--header-only" in sys.argv, only=only)
