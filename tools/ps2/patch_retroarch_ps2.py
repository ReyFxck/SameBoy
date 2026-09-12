#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_retroarch_ps2.py <RetroArch checkout>")

root = Path(sys.argv[1])


def replace_once(path: Path, old: str, new: str, label: str):
    s = path.read_text()
    if old not in s:
        raise SystemExit(f"{label}: anchor not found in {path}")
    path.write_text(s.replace(old, new, 1))


# Static PS2 cores do not have a separately loadable core binary/info pair.
# Allow RetroArch to use the core linked into the ELF even if no matching .info
# file is present on disc.
makefile = root / "Makefile.ps2"
replace_once(
    makefile,
    "DEFINES += -DRARCH_INTERNAL -DRARCH_CONSOLE\n",
    "DEFINES += -DRARCH_INTERNAL -DRARCH_CONSOLE\n"
    "DEFINES += -DLOAD_WITHOUT_CORE_INFO\n",
    "LOAD_WITHOUT_CORE_INFO",
)

# When booting from optical media, keep content browsing on cdfs:/ but put
# writable RetroArch state (SRAM, states, config, remaps) on memory card 0.
platform = root / "frontend/drivers/platform_ps2.c"
replace_once(
    platform,
    "   size_t _len = strlcpy(user_path, cwd, sizeof(user_path));\n"
    "   if (!PATH_CHAR_IS_SLASH(user_path[_len - 1])) {\n",
    "   size_t _len = strlcpy(user_path, cwd, sizeof(user_path));\n"
    "   if (!strncmp(user_path, \"cdfs:\", 5))\n"
    "      _len = strlcpy(user_path, \"mc0:/RETROARCH\", sizeof(user_path));\n"
    "   if (!PATH_CHAR_IS_SLASH(user_path[_len - 1])) {\n",
    "PS2 memory-card user path",
)

# The PS2 newlib stdio/open layer cannot reliably read cdfs:/ files after the
# IOP CDFS driver is loaded. Use the PS2SDK legacy FILEIO RPC path for optical
# disc files only. Other devices keep using RetroArch's normal VFS.
vfs_h = root / "libretro-common/include/vfs/vfs.h"
replace_once(
    vfs_h,
    "   VFS_SCHEME_NONE = 0,\n   VFS_SCHEME_CDROM,\n",
    "   VFS_SCHEME_NONE = 0,\n   VFS_SCHEME_PS2_CDFS,\n   VFS_SCHEME_CDROM,\n",
    "PS2 CDFS scheme enum",
)

vfs = root / "libretro-common/vfs/vfs_implementation.c"
s = vfs.read_text()

include_anchor = "#include <fcntl.h>\n"
include_block = """#include <fcntl.h>\n#if defined(PS2)\n#ifndef NEWLIB_PORT_AWARE\n#define NEWLIB_PORT_AWARE\n#endif\n#include <fileio.h>\n#include <iox_stat.h>\n#endif\n"""
if include_anchor not in s:
    raise SystemExit("PS2 FILEIO include anchor not found")
s = s.replace(include_anchor, include_block, 1)

helper_anchor = """#if defined(ANDROID) && defined(HAVE_SAF)\nstatic int path_is_saf(const char *p)\n{\n   return (p\n         && p[0] == 's' && p[1] == 'a' && p[2] == 'f'\n         && p[3] == ':' && p[4] == '/' && p[5] == '/'\n         && p[6] != '\\0');\n}\n#endif\n"""
helper_block = helper_anchor + """\n#if defined(PS2)\nstatic int path_is_ps2_cdfs(const char *p)\n{\n   return p\n      && (p[0] == 'c' || p[0] == 'C')\n      && (p[1] == 'd' || p[1] == 'D')\n      && (p[2] == 'f' || p[2] == 'F')\n      && (p[3] == 's' || p[3] == 'S')\n      && p[4] == ':' && p[5] == '/';\n}\n#endif\n"""
if helper_anchor not in s:
    raise SystemExit("PS2 CDFS helper anchor not found")
s = s.replace(helper_anchor, helper_block, 1)

