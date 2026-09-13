#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_upstream_sameboy_ps2.py <SameBoy checkout>")

root = Path(sys.argv[1])
p = root / "libretro/libretro.c"
s = p.read_text()

# PS2 needs a sane host sample rate. Current SameBoy libretro normally asks
# the core for half the Game Boy clock, which is useful on powerful hosts but
# far too expensive for the EE. 44.1 kHz is native to audsrv and matches the
# proven Gearboy PS2 path.
include_anchor = "#define WIIU_SAMPLE_RATE 48000\n"
include_repl = """#define WIIU_SAMPLE_RATE 48000
#ifdef PS2
#include <audsrv.h>
#define PS2_SAMPLE_RATE 44100
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

# Bypass RetroArch's generic audio mixing/resampling path on PS2. The PS2
# frontend already initializes audsrv before loading the static core. Feeding
# the frame's interleaved S16 stereo samples directly removes a layer that was
# silent in our earlier builds and also avoids unnecessary resampling work.
audio_anchor = """    while (remaining_frames > 0) {
        size_t uploaded_frames = audio_batch_cb(buf_pos, remaining_frames);
        buf_pos += uploaded_frames * 2;
        remaining_frames -= uploaded_frames;
    }
"""
audio_repl = """#ifdef PS2
    if (remaining_frames > 0) {
        const int bytes = (int)remaining_frames * 2 * (int)sizeof(int16_t);
        if (audsrv_wait_audio(bytes) >= 0) {
            int written = audsrv_play_audio((const char *)buf_pos, bytes);
            if (written > 0) {
                size_t uploaded_frames = (size_t)written / (2 * sizeof(int16_t));
                if (uploaded_frames > remaining_frames)
                    uploaded_frames = remaining_frames;
                buf_pos += uploaded_frames * 2;
                remaining_frames -= uploaded_frames;
            }
        }
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
print("Applied SameBoy 1.x PS2 patch: 44.1 kHz + direct audsrv audio")
