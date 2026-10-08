#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
DIR = ROOT / "fs/fuse/dir.c"
HDR = ROOT / "fs/fuse/fuse_i.h"
BACK = ROOT / "fs/fuse/backing.c"

def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)

dir_c = DIR.read_text()
hdr = HDR.read_text()
back = BACK.read_text()

# Linux 6.12's fuse_dentry_revalidate is already close to the 2 KiB frame
# limit. The generic storage hardening used FUSE_NAME_MAX+1 scratch buffers,
# including one embedded in struct fuse_lookup_io, which pushes the frame over
# the limit. Android's protected components we normalize here are tiny
# ("Android", "data", "obb" plus one or more ignorable UTF-8 codepoints), so a
# bounded scratch buffer is sufficient; longer names fall back to the original
# raw qstr instead of being truncated.

dir_c = dir_c.replace(
    "char filtered_name[FUSE_NAME_MAX + 1];",
    "char filtered_name[64];",
)
if dir_c.count("char filtered_name[64];") < 2:
    raise SystemExit("dir.c: expected two bounded lookup scratch buffers")

old = """\t\tlookup_name.len = fuse_filter_lookup_name(entry->d_name.name,
\t\t\t\tentry->d_name.len, filtered_name, sizeof(filtered_name));
\t\tlookup_name.name = filtered_name;
"""
new = """\t\tif (entry->d_name.len < sizeof(filtered_name)) {
\t\t\tlookup_name.len = fuse_filter_lookup_name(entry->d_name.name,
\t\t\t\t\tentry->d_name.len, filtered_name, sizeof(filtered_name));
\t\t\tlookup_name.name = filtered_name;
\t\t}
"""
dir_c = replace_once(dir_c, old, new, "revalidate bounded normalization")

old = """\tlookup_name.len = fuse_filter_lookup_name(name->name, name->len,
\t\t\tfiltered_name, sizeof(filtered_name));
\tlookup_name.name = filtered_name;
"""
new = """\tif (name->len < sizeof(filtered_name)) {
\t\tlookup_name.len = fuse_filter_lookup_name(name->name, name->len,
\t\t\t\tfiltered_name, sizeof(filtered_name));
\t\tlookup_name.name = filtered_name;
\t}
"""
dir_c = replace_once(dir_c, old, new, "lookup bounded normalization")

hdr = replace_once(
    hdr,
    "\tchar filtered_name[FUSE_NAME_MAX + 1];\n\tsize_t filtered_name_len;\n",
    "\tchar filtered_name[64];\n\tsize_t filtered_name_len;\n",
    "lookup io bounded buffer",
)

old = """\tfli->filtered_name_len = fuse_filter_lookup_name(entry->d_name.name,
\t\t\tentry->d_name.len, fli->filtered_name,
\t\t\tsizeof(fli->filtered_name));

\t*fa = (struct fuse_bpf_args) {
"""
new = """\tif (entry->d_name.len < sizeof(fli->filtered_name))
\t\tfli->filtered_name_len = fuse_filter_lookup_name(entry->d_name.name,
\t\t\t\tentry->d_name.len, fli->filtered_name,
\t\t\t\tsizeof(fli->filtered_name));
\telse
\t\tfli->filtered_name_len = (size_t)-1;

\t*fa = (struct fuse_bpf_args) {
"""
back = replace_once(back, old, new, "bpf bounded normalization")

old = """\t\t.in_args[0] = (struct fuse_bpf_in_arg) {
\t\t\t.size = fli->filtered_name_len + 1,
\t\t\t.value = fli->filtered_name,
\t\t},
"""
new = """\t\t.in_args[0] = (struct fuse_bpf_in_arg) {
\t\t\t.size = fli->filtered_name_len != (size_t)-1 ?
\t\t\t\tfli->filtered_name_len + 1 : entry->d_name.len + 1,
\t\t\t.value = fli->filtered_name_len != (size_t)-1 ?
\t\t\t\t(const void *)fli->filtered_name :
\t\t\t\t(const void *)entry->d_name.name,
\t\t},
"""
back = replace_once(back, old, new, "bpf raw-name fallback")

DIR.write_text(dir_c)
HDR.write_text(hdr)
BACK.write_text(back)
print("Xiaomi 6.12 FUSE stack-frame fix applied")
