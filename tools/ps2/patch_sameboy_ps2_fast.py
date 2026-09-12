#!/usr/bin/env python3
from pathlib import Path
import re
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_sameboy_ps2_fast.py <SameBoy checkout>")

root = Path(sys.argv[1])
cpu = root / "Core/sm83_cpu.c"
libretro = root / "libretro/libretro.c"

s = cpu.read_text()

# The stock SameBoy SM83 core is deliberately very cycle-accurate. On the PS2
# that means every memory M-cycle can call the timer/APU/PPU scheduler before
# returning to the opcode handler. Keep exact timing for VRAM/OAM/IO accesses,
# but batch ordinary ROM/RAM/HRAM accesses until the end of the instruction.
# This preserves total emulated cycles while cutting a large number of
# cross-component scheduler calls on the R5900.
read_anchor = """static uint8_t cycle_read(GB_gameboy_t *gb, uint16_t addr)\n{\n    if (gb->pending_cycles) {\n"""
read_repl = """static inline __attribute__((always_inline)) uint8_t cycle_read(GB_gameboy_t *gb, uint16_t addr)\n{\n#ifdef GB_PS2_FAST\n    /* Timing-sensitive areas still use SameBoy's original per-M-cycle path. */\n    if (addr < 0x8000 ||\n        (addr >= 0xA000 && addr < 0xFE00) ||\n        (addr >= 0xFF80 && addr < 0xFFFF)) {\n        gb->address_bus = addr;\n        uint8_t ret = GB_read_memory(gb, addr);\n        gb->pending_cycles += 4;\n        return ret;\n    }\n#endif\n    if (gb->pending_cycles) {\n"""
if read_anchor not in s:
    raise SystemExit("cycle_read anchor not found")
s = s.replace(read_anchor, read_repl, 1)

write_anchor = """static void cycle_write(GB_gameboy_t *gb, uint16_t addr, uint8_t value)\n{\n    assert(gb->pending_cycles);\n"""
write_repl = """static inline __attribute__((always_inline)) void cycle_write(GB_gameboy_t *gb, uint16_t addr, uint8_t value)\n{\n#ifdef GB_PS2_FAST\n    /* Ordinary ROM/RAM/HRAM writes do not need sub-instruction PPU timing. */\n    if (addr < 0x8000 ||\n        (addr >= 0xA000 && addr < 0xFE00) ||\n        (addr >= 0xFF80 && addr < 0xFFFF)) {\n        GB_write_memory(gb, addr, value);\n        gb->address_bus = addr;\n        gb->pending_cycles += 4;\n        return;\n    }\n#endif\n    assert(gb->pending_cycles);\n"""
if write_anchor not in s:
    raise SystemExit("cycle_write anchor not found")
s = s.replace(write_anchor, write_repl, 1)

# The original opcode table performs an indirect function call for every SM83
# instruction. That is disproportionately expensive on the R5900. Generate a
# direct switch from the table so GCC can turn dispatch into direct branches
# and inline the small opcode handlers into GB_cpu_run().
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

cases = []
for i, op in enumerate(ops):
    cases.append(f"            case 0x{i:02X}: {op}(gb, opcode); break;")
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

cpu.write_text(s)

# The libretro wrapper retries audio_batch_cb() until every generated sample is
# accepted. audsrv may legally accept only part of a chunk when its ring is
# temporarily full, so the retry loop can stall the entire emulation thread.
# On PS2, submit once and drop only an unaccepted tail; the next frame must not
# be held hostage by SPU buffering.
s = libretro.read_text()
audio_anchor = """static void upload_output_audio_buffer()\n{\n    int32_t remaining_frames = output_audio_buffer.size / 2;\n    int16_t *buf_pos = output_audio_buffer.data;\n\n    while (remaining_frames > 0) {\n        size_t uploaded_frames = audio_batch_cb(buf_pos, remaining_frames);\n        buf_pos += uploaded_frames * 2;\n        remaining_frames -= uploaded_frames;\n    }\n    output_audio_buffer.size = 0;\n}\n"""
audio_repl = """static void upload_output_audio_buffer()\n{\n    int32_t remaining_frames = output_audio_buffer.size / 2;\n    int16_t *buf_pos = output_audio_buffer.data;\n\n#ifdef GB_PS2_FAST\n    if (remaining_frames > 0)\n        (void)audio_batch_cb(buf_pos, remaining_frames);\n#else\n    while (remaining_frames > 0) {\n        size_t uploaded_frames = audio_batch_cb(buf_pos, remaining_frames);\n        buf_pos += uploaded_frames * 2;\n        remaining_frames -= uploaded_frames;\n    }\n#endif\n    output_audio_buffer.size = 0;\n}\n"""
if audio_anchor not in s:
    raise SystemExit("audio upload anchor not found")
s = s.replace(audio_anchor, audio_repl, 1)
libretro.write_text(s)

print("Applied PS2 fast CPU dispatch, cycle batching and nonblocking audio submit")
