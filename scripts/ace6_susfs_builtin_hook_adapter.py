#!/usr/bin/env python3
"""Review-locked one-line SUSFS hook interface adaptation for Ace 6 / SukiSU builtin.

Only rewrites the '+' (added) lines of pinned ShirkNeko SUSFS v2.3.0
android15-6.6 patch to the APIs actually present in pinned SukiSU builtin.
No hunk/context/source removals, fuzzy patching or version deception.
"""
from __future__ import annotations

import argparse
import hashlib
from pathlib import Path

SUSFS_PIN_BLOB = "f0de29699ccafe6e01763e1212f854d7482747fe"

CHANGES = (
    ("+extern struct static_key_true ksu_is_input_hook_enabled;\n",
     "+extern bool ksu_input_hook;\n", 1),
    ("+\tif (static_branch_unlikely(&ksu_is_input_hook_enabled))\n",
     "+\tif (READ_ONCE(ksu_input_hook))\n", 1),
    ("+extern struct static_key_true ksu_su_compat_enabled;\n",
     "+extern bool ksu_su_compat_enabled;\n", 3),
    ("+\tif (static_branch_likely(&ksu_su_compat_enabled)) {\n",
     "+\tif (READ_ONCE(ksu_su_compat_enabled)) {\n", 3),
    ("+extern struct static_key_true ksu_is_init_rc_hook_enabled;\n",
     "+extern bool ksu_vfs_read_hook;\n", 2),
    ("+\tif (static_branch_unlikely(&ksu_is_init_rc_hook_enabled))\n",
     "+\tif (READ_ONCE(ksu_vfs_read_hook))\n", 2),
    ("+extern __attribute__((cold)) void ksu_handle_sys_read(unsigned int fd);\n",
     "+extern int ksu_handle_sys_read(unsigned int fd, char __user **buf_ptr, size_t *count_ptr);\n", 1),
    ("+\t\tksu_handle_sys_read(fd);\n",
     "+\t\tksu_handle_sys_read(fd, NULL, NULL);\n", 1),
)


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def transform(patch: str) -> str:
    src = patch
    for old, new, count in CHANGES:
        actual = src.count(old)
        if actual != count:
            raise ValueError(f"Pinned SUSFS patch interface drifted: {old!r}, expected {count}, got {actual}")
        if not old.startswith("+") or not new.startswith("+") or old.count("\n") != new.count("\n"):
            raise ValueError("Unsafe patch modification")
        src = src.replace(old, new)
    if src.count("diff --git ") != patch.count("diff --git "):
        raise ValueError("Diff file sections lost")
    if any("ksu_is_init_rc_hook_enabled" in line or
           "ksu_is_input_hook_enabled" in line or
           "static_branch_likely(&ksu_su_compat_enabled)" in line
           for line in src.splitlines() if line.startswith("+") and not line.startswith("+++")):
        raise ValueError("Unreconciled SukiSU hook remains in added lines")
    return src


def adapt(src: Path, output: Path) -> None:
    if output.exists():
        raise ValueError("Output exists; refusing overwrite")
    data = src.read_bytes()
    if git_blob(data) != SUSFS_PIN_BLOB:
        raise ValueError("SUSFS patch source fingerprint drifted")
    modified = transform(data.decode("utf-8"))
    output.write_text(modified, encoding="utf-8", newline="\n")
    print("PASS: SUSFS 2.3.0 additions adapted to actual SukiSU builtin bool/3-argument APIs")
    print("Original Git blob:", git_blob(data))
    print("Prepared patch SHA256:", hashlib.sha256(output.read_bytes()).hexdigest())


def selftest() -> None:
    fixture = "diff --git a/x b/x\n" + "".join(old * count for old, _, count in CHANGES)
    result = transform(fixture)
    assert "ksu_handle_sys_read(fd, NULL, NULL)" in result
    assert "extern bool ksu_su_compat_enabled" in result
    assert "static_branch_likely(&ksu_su_compat_enabled)" not in result
    for old, _, _ in CHANGES:
        try:
            transform(fixture.replace(old, "", 1))
        except ValueError:
            pass
        else:
            raise AssertionError("Expected source mismatch to fail: " + old)
    print("PASS: strict positive/negative SUSFS hook interface regression tests")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["selftest", "adapt"])
    p.add_argument("source", nargs="?", type=Path)
    p.add_argument("destination", nargs="?", type=Path)
    args = p.parse_args()
    if args.cmd == "selftest":
        selftest()
    elif not args.source or not args.destination:
        p.error("adapt requires original patch and new destination")
    else:
        adapt(args.source, args.destination)
