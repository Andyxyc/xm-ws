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

if "fuse_default_ignorable_code_point" in dir_c:
    raise SystemExit("Pad Pro FUSE name filter already present; refusing double-apply")

dir_c = replace_once(
    dir_c,
    "#include <linux/security.h>\n#include <linux/types.h>",
    "#include <linux/security.h>\n#include <linux/nls.h>\n#include <linux/types.h>",
    "include linux/nls.h",
)

helper = r'''
/*
 * MediaProvider's FUSE daemon historically compares path components without
 * removing Unicode Default_Ignorable_Code_Point values, while the backing
 * casefold filesystem does. Keep the VFS dentry name untouched, but send a
 * filtered component to the FUSE daemon / FUSE-BPF policy path so both layers
 * make the access-control decision from the same logical name.
 */
static bool fuse_default_ignorable_code_point(unicode_t ch)
{
	return ch == 0x00ad ||
	       ch == 0x034f ||
	       ch == 0x061c ||
	       (ch >= 0x115f && ch <= 0x1160) ||
	       (ch >= 0x17b4 && ch <= 0x17b5) ||
	       (ch >= 0x180b && ch <= 0x180e) ||
	       (ch >= 0x200b && ch <= 0x200f) ||
	       (ch >= 0x202a && ch <= 0x202e) ||
	       (ch >= 0x2060 && ch <= 0x206f) ||
	       ch == 0x3164 ||
	       (ch >= 0xfe00 && ch <= 0xfe0f) ||
	       ch == 0xfeff ||
	       ch == 0xffa0 ||
	       (ch >= 0xfff0 && ch <= 0xfff8) ||
	       (ch >= 0x1bca0 && ch <= 0x1bca3) ||
	       (ch >= 0x1d173 && ch <= 0x1d17a) ||
	       (ch >= 0xe0000 && ch <= 0xe0fff);
}

size_t fuse_filter_lookup_name(const char *src, size_t len,
			       char *dst, size_t dst_size)
{
	size_t in = 0, out = 0;

	if (!dst_size)
		return 0;

	while (in < len && out + 1 < dst_size) {
		unicode_t ch;
		int char_len;

		char_len = utf8_to_utf32((const u8 *)src + in, len - in, &ch);
		if (char_len < 0) {
			/* Preserve invalid UTF-8 byte-for-byte. */
			dst[out++] = src[in++];
			continue;
		}

		if (!fuse_default_ignorable_code_point(ch)) {
			if (out + char_len >= dst_size)
				break;
			memcpy(dst + out, src + in, char_len);
			out += char_len;
		}
		in += char_len;
	}

	dst[out] = '\0';
	return out;
}
'''

dir_c = replace_once(
    dir_c,
    '#include "../internal.h"\n\nstatic void fuse_advise_use_readdirplus',
    '#include "../internal.h"\n' + helper + '\nstatic void fuse_advise_use_readdirplus',
    "insert FUSE lookup-name filter helper",
)

dir_c = replace_once(
    dir_c,
    "\t\tstruct fuse_forget_link *forget;\n\t\tu64 attr_version;\n",
    "\t\tstruct fuse_forget_link *forget;\n\t\tu64 attr_version;\n"
    "\t\tchar filtered_name[FUSE_NAME_MAX + 1];\n"
    "\t\tstruct qstr lookup_name = entry->d_name;\n",
    "revalidate scratch buffer",
)

dir_c = replace_once(
    dir_c,
    "\t\tfuse_lookup_init(fm->fc, &args, get_node_id(d_inode(parent)),\n"
    "\t\t\t\t &entry->d_name, &outarg, &bpf_arg.out);",
    "\t\tlookup_name.len = fuse_filter_lookup_name(entry->d_name.name,\n"
    "\t\t\t\tentry->d_name.len, filtered_name, sizeof(filtered_name));\n"
    "\t\tlookup_name.name = filtered_name;\n\n"
    "\t\tfuse_lookup_init(fm->fc, &args, get_node_id(d_inode(parent)),\n"
    "\t\t\t\t &lookup_name, &outarg, &bpf_arg.out);",
    "revalidate filtered lookup",
)

