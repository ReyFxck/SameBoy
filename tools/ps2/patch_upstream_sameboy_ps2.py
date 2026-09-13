#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_upstream_sameboy_ps2.py <SameBoy checkout>")

root = Path(sys.argv[1])
p = root / "libretro/libretro.c"
s = p.read_text()

# The R5900 does not need SameBoy's multi-megahertz libretro audio rate.
# 22.05 kHz keeps Game Boy audio useful while cutting sample callback work in
# half versus the previous PS2 build.
include_anchor = "#define WIIU_SAMPLE_RATE 48000\n"
include_repl = """#define WIIU_SAMPLE_RATE 48000
#ifdef PS2
/* RetroArch already links audsrv. Keep this PS2-only core patch independent
 * from PS2SDK header layout and use the non-blocking queue primitive only. */
extern int audsrv_play_audio(const char *chunk, int bytes);
#define PS2_SAMPLE_RATE 22050
#endif
"""
if include_anchor not in s:
    raise SystemExit("WIIU sample-rate anchor not found")
s = s.replace(include_anchor, include_repl, 1)

rate_anchor = """#ifdef WIIU
    GB_set_sample_rate(&gameboy[i], WIIU_SAMPLE_RATE);
#else
    GB_set_sample_rate(&gameboy[i], GB_get_clock_rate(&gameboy[i]) / 2);
#endif
"""
rate_repl = """#ifdef WIIU
    GB_set_sample_rate(&gameboy[i], WIIU_SAMPLE_RATE);
#elif defined(PS2)
    GB_set_sample_rate(&gameboy[i], PS2_SAMPLE_RATE);
#else
    GB_set_sample_rate(&gameboy[i], GB_get_clock_rate(&gameboy[i]) / 2);
#endif
"""
if rate_anchor not in s:
    raise SystemExit("sample-rate setup anchor not found")
s = s.replace(rate_anchor, rate_repl, 1)

# FPS-first PS2 path: never wait for the IOP audio ring. audsrv_play_audio()
# copies only what currently fits and returns immediately; if the ring is full
# the tail is deliberately dropped. This prevents audio back-pressure from
# stalling retro_run() and lets the EE spend its time emulating the Game Boy.
audio_anchor = """    while (remaining_frames > 0) {
        size_t uploaded_frames = audio_batch_cb(buf_pos, remaining_frames);
        buf_pos += uploaded_frames * 2;
        remaining_frames -= uploaded_frames;
    }
"""
audio_repl = """#ifdef PS2
    if (remaining_frames > 0) {
        const int bytes = (int)remaining_frames * 2 * (int)sizeof(int16_t);
        (void)audsrv_play_audio((const char *)buf_pos, bytes);
        /* Whatever did not fit is intentionally dropped on PS2. */
        remaining_frames = 0;
    }
#else
    while (remaining_frames > 0) {
        size_t uploaded_frames = audio_batch_cb(buf_pos, remaining_frames);
        if (uploaded_frames == 0)
            break;
        buf_pos += uploaded_frames * 2;
        remaining_frames -= uploaded_frames;
    }
#endif
"""
if audio_anchor not in s:
    raise SystemExit("audio upload loop anchor not found")
s = s.replace(audio_anchor, audio_repl, 1)

p.write_text(s)
print("Applied SameBoy 1.x PS2 fast audio patch: 22.05 kHz + non-blocking audsrv")
