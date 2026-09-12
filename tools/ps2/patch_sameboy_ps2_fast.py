#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_sameboy_ps2_fast.py <SameBoy checkout>")

root = Path(sys.argv[1])
cpu = root / "Core/sm83_cpu.c"
gb_c = root / "Core/gb.c"
libretro = root / "libretro/libretro.c"

# ---------------------------------------------------------------------------
# 1) SM83: Gearboy-style coarse scheduling on PS2
# ---------------------------------------------------------------------------
s = cpu.read_text()

# SameBoy's stock core advances timer/APU/PPU on almost every memory M-cycle.
# Gearboy's PS2 PERFORMANCE path instead lets the CPU run a sizeable chunk and
# then advances the rest of the machine. Reproduce that idea here while still
# forcing exact synchronization for timing-sensitive VRAM/OAM/IO accesses.
read_anchor = """static uint8_t cycle_read(GB_gameboy_t *gb, uint16_t addr)\n{\n    if (gb->pending_cycles) {\n"""
read_repl = """static inline __attribute__((always_inline)) uint8_t cycle_read(GB_gameboy_t *gb, uint16_t addr)\n{\n#ifdef GB_PS2_FAST\n    /* ROM, cartridge RAM, WRAM/echo and HRAM can be read without forcing the\n     * PPU/APU/timer state machines to synchronize every M-cycle. */\n    if (addr < 0x8000 ||\n        (addr >= 0xA000 && addr < 0xFE00) ||\n        (addr >= 0xFF80 && addr < 0xFFFF)) {\n        gb->address_bus = addr;\n        uint8_t ret = GB_read_memory(gb, addr);\n        gb->pending_cycles += 4;\n        return ret;\n    }\n#endif\n    if (gb->pending_cycles) {\n"""
if read_anchor not in s:
    raise SystemExit("cycle_read anchor not found")
s = s.replace(read_anchor, read_repl, 1)

write_anchor = """static void cycle_write(GB_gameboy_t *gb, uint16_t addr, uint8_t value)\n{\n    assert(gb->pending_cycles);\n"""
write_repl = """static inline __attribute__((always_inline)) void cycle_write(GB_gameboy_t *gb, uint16_t addr, uint8_t value)\n{\n#ifdef GB_PS2_FAST\n    /* Same coarse path as reads. IO/OAM/VRAM still use the accurate path. */\n    if (addr < 0x8000 ||\n        (addr >= 0xA000 && addr < 0xFE00) ||\n        (addr >= 0xFF80 && addr < 0xFFFF)) {\n        GB_write_memory(gb, addr, value);\n        gb->address_bus = addr;\n        gb->pending_cycles += 4;\n        return;\n    }\n#endif\n    assert(gb->pending_cycles);\n"""
if write_anchor not in s:
    raise SystemExit("cycle_write anchor not found")
s = s.replace(write_anchor, write_repl, 1)

flush_anchor = """static void flush_pending_cycles(GB_gameboy_t *gb)\n{\n    if (gb->pending_cycles) {\n        GB_advance_cycles(gb, gb->pending_cycles);\n    }\n    gb->pending_cycles = 0;\n}\n"""
flush_repl = flush_anchor + """
#ifdef GB_PS2_FAST
/* Gearboy's PS2 PERFORMANCE mode runs roughly 75 CPU ticks before syncing
 * video/audio/timers. SameBoy uses 4-T-cycle M-cycles, so use a 96-cycle
 * budget: large enough to amortize the state machines, small enough to keep
 * normal games responsive. Explicit timing-sensitive flushes above remain
 * exact and bypass this threshold. */
#define GB_PS2_BATCH_CYCLES 96u
static inline __attribute__((always_inline)) void ps2_fast_maybe_flush_pending(GB_gameboy_t *gb)
{
    if (gb->pending_cycles >= GB_PS2_BATCH_CYCLES) {
        GB_advance_cycles(gb, gb->pending_cycles);
        gb->pending_cycles = 0;
    }
}
#endif
"""
if flush_anchor not in s:
    raise SystemExit("flush_pending_cycles anchor not found")
s = s.replace(flush_anchor, flush_repl, 1)

