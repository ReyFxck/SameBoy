#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_sameboy_ps2.py <libretro.c>")

p = Path(sys.argv[1])
s = p.read_text()
old = """#ifndef WIIU
#define AUDIO_FREQUENCY 384000
#else
/* Use the internal sample rate for the Wii U */
#define AUDIO_FREQUENCY 48000
#endif
"""
new = """#if !defined(WIIU) && !defined(PS2)
#define AUDIO_FREQUENCY 384000
#else
/* Use the internal/device sample rate on Wii U and PlayStation 2. */
#define AUDIO_FREQUENCY 48000
#endif
"""
if old not in s:
    raise SystemExit("SameBoy audio-frequency anchor not found")
p.write_text(s.replace(old, new, 1))
print("Applied SameBoy PS2 runtime patch: 48 kHz audio")
