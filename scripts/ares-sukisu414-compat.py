#!/usr/bin/env python3
"""Small source-validated Linux 4.14 fixes for pinned SukiSU builtin.
Retain real root authorization, manual hooks, SUSFS and native KPM.
Do not suppress compiler errors, spoof versions or disable root features.
"""
from __future__ import annotations
import argparse
import pathlib
import subprocess
import sys

PIN = "c95d6e2c76adb11b0e438e518e32ac4e31f5b1d0"


def exact(data: str, old: str, new: str, count: int) -> str:
    found = data.count(old)
    if found != count:
        raise RuntimeError("Unexpected pinned source shape: %r count %s != %s" % (old, found, count))
    return data.replace(old, new)


def transform(allow: str, ksud: str, sulog: str) -> tuple[str, str, str]:
    allow = exact(allow, "        fallthrough;\n", "        /* fall through */\n", 1)

    call1 = "    ksu_selinux_hide_handle_post_fs_data();"
    ksud = exact(
        ksud, call1,
        "#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 10, 0)\n" + call1 +
        "\n#endif /* SELinux hiding implementation exists only for Linux >=5.10 */", 1
    )
    call2 = "\n                ksu_selinux_hide_handle_second_stage();\n"
    call3 = "\n            ksu_selinux_hide_handle_second_stage();\n"
    for call in (call2, call3):
        ksud = exact(
            ksud, call,
            "#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 10, 0)\n" + call +
            "\n#endif /* Keep second-stage root setup; only gate absent Linux 4.14 helper */\n",
            1
        )
    # Both SUSFS and non-SUSFS branches should compile without an invalid
    # struct user_arg_ptr pointer/value implicit conversion.
    old = "#define USER_ARG_NULL user_arg_null_ptr()"
    new = (
        "#ifdef CONFIG_KSU_SUSFS\n"
        "#define USER_ARG_NULL user_arg_null_ptr()\n"
        "#else\n"
        "#define USER_ARG_NULL (*user_arg_null_ptr())\n"
        "#endif"
    )
    sulog = exact(sulog, old, new, 1)
    return allow, ksud, sulog


def apply(root: pathlib.Path) -> None:
    root = root.resolve()
    current = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    if current != PIN:
        raise RuntimeError("Unknown SukiSU revision: " + current)
    rels = ["kernel/policy/allowlist.c", "kernel/runtime/ksud.c", "kernel/sulog/event.c"]
    original = [ (root / x).read_text(encoding="utf-8") for x in rels ]
    modified = transform(*original)
    if len(original) != len(modified):
        raise RuntimeError("Unexpected compatibility output length")
    for rel, data in zip(rels, modified):
        (root / rel).write_text(data, encoding="utf-8")
    print("PASS: Linux 4.14 fallthrough/SELinux helper/user_arg_ptr compatibility fixed")


def selftest() -> None:
    al = "case 2:\n        fallthrough;\ncase 3:\n"
    ku = (
        "    ksu_selinux_hide_handle_post_fs_data();\n"
        "                ksu_selinux_hide_handle_second_stage();\n"
        "            ksu_selinux_hide_handle_second_stage();\n"
    )
    su = "#define USER_ARG_NULL user_arg_null_ptr()\n"
    patched = transform(al, ku, su)
    assert "/* fall through */" in patched[0]
    assert patched[1].count("KERNEL_VERSION(5, 10, 0)") == 3
    assert "CONFIG_KSU_SUSFS" in patched[2]
    assert "*user_arg_null_ptr()" in patched[2]
    for broken in (
        (al.replace("fallthrough;", ""), ku, su),
        (al, ku.replace("ksu_selinux_hide_handle_post_fs_data();", ""), su),
        (al, ku, su.replace("USER_ARG_NULL", "NO_ARG")),
    ):
        try:
            transform(*broken)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Invalid source accepted")
    print("PASS: pinned-source transforms and negative failure-path tests")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["selftest", "apply"])
    parser.add_argument("tree", nargs="?", type=pathlib.Path)
    a = parser.parse_args()
    try:
        if a.operation == "selftest":
            selftest()
        elif a.tree is None:
            parser.error("apply requires source tree")
        else:
            apply(a.tree)
    except (RuntimeError, ValueError, OSError, subprocess.CalledProcessError) as e:
        sys.exit("::error::ares Linux4.14 compatibility refused: " + str(e))
