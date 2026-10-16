#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Patch-only ABI matching for pinned SukiSU builtin c95 and CCTV18 SUSFS 2.3.

The upstream SUSFS hook patch uses static keys from another KSU implementation.
SukiSU builtin c95 exposes bool flags instead. Keeping static-key accesses
would dereference a bool as a jump-label key and break the boot or compile.
This source-checked adapter changes hook flag access, not privilege policy,
kernel ABI struct layouts, scheduler, firmware module loading or feature IDs.
"""
from __future__ import annotations
import argparse
from pathlib import Path

COUNTS = (
    ("+extern struct static_key_true ksu_su_compat_enabled;",
     "+extern bool ksu_su_compat_enabled;", 3),
    ("+\tif (static_branch_likely(&ksu_su_compat_enabled))",
     "+\tif (READ_ONCE(ksu_su_compat_enabled))", 3),
    ("+extern struct static_key_true ksu_is_init_rc_hook_enabled;",
     "+extern bool ksu_vfs_read_hook;", 2),
    ("+\tif (static_branch_unlikely(&ksu_is_init_rc_hook_enabled))",
     "+\tif (READ_ONCE(ksu_vfs_read_hook))", 2),
    ("+extern struct static_key_true ksu_is_input_hook_enabled;",
     "+extern bool ksu_input_hook;", 1),
    ("+\tif (static_branch_unlikely(&ksu_is_input_hook_enabled))",
     "+\tif (READ_ONCE(ksu_input_hook))", 1),
)

def adjust(text: str) -> str:
    original=len(text.splitlines(keepends=True))
    for a,b,n in COUNTS:
        found=text.count(a)
        if found!=n:
            raise ValueError(f"Unexpected SUSFS/SukiSU hook shape: {a}: found {found}, expected {n}")
        text=text.replace(a,b)
    if len(text.splitlines(keepends=True))!=original:
        raise ValueError("Accidentally changed unified hunk line counts")
    for symbol in ("ksu_is_init_rc_hook_enabled", "ksu_is_input_hook_enabled",
                   "static_branch_likely(&ksu_su_compat_enabled)"):
        if symbol in text:
            raise ValueError(f"Incompatible static-key symbol remains: {symbol}")
    return text

def selftest() -> None:
    s="\n".join(line for old,_,n in COUNTS for line in [old]*n)+"\n"
    t=adjust(s)
    assert "READ_ONCE(ksu_su_compat_enabled)" in t
    assert "READ_ONCE(ksu_vfs_read_hook)" in t
    assert "READ_ONCE(ksu_input_hook)" in t
    try:
        adjust(s.replace(COUNTS[0][0],"",1))
    except ValueError:
        pass
    else:
        raise AssertionError("Incorrect hook source accepted")
    print("PASS: exact SukiSU c95 bool-vs-static-key ABI rewrites and negative guard")

def apply(source: Path, dest: Path) -> None:
    if dest.exists():
        raise ValueError("Output exists; do not replace verified original")
    text=source.read_text(encoding="utf-8")
    dest.write_text(adjust(text),encoding="utf-8",newline="\n")
    print("PASS: SukiSU native hook bool flags reconciled; SUSFS/KPM kept enabled")

if __name__=="__main__":
    arg=argparse.ArgumentParser()
    arg.add_argument("mode",choices=["selftest","apply"])
    arg.add_argument("source",type=Path,nargs="?")
    arg.add_argument("dest",type=Path,nargs="?")
    args=arg.parse_args()
    if args.mode=="selftest":
        selftest()
    elif args.source is None or args.dest is None:
        arg.error("apply requires an already Ace6-rebased upstream patch and an output path")
    else:
        apply(args.source,args.dest)
