#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_retroarch_ps2_runtime.py <RetroArch checkout>")

root = Path(sys.argv[1])


def replace_once(path: Path, old: str, new: str, label: str):
    s = path.read_text()
    if old not in s:
        raise SystemExit(f"{label}: anchor not found in {path}")
    path.write_text(s.replace(old, new, 1))


# PS2SDK documents a race in the BIOS FILEIO RPC implementation used by
# fioGetstat()/fioDread(): interrupts are not disabled around sceSifSetDma.
# RetroArch has a task thread while the menu is browsing, so that race is very
# easy to hit. libpatches is already linked by Makefile.ps2; apply the official
# runtime fix after each IOP reset, alongside the other sbv patches.
platform = root / "frontend/drivers/platform_ps2.c"
replace_once(
    platform,
    "   sbv_patch_enable_lmb();\n"
    "   sbv_patch_disable_prefix_check();\n",
    "   sbv_patch_enable_lmb();\n"
    "   sbv_patch_disable_prefix_check();\n"
    "   sbv_patch_fileio();\n",
    "PS2 FILEIO safety patch",
)

# RetroArch's PS2 renderer describes NTSC as a 704x480 logical surface, while
# GSKit actually exposes the visible NTSC field as 640x448. Scaling against the
# larger logical surface makes the menu/content geometry slightly wrong and is
# especially noticeable in ARMSX2. Keep core aspect handling intact (important
# for Game Boy's non-4:3 image) and only correct the PS2 output geometry.
gfx = root / "gfx/drivers/ps2_gfx.c"
s = gfx.read_text()

old = "    {-1, 704, -1, 4, GS_INTERLACED, GS_FIELD, -1, 11, \"AUTO\"},\n"
new = "    {-1, 640, -1, 4, GS_INTERLACED, GS_FIELD, -1, 11, \"AUTO\"},\n"
if old not in s:
    raise SystemExit("PS2 AUTO width anchor not found")
s = s.replace(old, new, 1)

old = "    {GS_MODE_NTSC, 704, 480, 4, GS_INTERLACED, GS_FIELD, 10, 11, \"NTSC@60Hz\"},\n"
new = "    {GS_MODE_NTSC, 640, 448, 4, GS_INTERLACED, GS_FIELD, 10, 11, \"NTSC@60Hz\"},\n"
if old not in s:
    raise SystemExit("PS2 NTSC geometry anchor not found")
s = s.replace(old, new, 1)

old = "   rm_mode_table[RM_VMODE_AUTO].height = (mode == GS_MODE_PAL) ? 576 : 480;\n"
new = "   rm_mode_table[RM_VMODE_AUTO].height = (mode == GS_MODE_PAL) ? 576 : 448;\n"
if old not in s:
    raise SystemExit("PS2 AUTO height anchor not found")
s = s.replace(old, new, 1)

gfx.write_text(s)
print("Applied PS2 FILEIO race fix and NTSC 640x448 geometry")