dir_c = replace_once(
    dir_c,
    "\tstruct fuse_forget_link *forget;\n\tu64 attr_version;\n\tint err;\n",
    "\tstruct fuse_forget_link *forget;\n\tu64 attr_version;\n\tint err;\n"
    "\tchar filtered_name[FUSE_NAME_MAX + 1];\n"
    "\tstruct qstr lookup_name = *name;\n",
    "normal lookup scratch buffer",
)

dir_c = replace_once(
    dir_c,
    "\tfuse_lookup_init(fm->fc, &args, nodeid, name, outarg, &bpf_arg.out);",
    "\tlookup_name.len = fuse_filter_lookup_name(name->name, name->len,\n"
    "\t\t\tfiltered_name, sizeof(filtered_name));\n"
    "\tlookup_name.name = filtered_name;\n\n"
    "\tfuse_lookup_init(fm->fc, &args, nodeid, &lookup_name, outarg, &bpf_arg.out);",
    "normal filtered lookup",
)

hdr = replace_once(
    hdr,
    "struct fuse_lookup_io {\n\tstruct fuse_entry_out feo;\n\tstruct fuse_entry_bpf feb;\n};\n",
    "struct fuse_lookup_io {\n\tstruct fuse_entry_out feo;\n\tstruct fuse_entry_bpf feb;\n"
    "\tchar filtered_name[FUSE_NAME_MAX + 1];\n\tsize_t filtered_name_len;\n};\n\n"
    "size_t fuse_filter_lookup_name(const char *src, size_t len,\n"
    "\t\t\t       char *dst, size_t dst_size);\n",
    "lookup io buffer/prototype",
)

back = replace_once(
    back,
    "int fuse_lookup_initialize(struct fuse_bpf_args *fa, struct fuse_lookup_io *fli,\n"
    "\t       struct inode *dir, struct dentry *entry, unsigned int flags)\n"
    "{\n"
    "\t*fa = (struct fuse_bpf_args) {\n"
    "\t\t.nodeid = get_fuse_inode(dir)->nodeid,\n"
    "\t\t.opcode = FUSE_LOOKUP,\n"
    "\t\t.in_numargs = 1,\n"
    "\t\t.out_numargs = 2,\n"
    "\t\t.flags = FUSE_BPF_OUT_ARGVAR,\n"
    "\t\t.in_args[0] = (struct fuse_bpf_in_arg) {\n"
    "\t\t\t.size = entry->d_name.len + 1,\n"
    "\t\t\t.value = entry->d_name.name,\n"
    "\t\t},",
    "int fuse_lookup_initialize(struct fuse_bpf_args *fa, struct fuse_lookup_io *fli,\n"
    "\t       struct inode *dir, struct dentry *entry, unsigned int flags)\n"
    "{\n"
    "\tfli->filtered_name_len = fuse_filter_lookup_name(entry->d_name.name,\n"
    "\t\t\tentry->d_name.len, fli->filtered_name,\n"
    "\t\t\tsizeof(fli->filtered_name));\n\n"
    "\t*fa = (struct fuse_bpf_args) {\n"
    "\t\t.nodeid = get_fuse_inode(dir)->nodeid,\n"
    "\t\t.opcode = FUSE_LOOKUP,\n"
    "\t\t.in_numargs = 1,\n"
    "\t\t.out_numargs = 2,\n"
    "\t\t.flags = FUSE_BPF_OUT_ARGVAR,\n"
    "\t\t.in_args[0] = (struct fuse_bpf_in_arg) {\n"
    "\t\t\t.size = fli->filtered_name_len + 1,\n"
    "\t\t\t.value = fli->filtered_name,\n"
    "\t\t},",
    "BPF lookup filtered initialize block",
)

DIR.write_text(dir_c)
HDR.write_text(hdr)
BACK.write_text(back)

print("Pad Pro FUSE default-ignorable lookup filter applied")
