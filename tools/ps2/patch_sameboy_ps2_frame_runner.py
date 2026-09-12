#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_sameboy_ps2_frame_runner.py <SameBoy checkout>")

p = Path(sys.argv[1]) / "Core/gb.c"
s = p.read_text()
start = s.find("uint64_t GB_run_frame(GB_gameboy_t *gb)\n{")
end = s.find("\nuint32_t *GB_get_pixels_output", start)
if start < 0 or end < 0:
    raise SystemExit("GB_run_frame boundaries not found")

replacement = r'''uint64_t GB_run_frame(GB_gameboy_t *gb)
{
#ifdef GB_PS2_FAST
    /* SameBoy 0.15.4 normally returns through GB_run() once per SM83
     * instruction. Keep execution in one hot loop until VBlank instead. */
    bool old_turbo = gb->turbo;
    bool old_dont_skip = gb->turbo_dont_skip;
    gb->turbo = true;
    gb->turbo_dont_skip = true;

    gb->cycles_since_last_sync = 0;
    gb->vblank_just_occured = false;
    while (!gb->vblank_just_occured) {
        gb->cycles_since_run = 0;
        GB_cpu_run(gb);
    }

    if (!(gb->io_registers[GB_IO_IF] & 0x10) &&
        (gb->io_registers[GB_IO_JOYP] & 0x30) != 0x30) {
        gb->joyp_accessed = true;
    }

    gb->turbo = old_turbo;
    gb->turbo_dont_skip = old_dont_skip;
    return gb->cycles_since_last_sync * 1000000000LL / 2 / GB_get_clock_rate(gb);
#else
    /* Configure turbo temporarily, the user wants to handle FPS capping manually. */
    bool old_turbo = gb->turbo;
    bool old_dont_skip = gb->turbo_dont_skip;
    gb->turbo = true;
    gb->turbo_dont_skip = true;

    gb->cycles_since_last_sync = 0;
    while (true) {
        GB_run(gb);
        if (gb->vblank_just_occured) {
            break;
        }
    }
    gb->turbo = old_turbo;
    gb->turbo_dont_skip = old_dont_skip;
    return gb->cycles_since_last_sync * 1000000000LL / 2 / GB_get_clock_rate(gb);
#endif
}

void GB_set_pixels_output(GB_gameboy_t *gb, uint32_t *output)
{
    gb->screen = output;
}
'''

p.write_text(s[:start] + replacement + s[end:])
print("Applied SameBoy 0.15.4 PS2 hot VBlank runner")
