#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_retroarch_ps2_perf.py <RetroArch checkout>")

p = Path(sys.argv[1]) / "Makefile.ps2"
s = p.read_text()

old = "CFLAGS = $(OPTIMIZE_LV) $(DISABLE_WARNINGS) $(DEFINES) -DPS2 -fsingle-precision-constant -ffast-math\n"
new = "CFLAGS = $(OPTIMIZE_LV) $(DISABLE_WARNINGS) $(DEFINES) -DPS2 -fsingle-precision-constant -ffast-math -flto -ffat-lto-objects -fomit-frame-pointer\n"
if old not in s:
    raise SystemExit("RetroArch CFLAGS anchor not found")
s = s.replace(old, new, 1)

old = "EE_LDFLAGS = $(LDFLAGS)\n"
new = "EE_LDFLAGS = $(LDFLAGS) -flto\n"
if old not in s:
    raise SystemExit("RetroArch LDFLAGS anchor not found")
s = s.replace(old, new, 1)

p.write_text(s)
print("Applied PS2 frontend LTO flags")
