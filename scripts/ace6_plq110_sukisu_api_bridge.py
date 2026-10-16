#!/usr/bin/env python3
"""Minimal pinned SUSFS inline-hook ABI bridge for OnePlus Ace6 6.6.118.

cctv18 SUSFS oki-android15-6.6 3f6aae expects an old SukiSU static key
variable for sucompat. Official builtin c95d6e2 instead declares a bool
ksu_su_compat_enabled. Interpreting bool as static_key risks memory corruption.
This changes ONLY that 3-file predicate to READ_ONCE(bool) without removing
security checks or disabling hooks. Never flashes or operates on a phone.
"""
from __future__ import annotations
import argparse
import hashlib
import pathlib
import subprocess

COMMON_PIN = "65b954a773b183a9999b06bb1b2f921f12eaaf11"
SUKISU_PIN = "c95d6e2c76adb11b0e438e518e32ac4e31f5b1d0"
FILES = ("fs/exec.c", "fs/open.c", "fs/stat.c")
OLD_DECL = "extern struct static_key_true ksu_su_compat_enabled;"
NEW_DECL = "extern bool ksu_su_compat_enabled;"
OLD_CALL = "static_branch_likely(&ksu_su_compat_enabled)"
NEW_CALL = "READ_ONCE(ksu_su_compat_enabled)"


def exact_replace(s: str, old: str, new: str, filename: str) -> str:
    n = s.count(old)
    if n != 1:
        raise ValueError(f"{filename}: source API drift for {old!r}, count {n}")
    return s.replace(old, new, 1)


def bridge(s: str, filename: str) -> str:
    s = exact_replace(s, OLD_DECL, NEW_DECL, filename)
    s = exact_replace(s, OLD_CALL, NEW_CALL, filename)
    if OLD_DECL in s or OLD_CALL in s:
        raise ValueError(f"{filename}: old bool/static-key API mismatch remains")
    return s


def git_hash(tree: pathlib.Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=tree, text=True).strip()


def apply(root: pathlib.Path, suki: pathlib.Path) -> None:
    root = root.resolve()
    suki = suki.resolve()
    if git_hash(root, "rev-parse", "HEAD") != COMMON_PIN:
        raise ValueError("Ace6 source commit does not match reviewed .401 source")
    if git_hash(suki, "rev-parse", "HEAD") != SUKISU_PIN:
        raise ValueError("SukiSU builtin commit is not the reviewed revision")
    source = (suki / "kernel/feature/sucompat.c").read_text(encoding="utf-8")
    header = (suki / "kernel/feature/sucompat.h").read_text(encoding="utf-8")
    if "bool ksu_su_compat_enabled __read_mostly = true;" not in source:
        raise ValueError("Official builtin sucompat bool implementation changed")
    if "extern bool ksu_su_compat_enabled;" not in header:
        raise ValueError("Official builtin sucompat public ABI changed")
    if not (root / "include/linux/susfs.h").is_file():
        raise ValueError("SUSFS inline source files are missing")
    before = {p: (root / p).read_text(encoding="utf-8") for p in FILES}
    result = {p: bridge(before[p], p) for p in FILES}
    for p, contents in result.items():
        (root / p).write_text(contents, encoding="utf-8")
    print("PASS: verified SUSFS/SukiSU bool ABI bridge in 3 kernel sources")
    for p in FILES:
        print(p, hashlib.sha256((root / p).read_bytes()).hexdigest())


def selftest() -> None:
    stub = f"#ifdef CONFIG_KSU_SUSFS\n{OLD_DECL}\n{OLD_CALL}\n#endif\n"
    for file in FILES:
        out = bridge(stub, file)
        assert NEW_DECL in out and NEW_CALL in out
        assert "CONFIG_KSU_SUSFS" in out
        for bad in (stub.replace(OLD_DECL, ""),
                    stub.replace(OLD_CALL, ""),
                    stub + OLD_CALL + "\n"):
            try:
                bridge(bad, file)
            except ValueError:
                pass
            else:
                raise AssertionError("Unsafe source variant accepted")
    print("PASS: source bridge and malformed API negative tests")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=("selftest", "apply"))
    p.add_argument("kernel_tree", nargs="?", type=pathlib.Path)
    p.add_argument("sukisu_tree", nargs="?", type=pathlib.Path)
    args = p.parse_args()
    if args.mode == "selftest":
        selftest()
    elif args.kernel_tree is None or args.sukisu_tree is None:
        p.error("apply requires kernel_tree and sukisu_tree")
    else:
        apply(args.kernel_tree, args.sukisu_tree)
