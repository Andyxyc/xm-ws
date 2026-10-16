#!/usr/bin/env python3
"""Bridge SukiSU SUSFS sucompat pathname hooks to alioth's non-GKI syscall ABI.

Pinned SukiSU c95d6e2's CONFIG_KSU_SUSFS implementation expects
struct filename **, while alioth's fs/open.c and fs/stat.c manual hooks
pass const char __user **.  C linking doesn't detect this mismatch.
Preserve the SukiSU root authorization path and change only these
two exact source-level syscall hooks, not any vendor scheduler/driver.
"""
from __future__ import annotations
import argparse
import re
import subprocess
import sys
from pathlib import Path

PIN = "c95d6e2c76adb11b0e438e518e32ac4e31f5b1d0"
EXPECTED = {
    "kernel/feature/sucompat.c": "5866c76efa44fc38cfb5c9ba4a0442ad0295003c",
    "kernel/feature/sucompat.h": "1846cdcafd9b1569c45cf36718ddbb8942437e40",
}
START = "int ksu_handle_faccessat(int *dfd, struct filename **filename, int *mode,"
END = "\n#else\n__attribute__((hot)) static __always_inline bool __is_su_allowed"
HEADER_OLD = """int ksu_handle_faccessat(int *dfd, struct filename **filename, int *mode,
             int *__unused_flags);
int ksu_handle_stat(int *dfd, struct filename **filename, int *flags);"""
HEADER_NEW = """int ksu_handle_faccessat(int *dfd, const char __user **filename_user, int *mode,
             int *__unused_flags);
int ksu_handle_stat(int *dfd, const char __user **filename_user, int *flags);"""

# Match SukiSU's own non-SUSFS user-path lookup and su->sh redirection, not
# the struct filename ** implementation that is invalid at alioth syscall site.
REPLACEMENT = r"""/* alioth Linux 4.19 manual syscall ABI: const char __user **.  This
 * SUSFS-enabled hook must not dereference the syscall's user pointer as a
 * kernel struct filename.  Keep both root/profile and chroot checks.
 */
static int ksu_alioth_susfs_su_user_path(const char __user **filename_user)
{
    char path[sizeof(su_path)] = { 0 };
    char __user *sh;
    long length;

    if (!ksu_su_compat_enabled || !filename_user || !*filename_user)
        return 0;
    if (unlikely(!__ksu_is_allow_uid_for_current(current_uid().val)))
        return 0;
    if (unlikely(current_chrooted()))
        return 0;

    length = ksu_strncpy_from_user_nofault(path, *filename_user, sizeof(path));
    if (length <= 0 || memcmp(path, su_path, sizeof(su_path)))
        return 0;

    sh = sh_user_path();
    if (sh)
        *filename_user = sh;
    return 0;
}

int ksu_handle_faccessat(int *dfd, const char __user **filename_user, int *mode,
                         int *__unused_flags)
{
    return ksu_alioth_susfs_su_user_path(filename_user);
}

int ksu_handle_stat(int *dfd, const char __user **filename_user, int *flags)
{
    return ksu_alioth_susfs_su_user_path(filename_user);
}
"""


def transform(code: str, header: str) -> tuple[str, str]:
    if code.count(START) != 1 or code.count(END) != 1:
        raise ValueError("Pinned SUSFS code layout changed")
    a, b = code.index(START), code.index(END)
    if b <= a:
        raise ValueError("Unexpected SUSFS syscall function order")
    original = code[a:b]
    for item in (
        "int ksu_handle_stat(int *dfd, struct filename **filename, int *flags)",
        "current_chrooted()",
        "su_path",
        "sh_path",
    ):
        if item not in original:
            raise ValueError("Unexpected SUSFS source body: " + item)
    if header.count(HEADER_OLD) != 1:
        raise ValueError("Unexpected SukiSU sucompat prototype")
    new_code = code[:a] + REPLACEMENT + code[b:]
    new_header = header.replace(HEADER_OLD, HEADER_NEW)
    for check in ("ksu_is_allow_uid_for_current", "sh_user_path", "ksu_su_compat_enabled"):
        if check not in new_code:
            raise ValueError("Authorization behavior missing: " + check)
    if re.search(r'int ksu_handle_(?:stat|faccessat)\([^\n]+struct filename \*\*', new_code):
        raise ValueError("Original incompatible signature remains")
    return new_code, new_header


def verify_alioth(tree: Path) -> None:
    candidates = {
        "fs/open.c": "const char __user **filename_user",
        "fs/stat.c": "const char __user **filename_user",
        "kernel/ksu_manual_hook.c": "const char __user **filename_user",
    }
    for path, token in candidates.items():
        data = (tree / path).read_text()
        if token not in data:
            raise ValueError("Alioth manual hook ABI changed: " + path)


def apply(root: Path, kernel: Path) -> None:
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip() != PIN:
        raise ValueError("Not the pinned SukiSU source")
    for rel, expected in EXPECTED.items():
        actual = subprocess.check_output(["git", "hash-object", rel], cwd=root, text=True).strip()
        if actual != expected:
            raise ValueError("SukiSU blob changed: " + rel + ": " + actual)
    verify_alioth(kernel)
    p = root / "kernel/feature/sucompat.c"
    h = root / "kernel/feature/sucompat.h"
    code, header = transform(p.read_text(), h.read_text())
    p.write_text(code)
    h.write_text(header)
    print("PASS: SUSFS-enabled K40 faccessat/newfstatat manual ABI and root profile validated")


def selftest() -> None:
    source = START + """\n{\n if (current_chrooted()) return 0;\n memcpy(path, su_path, sizeof(su_path));\n memcpy(path, sh_path, sizeof(sh_path));\n}\nint ksu_handle_stat(int *dfd, struct filename **filename, int *flags)\n{\n if (current_chrooted()) return 0;\n}\n""" + END
    header = HEADER_OLD
    c, h = transform(source, header)
    assert "const char __user **filename_user" in c
    assert "struct filename **filename" not in c
    assert "int ksu_handle_stat(int *dfd, const char __user **filename_user" in h
    for broken in [(source.replace(START, "x"), header), (source, header.replace(HEADER_OLD, "x"))]:
        try:
            transform(*broken)
        except ValueError:
            pass
        else:
            raise AssertionError("Unexpected upstream ABI accepted")
    print("PASS: positive/negative source ABI unit tests")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("operation", choices=["selftest", "apply"])
    p.add_argument("sukisu_tree", type=Path, nargs="?")
    p.add_argument("kernel_tree", type=Path, nargs="?")
    args = p.parse_args()
    try:
        if args.operation == "selftest":
            selftest()
        elif args.sukisu_tree is None or args.kernel_tree is None:
            p.error("apply requires SukiSU and alioth kernel tree")
        else:
            apply(args.sukisu_tree, args.kernel_tree)
    except (ValueError, OSError, subprocess.CalledProcessError) as e:
        sys.exit("::error::K40 SUSFS syscall ABI check failed: " + str(e))
