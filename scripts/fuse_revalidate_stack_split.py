#!/usr/bin/env python3
from pathlib import Path
import sys

root = Path(sys.argv[1] if len(sys.argv) > 1 else ".")
path = root / "fs/fuse/dir.c"
text = path.read_text()

helper_name = "fuse_bpf_lookup_revalidate_run"
if helper_name in text:
    raise SystemExit("FUSE revalidate stack split already present")

old_block = """		if (get_fuse_inode(parent->d_inode)->backing_inode) {
			struct inode *dir = parent->d_inode;
			struct fuse_err_ret fer;

			fer = fuse_bpf_backing(dir, struct fuse_lookup_io,
						fuse_lookup_revalidate_initialize,
						fuse_lookup_revalidate_backing,
						fuse_lookup_revalidate_finalize,
						dir, entry, flags);
			dput(parent);
			if (fer.ret && PTR_ERR(fer.result))
				ret = PTR_ERR(fer.result);
			else
				ret = 1;
			goto out;
		}
"""

new_block = """		if (get_fuse_inode(parent->d_inode)->backing_inode) {
			ret = fuse_bpf_lookup_revalidate_run(parent->d_inode, entry, flags);
			dput(parent);
			goto out;
		}
"""

if text.count(old_block) != 1:
    raise SystemExit(f"revalidate inline block mismatch: {text.count(old_block)}")

anchor = """/*
 * Check whether the dentry is still valid
 *
 * If the entry validity timeout has expired and the dentry is
"""

helper = """#ifdef CONFIG_FUSE_BPF
/*
 * Keep fuse_bpf_backing() out of fuse_dentry_revalidate(). The macro owns a
 * fuse_lookup_io scratch object; isolating it here keeps the caller below the
 * kernel's 2 KiB stack-frame limit on Android 16 / Linux 6.12.
 */
static int fuse_bpf_lookup_revalidate_run(struct inode *dir,
					  struct dentry *entry,
					  unsigned int flags)
{
	struct fuse_err_ret fer;

	fer = fuse_bpf_backing(dir, struct fuse_lookup_io,
			       fuse_lookup_revalidate_initialize,
			       fuse_lookup_revalidate_backing,
			       fuse_lookup_revalidate_finalize,
			       dir, entry, flags);
	if (fer.ret && PTR_ERR(fer.result))
		return PTR_ERR(fer.result);
	return 1;
}
#endif

"""

if text.count(anchor) != 1:
    raise SystemExit(f"revalidate helper anchor mismatch: {text.count(anchor)}")

text = text.replace(anchor, helper + anchor, 1)
text = text.replace(old_block, new_block, 1)
path.write_text(text)
print("FUSE lookup_revalidate BPF scratch stack isolated")
