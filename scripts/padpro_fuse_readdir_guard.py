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
    '#include <linux/highmem.h>\n#include <linux/cred.h>\n#include <linux/uidgid.h>\n#include <linux/nls.h>\n#include <linux/string.h>\n',
    "credential includes",
)

helper = r'''
/*
 * Android/data and Android/obb are app-private namespace roots. Third-party app
 * UIDs must not enumerate those parent directories; direct child lookup remains
 * governed by the normal MediaProvider/FUSE policy.
 *
 * This guard intentionally lives above both FUSE-BPF and userspace readdir
 * paths, so it also covers older OnePlus kernels without CONFIG_FUSE_BPF.
 */
static bool fuse_readdir_default_ignorable(unicode_t ch)
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

static size_t fuse_readdir_filter_component(const char *src, size_t len,
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
			dst[out++] = src[in++];
			continue;
		}

		if (!fuse_readdir_default_ignorable(ch)) {
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

static bool fuse_component_eq_ascii(const struct qstr *q, const char *literal)
{
	char filtered[FUSE_NAME_MAX + 1];
	size_t len;
	size_t literal_len = strlen(literal);

	len = fuse_readdir_filter_component(q->name, q->len, filtered, sizeof(filtered));
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
print("OnePlus Android/data + Android/obb app-UID readdir guard applied")
