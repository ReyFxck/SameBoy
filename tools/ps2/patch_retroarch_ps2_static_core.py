#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_retroarch_ps2_static_core.py <RetroArch checkout>")

p = Path(sys.argv[1]) / "menu/cbs/menu_cbs_deferred_push.c"
s = p.read_text()

old = """            bool filter_by_current_core       = settings->bools.filter_by_current_core;\n\n            if (sysinfo && sysinfo->valid_extensions && *sysinfo->valid_extensions\n                && filter_by_current_core)\n"""
new = """            bool filter_by_current_core       = settings->bools.filter_by_current_core;\n\n#if defined(PS2) && defined(LOAD_WITHOUT_CORE_INFO)\n            /* The PS2 build links one libretro core directly into the ELF and\n             * intentionally ships without a .info database. The normal Load\n             * Content browser therefore cannot build list->all_ext and may\n             * end up filtering the disc to multimedia formats only. Use the\n             * extensions reported by the statically linked core instead. */\n            filter_by_current_core = true;\n#endif\n\n            if (sysinfo && sysinfo->valid_extensions && *sysinfo->valid_extensions\n                && filter_by_current_core)\n"""

if old not in s:
    raise SystemExit("static-core extension filter anchor not found")

p.write_text(s.replace(old, new, 1))
print("Applied PS2 static-core content extension filter")
