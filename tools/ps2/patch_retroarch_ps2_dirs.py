#!/usr/bin/env python3
from pathlib import Path
import sys

if len(sys.argv) != 2:
    raise SystemExit("usage: patch_retroarch_ps2_dirs.py <RetroArch checkout>")

p = Path(sys.argv[1]) / "libretro-common/vfs/vfs_implementation.c"
s = p.read_text()


def rep(old: str, new: str, label: str):
    global s
    if old not in s:
        raise SystemExit(f"{label}: anchor not found")
    s = s.replace(old, new, 1)

# Keep normal POSIX directory handles for mc0:/mass:/etc, but add a dedicated
# legacy FILEIO handle + aligned ioman dirent for optical-disc browsing.
rep(
"""#else
   DIR *directory;
   const struct dirent *entry;
#endif
#if defined(ANDROID) && defined(HAVE_SAF)
""",
"""#else
   DIR *directory;
   const struct dirent *entry;
#if defined(PS2)
   int ps2_cdfs_dir;
   io_dirent_t ps2_cdfs_entry __attribute__((aligned(64)));
   bool ps2_cdfs;
#endif
#endif
#if defined(ANDROID) && defined(HAVE_SAF)
""",
"PS2 directory handle fields")

# Open cdfs:/ directories through FILEIO. This is the same RPC family used by
# the CDFS file fast path and avoids depending on the newlib dirent shim.
opendir_anchor = """#if defined(ANDROID) && defined(HAVE_SAF)
   rdir->saf_directory = NULL;

   if (path_is_saf(name))
   {
      struct libretro_vfs_implementation_saf_path_split_result saf_split_result;
      if (!retro_vfs_path_split_saf(&saf_split_result, name))
      {
         free(rdir->orig_path);
         free(rdir);
         return NULL;
      }
      rdir->saf_directory = retro_vfs_opendir_saf(saf_split_result.tree, saf_split_result.path, include_hidden);
      free(saf_split_result.path);
      free(saf_split_result.tree);
      if (rdir->saf_directory == NULL)
      {
         free(rdir->orig_path);
         free(rdir);
         return NULL;
      }
      return rdir;
   }
#endif

#if defined(_WIN32)
"""
opendir_block = opendir_anchor[:-len("#if defined(_WIN32)\n")] + """#if defined(PS2)
   if (path_is_ps2_cdfs(name))
   {
      rdir->ps2_cdfs_dir = fioDopen(name);
      if (rdir->ps2_cdfs_dir < 0)
      {
         free(rdir->orig_path);
         free(rdir);
         return NULL;
      }
      rdir->ps2_cdfs = true;
      (void)include_hidden;
      return rdir;
   }
#endif

#if defined(_WIN32)
"""
rep(opendir_anchor, opendir_block, "PS2 fioDopen")

rep(
"""bool retro_vfs_readdir_impl(libretro_vfs_implementation_dir *rdir)
{
#ifdef HAVE_SMBCLIENT
""",
"""bool retro_vfs_readdir_impl(libretro_vfs_implementation_dir *rdir)
{
#if defined(PS2)
   if (rdir && rdir->ps2_cdfs)
   {
      memset(&rdir->ps2_cdfs_entry, 0, sizeof(rdir->ps2_cdfs_entry));
      return fioDread(rdir->ps2_cdfs_dir, &rdir->ps2_cdfs_entry) > 0;
   }
#endif
#ifdef HAVE_SMBCLIENT
""",
"PS2 fioDread")

rep(
"""const char *retro_vfs_dirent_get_name_impl(libretro_vfs_implementation_dir *rdir)
{
#ifdef HAVE_SMBCLIENT
""",
"""const char *retro_vfs_dirent_get_name_impl(libretro_vfs_implementation_dir *rdir)
{
#if defined(PS2)
   if (rdir && rdir->ps2_cdfs)
      return rdir->ps2_cdfs_entry.name;
#endif
#ifdef HAVE_SMBCLIENT
""",
"PS2 directory entry name")

rep(
"""bool retro_vfs_dirent_is_dir_impl(libretro_vfs_implementation_dir *rdir)
{
#ifdef HAVE_SMBCLIENT
""",
"""bool retro_vfs_dirent_is_dir_impl(libretro_vfs_implementation_dir *rdir)
{
#if defined(PS2)
   if (rdir && rdir->ps2_cdfs)
      return FIO_SO_ISDIR(rdir->ps2_cdfs_entry.stat.mode);
#endif
#ifdef HAVE_SMBCLIENT
""",
"PS2 directory type")

rep(
"""int retro_vfs_dirent_stat_impl(libretro_vfs_implementation_dir *rdir,
      int64_t *size, int64_t *mtime)
{
   if (!rdir)
      return 0;
#ifdef HAVE_SMBCLIENT
""",
"""int retro_vfs_dirent_stat_impl(libretro_vfs_implementation_dir *rdir,
      int64_t *size, int64_t *mtime)
{
   if (!rdir)
      return 0;
#if defined(PS2)
   if (rdir->ps2_cdfs)
   {
      int ret = RETRO_VFS_STAT_IS_VALID | RETRO_VFS_STAT_IS_READONLY;
      if (size)
         *size = ((int64_t)rdir->ps2_cdfs_entry.stat.hisize << 32)
               | rdir->ps2_cdfs_entry.stat.size;
      if (mtime)
         *mtime = 0;
      if (FIO_SO_ISDIR(rdir->ps2_cdfs_entry.stat.mode))
         ret |= RETRO_VFS_STAT_IS_DIRECTORY;
      return ret;
   }
#endif
#ifdef HAVE_SMBCLIENT
""",
"PS2 directory stat")

rep(
"""int retro_vfs_closedir_impl(libretro_vfs_implementation_dir *rdir)
{
   int ret = 0;

   if (!rdir)
      return -1;

#ifdef HAVE_SMBCLIENT
""",
"""int retro_vfs_closedir_impl(libretro_vfs_implementation_dir *rdir)
{
   int ret = 0;

   if (!rdir)
      return -1;

#if defined(PS2)
   if (rdir->ps2_cdfs)
   {
      if (rdir->ps2_cdfs_dir >= 0)
         fioDclose(rdir->ps2_cdfs_dir);
      if (rdir->orig_path)
         free(rdir->orig_path);
      free(rdir);
      return 0;
   }
#endif

#ifdef HAVE_SMBCLIENT
""",
"PS2 fioDclose")

p.write_text(s)
print("Applied PS2 CDFS directory browsing patches")
