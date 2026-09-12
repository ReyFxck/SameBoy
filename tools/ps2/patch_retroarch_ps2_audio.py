#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_retroarch_ps2_audio.py <RetroArch checkout>")

root = Path(sys.argv[1])
p = root / "audio/drivers/ps2_audio.c"
s = p.read_text()

old = """static ssize_t ps2_audio_write(void *data, const void *s, size_t len)\n{\n   ps2_audio_t* ps2 = (ps2_audio_t*)data;\n   if (!ps2->running)\n      return -1;\n   return audsrv_play_audio(s, len);\n}\n"""
new = """static ssize_t ps2_audio_write(void *data, const void *s, size_t len)\n{\n   int rv;\n   ps2_audio_t* ps2 = (ps2_audio_t*)data;\n   if (!ps2->running)\n      return -1;\n   if (!len)\n      return 0;\n\n   /* audsrv_play_audio() may accept nothing when its IOP ring is full.\n    * SameBoy then used to lose the entire frame's samples and could remain\n    * effectively silent. The PS2SDK reference player explicitly waits for\n    * enough ring-buffer room before submitting each chunk. */\n   rv = audsrv_wait_audio((int)len);\n   if (rv < 0)\n      return -1;\n   rv = audsrv_play_audio((const char*)s, (int)len);\n   return rv < 0 ? -1 : rv;\n}\n"""
if old not in s:
    raise SystemExit("ps2_audio_write anchor not found")
p.write_text(s.replace(old, new, 1))
print("Applied blocking audsrv ring-space fix for PS2 audio")