# Replace the indirect opcode function-pointer call with a direct switch. This
# gives GCC/LTO a chance to inline tiny handlers and removes a hard-to-predict
# indirect branch from every emulated instruction on the R5900.
table_marker = "static opcode_t *opcodes[256] = {"
table_start = s.find(table_marker)
if table_start < 0:
    raise SystemExit("opcode table not found")
brace_start = s.find("{", table_start)
brace_end = s.find("};", brace_start)
if brace_end < 0:
    raise SystemExit("opcode table end not found")
body = s[brace_start + 1:brace_end]
body = re.sub(r"/\*.*?\*/", "", body, flags=re.S)
ops = [x.strip() for x in body.replace("\n", " ").split(",") if x.strip()]
if len(ops) != 256:
    raise SystemExit(f"expected 256 opcode entries, got {len(ops)}")
for op in ops:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", op):
        raise SystemExit(f"unexpected opcode handler token: {op!r}")

cases = [f"            case 0x{i:02X}: {op}(gb, opcode); break;" for i, op in enumerate(ops)]
switch_code = "\n".join(cases)
dispatch_anchor = "        opcodes[opcode](gb, opcode);\n"
dispatch_repl = (
    "#ifdef GB_PS2_FAST\n"
    "        switch (opcode) {\n"
    + switch_code + "\n"
    "        }\n"
    "#else\n"
    "        opcodes[opcode](gb, opcode);\n"
    "#endif\n"
)
if dispatch_anchor not in s:
    raise SystemExit("opcode dispatch anchor not found")
s = s.replace(dispatch_anchor, dispatch_repl, 1)

# The last flush in GB_cpu_run is the per-instruction synchronization point.
# Keep explicit mid-instruction flushes accurate, but turn this final one into
# the 96-cycle coarse scheduler on PS2.
cpu_run_pos = s.find("void GB_cpu_run(GB_gameboy_t *gb)")
if cpu_run_pos < 0:
    raise SystemExit("GB_cpu_run not found")
last_flush = s.rfind("    flush_pending_cycles(gb);\n}")
if last_flush < cpu_run_pos:
    raise SystemExit("GB_cpu_run final flush not found")
s = s[:last_flush] + """#ifdef GB_PS2_FAST
    ps2_fast_maybe_flush_pending(gb);
#else
    flush_pending_cycles(gb);
#endif
}""" + s[last_flush + len("    flush_pending_cycles(gb);\n}"):]

cpu.write_text(s)

# ---------------------------------------------------------------------------
# 2) Frame runner: stay inside the core until VBlank
# ---------------------------------------------------------------------------
s = gb_c.read_text()
start = s.find("uint64_t GB_run_frame(GB_gameboy_t *gb)\n{")
end = s.find("\nuint32_t *GB_get_pixels_output", start)
if start < 0 or end < 0:
    raise SystemExit("GB_run_frame boundaries not found")
orig_func = s[start:end]
body_start = orig_func.find("{") + 1
orig_body = orig_func[body_start:-1]
fast_func = """uint64_t GB_run_frame(GB_gameboy_t *gb)
{
#ifdef GB_PS2_FAST
    /* Avoid returning through GB_run() once per SM83 instruction. Keep the
     * R5900 in one hot loop until VBlank, like Gearboy's RunToVBlank path. */
    bool old_turbo = gb->turbo;
    bool old_dont_skip = gb->turbo_dont_skip;
    double old_turbo_cap = gb->turbo_cap_multiplier;
    gb->turbo = true;
    gb->turbo_dont_skip = true;
    gb->turbo_cap_multiplier = 0;

    gb->cycles_since_last_sync = 0;
    gb->vblank_just_occured = false;
    GB_set_running_thread(gb);
    while (!gb->vblank_just_occured) {
        gb->cycles_since_run = 0;
        GB_cpu_run(gb);
    }
    GB_clear_running_thread(gb);

    GB_update_faux_analog(gb);
    if (!(gb->io_registers[GB_IO_IF] & 0x10) &&
        (gb->io_registers[GB_IO_JOYP] & 0x30) != 0x30) {
        gb->joyp_accessed = true;
    }

    gb->turbo = old_turbo;
    gb->turbo_dont_skip = old_dont_skip;
    gb->turbo_cap_multiplier = old_turbo_cap;
    return gb->cycles_since_last_sync * 1000000000LL / 2 / GB_get_clock_rate(gb);
#else
""" + orig_body + """
#endif
}
"""
s = s[:start] + fast_func + s[end:]
gb_c.write_text(s)

