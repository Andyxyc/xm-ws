#!/usr/bin/env python3
from pathlib import Path
import sys

ROOT = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
TARGET = ROOT / "fs/fuse/readdir.c"

def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)

text = TARGET.read_text()

if "fuse_android_private_dir_readdir_denied" in text:
    raise SystemExit("Pad Pro Android/data readdir guard already present; refusing double-apply")

text = replace_once(
    text,
    '#include <linux/highmem.h>\n',
    '#include <linux/highmem.h>\n#include <linux/cred.h>\n#include <linux/uidgid.h>\n',
    "credential includes",
)

helper = r'''
/*
 * Android/data and Android/obb are app-private namespace roots. Third-party app
 * UIDs must not enumerate those parent directories; direct child lookup remains
 * governed by the normal MediaProvider/FUSE policy.
 *
 * This guard intentionally lives above both FUSE-BPF and userspace readdir
 * paths, so it also covers ROMs where fuse-bpf is compiled in but not active.
 * Component matching strips Unicode Default_Ignorable_Code_Point values with
 * the same helper used by the Pad Pro lookup hardening, then compares ASCII
 * case-insensitively.
 */
static bool fuse_component_eq_ascii(const struct qstr *q, const char *literal)
{
	char filtered[FUSE_NAME_MAX + 1];
	size_t len;
	size_t literal_len = strlen(literal);

	len = fuse_filter_lookup_name(q->name, q->len, filtered, sizeof(filtered));
	return len == literal_len && !strncasecmp(filtered, literal, literal_len);
}

static bool fuse_is_android_app_private_dir(struct dentry *dentry)
{
	struct dentry *parent;

	if (!dentry)
		return false;

	parent = READ_ONCE(dentry->d_parent);
	if (!parent || parent == dentry)
		return false;

	if (!fuse_component_eq_ascii(&parent->d_name, "Android"))
		return false;

	return fuse_component_eq_ascii(&dentry->d_name, "data") ||
	       fuse_component_eq_ascii(&dentry->d_name, "obb");
}

static bool fuse_android_private_dir_readdir_denied(struct file *file)
{
	uid_t uid = from_kuid_munged(&init_user_ns, current_fsuid());

	/* Android application UIDs start at 10000. System/root/shell remain intact. */
	if (uid < 10000)
		return false;

	return fuse_is_android_app_private_dir(file->f_path.dentry);
}
'''

text = replace_once(
    text,
    'static bool fuse_use_readdirplus(struct inode *dir, struct dir_context *ctx)\n',
    helper + '\nstatic bool fuse_use_readdirplus(struct inode *dir, struct dir_context *ctx)\n',
    "readdir guard helper insertion",
)

text = replace_once(
    text,
    'int fuse_readdir(struct file *file, struct dir_context *ctx)\n{\n\tstruct fuse_file *ff = file->private_data;\n\tstruct inode *inode = file_inode(file);\n\tint err;\n',
    'int fuse_readdir(struct file *file, struct dir_context *ctx)\n{\n\tstruct fuse_file *ff = file->private_data;\n\tstruct inode *inode = file_inode(file);\n\tint err;\n\n\tif (fuse_android_private_dir_readdir_denied(file))\n\t\treturn -EACCES;\n',
    "readdir early deny",
)

TARGET.write_text(text)
print("Pad Pro Android/data + Android/obb app-UID readdir guard applied")
