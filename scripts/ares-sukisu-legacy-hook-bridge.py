#!/usr/bin/env python3
"""Pin-locked Ares (MT6893, Linux4.14) manual-hook interface bridge for SukiSU builtin.
The old ReSukiSU kernel callsites use userspace filename pointers and static
keys. SukiSU builtin c95d6e2 expects kernel struct filename pointers and
ordinary bool flags. Never silently mix their ABI; preserve su authorization
and legacy userspace path handling. No optional hooks or privilege checks
removed. Does not flash any device.
"""
from __future__ import annotations
import argparse
import pathlib
import subprocess
import sys

ARES_PIN = "51493fdd25984d3c2f7c6bd1bcaec9775430f4c0"
SUKI_PIN = "c95d6e2c76adb11b0e438e518e32ac4e31f5b1d0"
ARES_BLOBS = {
    "fs/open.c": "3a79a3f5525cdeb7dd4e1351188673fec4a573bb",
    "fs/exec.c": "bb110e092c2945bc9067218b6f86ba3289866e04",
    "fs/stat.c": "dd32b8587a05e4936060e856351ab62582fce951",
    "fs/read_write.c": "1a4550a36f3bbfb8c7ff0ab51c16613866867c37",
}
SUKI_BLOBS = {
    "kernel/feature/sucompat.c": "5866c76efa44fc38cfb5c9ba4a0442ad0295003c",
    "kernel/feature/sucompat.h": "1846cdcafd9b1569c45cf36718ddbb8942437e40",
}

def exact_replace(data: str, old: str, new: str, count: int = 1) -> str:
    n = data.count(old)
    if n != count:
        raise ValueError(f"Unexpected source shape for {old[:70]!r}: {n} != {count}")
    return data.replace(old, new)


def bridge_suki(src: str, hdr: str) -> tuple[str, str]:
    old1 = ("int ksu_handle_faccessat(int *dfd, struct filename **filename, int *mode,\n"
            "             int *__unused_flags);")
    new1 = ("int ksu_handle_faccessat(int *dfd, const char __user **filename_user, int *mode,\n"
            "             int *__unused_flags);")
    old2 = "int ksu_handle_stat(int *dfd, struct filename **filename, int *flags);"
    new2 = "int ksu_handle_stat(int *dfd, const char __user **filename_user, int *flags);"
    hdr = exact_replace(hdr, old1, new1)
    hdr = exact_replace(hdr, old2, new2)
    start = src.find("int ksu_handle_faccessat(int *dfd, struct filename **filename")
    end = src.find("\n#else\n", start)
    if start < 0 or end < 0 or src[start:end].count("int ksu_handle_stat(") != 1:
        raise ValueError("Pinned SukiSU SUSFS/manual user-hook block changed")
    # The community Ares fs/open.c and fs/stat.c use __user **; forwarding
    # that to a struct filename ** blindly can corrupt memory on boot.
    # Use the same userspace path rewrite that SukiSU's own non-SUSFS branch
    # provides, but keep SUSFS active for the rest of the kernel.
    new = """static bool ares_su_user_path_allowed(const char __user *user_path)
{
    char name[sizeof(su_path)];

    if (!user_path || !READ_ONCE(ksu_su_compat_enabled))
        return false;
    if (!__ksu_is_allow_uid_for_current(current_uid().val) || current_chrooted())
        return false;
    if (copy_from_user(name, user_path, sizeof(name)))
        return false;
    return !memcmp(name, su_path, sizeof(name));
}

int ksu_handle_faccessat(int *dfd, const char __user **filename_user, int *mode,
                        int *__unused_flags)
{
    char __user *replacement;

    if (!filename_user || !ares_su_user_path_allowed(*filename_user))
        return 0;
    replacement = sh_user_path();
    if (replacement)
        *filename_user = replacement;
    return 0;
}

int ksu_handle_stat(int *dfd, const char __user **filename_user, int *flags)
{
    char __user *replacement;

    if (!filename_user || !ares_su_user_path_allowed(*filename_user))
        return 0;
    replacement = sh_user_path();
    if (replacement)
        *filename_user = replacement;
    return 0;
}
"""
    src = src[:start] + new + src[end:]
    if "ares_su_user_path_allowed" not in src:
        raise ValueError("Legacy path adapter not installed")
    return src, hdr