# ---------------------------------------------------------------------------
# 3) Libretro: native PS2 16-bit texture + reliable audio batching
# ---------------------------------------------------------------------------
s = libretro.read_text()

# Keep SameBoy's internal screen as uint32_t for minimal invasive changes, but
# encode each color directly as the same BGR555 layout Gearboy uses on PS2 and
# pack the low 16 bits into a native GS CT16 upload buffer once per frame.
frame_anchor = """static uint32_t *frame_buf = NULL;\nstatic uint32_t *frame_buf_copy = NULL;\n"""
frame_repl = frame_anchor + """#ifdef PS2
static uint16_t ps2_frame_buf[MAX_VIDEO_PIXELS * 2];
#endif
"""
if frame_anchor not in s:
    raise SystemExit("frame buffer declaration anchor not found")
s = s.replace(frame_anchor, frame_repl, 1)

rgb_anchor = """static uint32_t rgb_encode(GB_gameboy_t *gb, uint8_t r, uint8_t g, uint8_t b)\n{\n    return r <<16 | g <<8 | b;\n}\n"""
rgb_repl = """static uint32_t rgb_encode(GB_gameboy_t *gb, uint8_t r, uint8_t g, uint8_t b)\n{\n#ifdef PS2\n    (void)gb;\n    /* Match Gearboy's proven PS2 path: A1:B5:G5:R5 (GS CT16). */\n    return 0x8000u | ((uint32_t)(b >> 3) << 10) |\n           ((uint32_t)(g >> 3) << 5) | (uint32_t)(r >> 3);\n#else\n    return r <<16 | g <<8 | b;\n#endif\n}\n\n#ifdef PS2\nstatic inline __attribute__((always_inline)) const uint16_t *ps2_pack_frame(const uint32_t *src, size_t pixels)\n{\n    uint32_t *dst = (uint32_t *)ps2_frame_buf;\n    size_t pairs = pixels >> 1;\n    for (size_t i = 0; i < pairs; i++) {\n        uint32_t a = src[i * 2] & 0xFFFFu;\n        uint32_t b = src[i * 2 + 1] & 0xFFFFu;\n        dst[i] = a | (b << 16);\n    }\n    if (pixels & 1)\n        ps2_frame_buf[pixels - 1] = (uint16_t)src[pixels - 1];\n    return ps2_frame_buf;\n}\n#endif\n"""
if rgb_anchor not in s:
    raise SystemExit("rgb_encode anchor not found")
s = s.replace(rgb_anchor, rgb_repl, 1)

# Do not drop the whole frame's audio if the frontend temporarily accepts zero
# frames. The patched PS2 audio driver below waits for audsrv ring-buffer space,
# so normally this completes in one call; the zero guard prevents a dead loop.
audio_anchor = """static void upload_output_audio_buffer()\n{\n    int32_t remaining_frames = output_audio_buffer.size / 2;\n    int16_t *buf_pos = output_audio_buffer.data;\n\n    while (remaining_frames > 0) {\n        size_t uploaded_frames = audio_batch_cb(buf_pos, remaining_frames);\n        buf_pos += uploaded_frames * 2;\n        remaining_frames -= uploaded_frames;\n    }\n    output_audio_buffer.size = 0;\n}\n"""
audio_repl = """static void upload_output_audio_buffer()\n{\n    int32_t remaining_frames = output_audio_buffer.size / 2;\n    int16_t *buf_pos = output_audio_buffer.data;\n\n    while (remaining_frames > 0) {\n        size_t uploaded_frames = audio_batch_cb(buf_pos, remaining_frames);\n        if (uploaded_frames == 0)\n            break;\n        buf_pos += uploaded_frames * 2;\n        remaining_frames -= uploaded_frames;\n    }\n    output_audio_buffer.size = 0;\n}\n"""
if audio_anchor not in s:
    raise SystemExit("audio upload anchor not found")
s = s.replace(audio_anchor, audio_repl, 1)

