#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_retroarch_ps2_audio.py <RetroArch checkout>")

root = Path(sys.argv[1])
p = root / "audio/drivers/ps2_audio.c"
s = p.read_text()

init_old = """   audsrv_set_format(&format);\n   audsrv_set_volume(MAX_VOLUME);\n\n   return ps2;\n}\n"""
init_new = """   if (audsrv_set_format(&format) < 0)\n   {\n      free(ps2);\n      return NULL;\n   }\n   audsrv_set_volume(MAX_VOLUME);\n\n   if (new_rate)\n      *new_rate = rate;\n   ps2->running = true;\n\n   return ps2;\n}\n"""
if init_old not in s:
    raise SystemExit("ps2_audio_init anchor not found")
s = s.replace(init_old, init_new, 1)

# Do not call audsrv_wait_audio() here. It sleeps the EE until the IOP ring
# drains and can throttle the entire libretro runloop. audsrv_play_audio()
# already clips the copy to currently available ring space, so callers can
# drop the excess rather than stalling emulation.
write_old = """static ssize_t ps2_audio_write(void *data, const void *s, size_t len)\n{\n   ps2_audio_t* ps2 = (ps2_audio_t*)data;\n   if (!ps2->running)\n      return -1;\n   return audsrv_play_audio(s, len);\n}\n"""
write_new = """static ssize_t ps2_audio_write(void *data, const void *s, size_t len)\n{\n   int rv;\n   ps2_audio_t* ps2 = (ps2_audio_t*)data;\n   if (!ps2->running)\n      return -1;\n   if (!len)\n      return 0;\n\n   rv = audsrv_play_audio((const char*)s, (int)len);\n   /* Report the input as consumed even if audsrv had room for only part of\n    * it. This is intentional on PS2: preserving realtime emulation is more\n    * important than blocking the EE for stale audio. */\n   return rv < 0 ? -1 : (ssize_t)len;\n}\n"""
if write_old not in s:
    raise SystemExit("ps2_audio_write anchor not found")
s = s.replace(write_old, write_new, 1)

p.write_text(s)
print("Applied PS2 audsrv init/rate fix with non-blocking writes")