def bridge_ares(srcs: dict[str, str]) -> dict[str, str]:
    result = dict(srcs)
    for file in ["fs/open.c", "fs/exec.c"]:
        s = result[file]
        s = exact_replace(s,
                          "extern struct static_key_true ksu_su_compat_enabled;",
                          "extern bool ksu_su_compat_enabled;")
        s = exact_replace(s,
                          "static_branch_likely(&ksu_su_compat_enabled)",
                          "READ_ONCE(ksu_su_compat_enabled)")
        result[file] = s
    for file in ["fs/stat.c", "fs/read_write.c"]:
        s = result[file]
        s = exact_replace(s,
                          "extern struct static_key_true ksu_is_init_rc_hook_enabled;",
                          "extern bool ksu_vfs_read_hook;")
        s = exact_replace(s,
                          "static_branch_unlikely(&ksu_is_init_rc_hook_enabled)",
                          "READ_ONCE(ksu_vfs_read_hook)")
        result[file] = s
    for file in result:
        if "static_branch_likely(&ksu_su_compat_enabled)" in result[file]:
            raise ValueError("Old static key binding remains: "+file)
        if "ksu_is_init_rc_hook_enabled" in result[file]:
            raise ValueError("Old unavailable init static key remains: "+file)
    return result


def run_git(where: pathlib.Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=where, text=True).strip()


def apply(ares: pathlib.Path) -> None:
    ares = ares.resolve()
    suki = ares / "KernelSU"
    if run_git(ares, "rev-parse", "HEAD") != ARES_PIN:
        raise ValueError("Ares source does not match reviewed commit")
    if run_git(suki, "rev-parse", "HEAD") != SUKI_PIN:
        raise ValueError("SukiSU source does not match reviewed commit")
    for root, pins in ((ares, ARES_BLOBS), (suki, SUKI_BLOBS)):
        for rel, sha in pins.items():
            p = root / rel
            if not p.is_file() or run_git(root, "hash-object", rel) != sha:
                raise ValueError("Unexpected modified source before patch: "+str(p))
    ares_orig = {p: (ares / p).read_text(encoding="utf-8") for p in ARES_BLOBS}
    suki_orig = {p: (suki / p).read_text(encoding="utf-8") for p in SUKI_BLOBS}
    ares_new = bridge_ares(ares_orig)
    sc, sh = bridge_suki(suki_orig["kernel/feature/sucompat.c"],
                          suki_orig["kernel/feature/sucompat.h"])
    for p, value in ares_new.items():
        (ares / p).write_text(value, encoding="utf-8")
    (suki / "kernel/feature/sucompat.c").write_text(sc, encoding="utf-8")
    (suki / "kernel/feature/sucompat.h").write_text(sh, encoding="utf-8")
    print("PASS: Ares userspace hooks match latest SukiSU builtin; no static-key ABI mismatch")


def selftest() -> None:
    head = ("int ksu_handle_faccessat(int *dfd, struct filename **filename, int *mode,\n"
            "             int *__unused_flags);\n"
            "int ksu_handle_stat(int *dfd, struct filename **filename, int *flags);\n")
    sc = ("static bool helper(void){}\n"
          "int ksu_handle_faccessat(int *dfd, struct filename **filename, int *mode,\n"
          " int *__unused_flags) { return 0; }\n"
          "int ksu_handle_stat(int *dfd, struct filename **filename, int *flags) { return 0; }\n"
          "\n#else\n")
    patched_c, patched_h = bridge_suki(sc, head)
    assert "ares_su_user_path_allowed" in patched_c
    assert patched_h.count("const char __user **filename_user") == 2
    aliases = {
        "fs/open.c": "extern struct static_key_true ksu_su_compat_enabled;\nstatic_branch_likely(&ksu_su_compat_enabled)",
        "fs/exec.c": "extern struct static_key_true ksu_su_compat_enabled;\nstatic_branch_likely(&ksu_su_compat_enabled)",
        "fs/stat.c": "extern struct static_key_true ksu_is_init_rc_hook_enabled;\nstatic_branch_unlikely(&ksu_is_init_rc_hook_enabled)",
        "fs/read_write.c": "extern struct static_key_true ksu_is_init_rc_hook_enabled;\nstatic_branch_unlikely(&ksu_is_init_rc_hook_enabled)",
    }
    result=bridge_ares(aliases)
    assert all("READ_ONCE" in data for data in result.values())
    for broken in ((sc.replace("ksu_handle_stat(", "missing("), head),
                   (sc, head.replace("struct filename **filename", "void **filename"))):
        try:
            bridge_suki(*broken)
        except ValueError:
            pass
        else:
            raise AssertionError("Unsafe interface mismatch accepted")
    print("PASS: Ares/Suki manual ABI transformation and negative regression tests")


if __name__ == "__main__":
    p=argparse.ArgumentParser()
    p.add_argument("op", choices=["selftest","apply"])
    p.add_argument("ares_root", type=pathlib.Path, nargs="?")
    args=p.parse_args()
    try:
        if args.op=="selftest":
            selftest()
        elif args.ares_root is None:
            p.error("apply requires source tree")
        else:
            apply(args.ares_root)
    except (ValueError,OSError,subprocess.CalledProcessError) as err:
        sys.exit("::error::Ares legacy hook ABI incompatible: "+str(err))