seek_anchor = """   if (!stream)\n      return -1;\n\n   if ((stream->hints & RFILE_HINT_UNBUFFERED) == 0)\n"""
seek_block = """   if (!stream)\n      return -1;\n\n#if defined(PS2)\n   if (stream->scheme == VFS_SCHEME_PS2_CDFS)\n   {\n      int rv;\n      if (offset > 0x7fffffffLL || offset < (-0x7fffffffLL - 1))\n         return -1;\n      rv = fioLseek(stream->fd, (int)offset, whence);\n      return rv < 0 ? -1 : 0;\n   }\n#endif\n\n   if ((stream->hints & RFILE_HINT_UNBUFFERED) == 0)\n"""
# Only replace the first occurrence: retro_vfs_file_seek_internal().
if seek_anchor not in s:
    raise SystemExit("PS2 seek anchor not found")
s = s.replace(seek_anchor, seek_block, 1)

scheme_anchor = """#if defined(ANDROID) && defined(HAVE_SAF)\n   if (path_is_saf(path))\n   {\n      stream->scheme    = VFS_SCHEME_SAF;\n   }\n#endif\n\n   if (path)\n"""
scheme_block = """#if defined(ANDROID) && defined(HAVE_SAF)\n   if (path_is_saf(path))\n   {\n      stream->scheme    = VFS_SCHEME_SAF;\n   }\n#endif\n\n#if defined(PS2)\n   if (path_is_ps2_cdfs(path))\n   {\n      stream->scheme = VFS_SCHEME_PS2_CDFS;\n      stream->hints |= RFILE_HINT_UNBUFFERED;\n   }\n#endif\n\n   if (path)\n"""
if scheme_anchor not in s:
    raise SystemExit("PS2 open scheme anchor not found")
s = s.replace(scheme_anchor, scheme_block, 1)

open_anchor = """      switch (stream->scheme)\n      {\n#if defined(ANDROID) && defined(HAVE_SAF)\n"""
open_block = """      switch (stream->scheme)\n      {\n#if defined(PS2)\n         case VFS_SCHEME_PS2_CDFS:\n            if (mode != RETRO_VFS_FILE_ACCESS_READ)\n               goto error;\n            {\n               int fd = fioOpen(path, FIO_O_RDONLY);\n               stream->fd = fd < 0 ? -1 : fd;\n            }\n            break;\n#endif\n#if defined(ANDROID) && defined(HAVE_SAF)\n"""
if open_anchor not in s:
    raise SystemExit("PS2 fioOpen anchor not found")
s = s.replace(open_anchor, open_block, 1)

close_anchor = """#ifdef HAVE_SMBCLIENT\n   if (stream->scheme == VFS_SCHEME_SMB)\n   {\n      retro_vfs_file_close_smb(stream);\n      goto smbend;\n   }\n#endif\n\n   if ((stream->hints & RFILE_HINT_UNBUFFERED) == 0)\n"""
close_block = """#ifdef HAVE_SMBCLIENT\n   if (stream->scheme == VFS_SCHEME_SMB)\n   {\n      retro_vfs_file_close_smb(stream);\n      goto smbend;\n   }\n#endif\n\n#if defined(PS2)\n   if (stream->scheme == VFS_SCHEME_PS2_CDFS && stream->fd >= 0)\n   {\n      fioClose(stream->fd);\n      stream->fd = -1;\n   }\n#endif\n\n   if ((stream->hints & RFILE_HINT_UNBUFFERED) == 0)\n"""
if close_anchor not in s:
    raise SystemExit("PS2 fioClose anchor not found")
s = s.replace(close_anchor, close_block, 1)

error_anchor = """int retro_vfs_file_error_impl(libretro_vfs_implementation_file *stream)\n{\n   if (!stream)\n      return -1;\n"""
error_block = """int retro_vfs_file_error_impl(libretro_vfs_implementation_file *stream)\n{\n   if (!stream)\n      return -1;\n#if defined(PS2)\n   if (stream->scheme == VFS_SCHEME_PS2_CDFS)\n      return 0;\n#endif\n"""
if error_anchor not in s:
    raise SystemExit("PS2 error anchor not found")
s = s.replace(error_anchor, error_block, 1)