# SameBoy normally requests XRGB8888. On the PS2 this makes gsKit upload CT32
# textures even though the GS framebuffer is CT16. Gearboy's PS2 core uses a
# 16-bit texture path; request the same class of path here.
pix_anchor = """    enum retro_pixel_format fmt = RETRO_PIXEL_FORMAT_XRGB8888;\n    if (!environ_cb(RETRO_ENVIRONMENT_SET_PIXEL_FORMAT, &fmt)) {\n        log_cb(RETRO_LOG_ERROR, \"XRGB8888 is not supported\\n\");\n        return false;\n    }\n"""
pix_repl = """#ifdef PS2\n    enum retro_pixel_format fmt = RETRO_PIXEL_FORMAT_RGB565;\n#else\n    enum retro_pixel_format fmt = RETRO_PIXEL_FORMAT_XRGB8888;\n#endif\n    if (!environ_cb(RETRO_ENVIRONMENT_SET_PIXEL_FORMAT, &fmt)) {\n        log_cb(RETRO_LOG_ERROR, \"Requested pixel format is not supported\\n\");\n        return false;\n    }\n"""
count = s.count(pix_anchor)
if count != 2:
    raise SystemExit(f"expected 2 pixel format anchors, got {count}")
s = s.replace(pix_anchor, pix_repl)

single_video = """        video_cb(frame_buf,\n                 GB_get_screen_width(&gameboy[0]),\n                 GB_get_screen_height(&gameboy[0]),\n                 GB_get_screen_width(&gameboy[0]) * sizeof(uint32_t));\n"""
single_repl = """#ifdef PS2\n        unsigned w = GB_get_screen_width(&gameboy[0]);\n        unsigned h = GB_get_screen_height(&gameboy[0]);\n        const uint16_t *packed = ps2_pack_frame(frame_buf, (size_t)w * h);\n        video_cb(packed, w, h, w * sizeof(uint16_t));\n#else\n        video_cb(frame_buf,\n                 GB_get_screen_width(&gameboy[0]),\n                 GB_get_screen_height(&gameboy[0]),\n                 GB_get_screen_width(&gameboy[0]) * sizeof(uint32_t));\n#endif\n"""
if single_video not in s:
    raise SystemExit("single-device video callback anchor not found")
s = s.replace(single_video, single_repl, 1)

top_video = """            video_cb(frame_buf,\n                     GB_get_screen_width(&gameboy[0]),\n                     GB_get_screen_height(&gameboy[0]) * emulated_devices,\n                     GB_get_screen_width(&gameboy[0]) * sizeof(uint32_t));\n"""
top_repl = """#ifdef PS2\n            unsigned w = GB_get_screen_width(&gameboy[0]);\n            unsigned h = GB_get_screen_height(&gameboy[0]) * emulated_devices;\n            video_cb(ps2_pack_frame(frame_buf, (size_t)w * h),\n                     w, h, w * sizeof(uint16_t));\n#else\n            video_cb(frame_buf,\n                     GB_get_screen_width(&gameboy[0]),\n                     GB_get_screen_height(&gameboy[0]) * emulated_devices,\n                     GB_get_screen_width(&gameboy[0]) * sizeof(uint32_t));\n#endif\n"""
if top_video not in s:
    raise SystemExit("top-down video callback anchor not found")
s = s.replace(top_video, top_repl, 1)

lr_video = """            video_cb(frame_buf_copy, GB_get_screen_width(&gameboy[0]) * emulated_devices, GB_get_screen_height(&gameboy[0]), GB_get_screen_width(&gameboy[0]) * emulated_devices * sizeof(uint32_t));\n"""
lr_repl = """#ifdef PS2\n            unsigned out_w = GB_get_screen_width(&gameboy[0]) * emulated_devices;\n            unsigned out_h = GB_get_screen_height(&gameboy[0]);\n            video_cb(ps2_pack_frame(frame_buf_copy, (size_t)out_w * out_h),\n                     out_w, out_h, out_w * sizeof(uint16_t));\n#else\n            video_cb(frame_buf_copy, GB_get_screen_width(&gameboy[0]) * emulated_devices, GB_get_screen_height(&gameboy[0]), GB_get_screen_width(&gameboy[0]) * emulated_devices * sizeof(uint32_t));\n#endif\n"""
if lr_video not in s:
    raise SystemExit("left-right video callback anchor not found")
s = s.replace(lr_video, lr_repl, 1)

libretro.write_text(s)
print("Applied PS2 coarse SM83 scheduling, hot frame loop, 16-bit GS video and safe audio batching")
