#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_retroarch_ps2_audio.py <RetroArch checkout>")

root = Path(sys.argv[1])
p = root / "audio/drivers/ps2_audio.c"
s = p.read_text()

init_old = """   audsrv_set_format(&format);\n   audsrv_set_volume(MAX_VOLUME);\n\n   return ps2;\n}\n"""
init_new = """   if (audsrv_set_format(&format) < 0)\n   {\n      free(ps2);\n      return NULL;\n   }\n   audsrv_set_volume(MAX_VOLUME);\n\n   /* Report the real device rate back to RetroArch and start in a usable\n    * state. The stock PS2 driver left new_rate untouched and running false,\n    * which is fragile for statically linked cores during startup. */\n   if (new_rate)\n      *new_rate = rate;\n   ps2->running = true;\n\n   return ps2;\n}\n"""
if init_old not in s:
    raise SystemExit("ps2_audio_init anchor not found")
s = s.replace(init_old, init_new, 1)

write_old = """static ssize_t ps2_audio_write(void *data, const void *s, size_t len)\n{\n   ps2_audio_t* ps2 = (ps2_audio_t*)data;\n   if (!ps2->running)\n      return -1;\n   return audsrv_play_audio(s, len);\n}\n"""
write_new = """static ssize_t ps2_audio_write(void *data, const void *s, size_t len)\n{\n   int rv;\n   ps2_audio_t* ps2 = (ps2_audio_t*)data;\n   if (!ps2->running)\n      return -1;\n   if (!len)\n      return 0;\n\n   rv = audsrv_wait_audio((int)len);\n   if (rv < 0)\n      return -1;\n   rv = audsrv_play_audio((const char*)s, (int)len);\n   return rv < 0 ? -1 : rv;\n}\n"""
if write_old not in s:
    raise SystemExit("ps2_audio_write anchor not found")
s = s.replace(write_old, write_new, 1)

p.write_text(s)
print("Applied complete PS2 audsrv init/rate/ring-space fix")