tell_anchor = """int64_t retro_vfs_file_tell_impl(libretro_vfs_implementation_file *stream)\n{\n   if (!stream)\n      return -1;\n\n   if ((stream->hints & RFILE_HINT_UNBUFFERED) == 0)\n"""
tell_block = """int64_t retro_vfs_file_tell_impl(libretro_vfs_implementation_file *stream)\n{\n   if (!stream)\n      return -1;\n\n#if defined(PS2)\n   if (stream->scheme == VFS_SCHEME_PS2_CDFS)\n   {\n      int rv = fioLseek(stream->fd, 0, FIO_SEEK_CUR);\n      return rv < 0 ? -1 : (int64_t)rv;\n   }\n#endif\n\n   if ((stream->hints & RFILE_HINT_UNBUFFERED) == 0)\n"""
if tell_anchor not in s:
    raise SystemExit("PS2 tell anchor not found")
s = s.replace(tell_anchor, tell_block, 1)

read_anchor = """   if (len > (uint64_t)INT64_MAX)\n      return -1;\n\n   if ((stream->hints & RFILE_HINT_UNBUFFERED) == 0)\n"""
read_block = """   if (len > (uint64_t)INT64_MAX)\n      return -1;\n\n#if defined(PS2)\n   if (stream->scheme == VFS_SCHEME_PS2_CDFS)\n   {\n      uint8_t *p = (uint8_t*)s;\n      uint64_t total = 0;\n      while (len != 0)\n      {\n         int chunk = len > 0x7fffffffULL ? 0x7fffffff : (int)len;\n         int got = fioRead(stream->fd, p, chunk);\n         if (got < 0)\n            return total ? (int64_t)total : -1;\n         total += (uint64_t)got;\n         if (got < chunk)\n            break;\n         p += got;\n         len -= (uint64_t)got;\n      }\n      return (int64_t)total;\n   }\n#endif\n\n   if ((stream->hints & RFILE_HINT_UNBUFFERED) == 0)\n"""
# This anchor appears in read only in the pinned RetroArch revision.
if read_anchor not in s:
    raise SystemExit("PS2 fioRead anchor not found")
s = s.replace(read_anchor, read_block, 1)

flush_anchor = """int retro_vfs_file_flush_impl(libretro_vfs_implementation_file *stream)\n{\n   if (!stream)\n      return -1;\n"""
flush_block = """int retro_vfs_file_flush_impl(libretro_vfs_implementation_file *stream)\n{\n   if (!stream)\n      return -1;\n#if defined(PS2)\n   if (stream->scheme == VFS_SCHEME_PS2_CDFS)\n      return 0;\n#endif\n"""
if flush_anchor not in s:
    raise SystemExit("PS2 flush anchor not found")
s = s.replace(flush_anchor, flush_block, 1)

stat_anchor = """#if defined(ANDROID) && defined(HAVE_SAF)\n   if (path_is_saf(path))\n   {\n      struct libretro_vfs_implementation_saf_path_split_result saf_split_result;\n      if (!retro_vfs_path_split_saf(&saf_split_result, path))\n         return 0;\n      ret = retro_vfs_stat_saf(saf_split_result.tree, saf_split_result.path, size);\n      free(saf_split_result.path);\n      free(saf_split_result.tree);\n      return ret;\n   }\n#endif\n\n   {\n"""
stat_block = """#if defined(ANDROID) && defined(HAVE_SAF)\n   if (path_is_saf(path))\n   {\n      struct libretro_vfs_implementation_saf_path_split_result saf_split_result;\n      if (!retro_vfs_path_split_saf(&saf_split_result, path))\n         return 0;\n      ret = retro_vfs_stat_saf(saf_split_result.tree, saf_split_result.path, size);\n      free(saf_split_result.path);\n      free(saf_split_result.tree);\n      return ret;\n   }\n#endif\n\n#if defined(PS2)\n   if (path_is_ps2_cdfs(path))\n   {\n      io_stat_t stat_buf __attribute__((aligned(64)));\n      memset(&stat_buf, 0, sizeof(stat_buf));\n      if (fioGetstat(path, &stat_buf) < 0)\n         return 0;\n      if (size)\n         *size = ((int64_t)stat_buf.hisize << 32) | stat_buf.size;\n      if (FIO_SO_ISDIR(stat_buf.mode))\n         ret |= RETRO_VFS_STAT_IS_DIRECTORY;\n      ret |= RETRO_VFS_STAT_IS_READONLY;\n      return ret;\n   }\n#endif\n\n   {\n"""
if stat_anchor not in s:
    raise SystemExit("PS2 fioGetstat anchor not found")
s = s.replace(stat_anchor, stat_block, 1)

vfs.write_text(s)
print("Applied SameBoy PS2 RetroArch patches")
