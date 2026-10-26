#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Guard two optional new SukiSU builtin calls absent from pinned CCTV18 SUSFS 2.2.0.

Only for OnePlus 13's already-booted SUSFS baseline. No configuration, SUSFS
kernel implementation, OEM source, KPM, or AK3 installer changes.
"""
import argparse
import hashlib
import difflib
from pathlib import Path

SU_SRC = {
    "manager/pkg_observer.c": "375e6b600f1e18574151b3b31f43818ab4a94d39",
    "supercall/dispatch.c": "ec50b3124d474f33d6fcd0b8f070f7fc905b2008",
}
SUSFS_DEF_BLOB = "1fc33b482720bc1e73e4b5aceb31f06d6f7cf301"
MARKER = "CMD_SUSFS_SET_PRIORITY_UID_FILTER"

PKG_OLD = (
    "    // Renew the getpriority uid bitmap filter\n"
    "    susfs_parse_priority_app_strings();\n"
)
PKG_NEW = (
    "    // This optional API is absent in the pinned CCTV18 SUSFS 2.2.0.\n"
    "#ifdef CMD_SUSFS_SET_PRIORITY_UID_FILTER\n"
    "    susfs_parse_priority_app_strings();\n"
    "#endif\n"
)
DISPATCH_OLD = (
    "        case CMD_SUSFS_SET_PRIORITY_UID_FILTER:\n"
    "            susfs_set_priority_uid_filter(arg);\n"
    "            return 0;\n"
)
DISPATCH_NEW = (
    "#ifdef CMD_SUSFS_SET_PRIORITY_UID_FILTER\n"
    "        case CMD_SUSFS_SET_PRIORITY_UID_FILTER:\n"
    "            susfs_set_priority_uid_filter(arg);\n"
    "            return 0;\n"
    "#endif\n"
)


def blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\\0" + data).hexdigest()


def patch_exact(text: str, original: str, replacement: str) -> str:
    if text.count(original) != 1:
        raise ValueError("Required upstream interface snippet missing or duplicated")
    return text.replace(original, replacement, 1)


def test() -> None:
    assert patch_exact(PKG_OLD, PKG_OLD, PKG_NEW) == PKG_NEW
    assert patch_exact(DISPATCH_OLD, DISPATCH_OLD, DISPATCH_NEW) == DISPATCH_NEW
    assert "CMD_SUSFS_SET_PRIORITY_UID_FILTER" in PKG_NEW
    assert PKG_NEW.count("susfs_parse_priority_app_strings();") == 1
    assert DISPATCH_NEW.count("susfs_set_priority_uid_filter(arg);") == 1
    for orig, new in ((PKG_OLD, PKG_NEW), (DISPATCH_OLD, DISPATCH_NEW)):
        assert patch_exact("prefix\\n" + orig + "suffix\\n", orig, new).startswith("prefix\\n")
        try:
            patch_exact(new, orig, new)
            raise AssertionError("Idempotence check failed: patch may be re-applied")
        except ValueError:
            pass
    assert blob(b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    print("PASS: priority-UID guards are exact, minimal and non-repeatable")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("ksu_root", nargs="?", type=Path)
    ap.add_argument("susfs_def", nargs="?", type=Path)
    ap.add_argument("diagnostics", nargs="?", type=Path)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    test()
    if args.selftest:
        return
    if not (args.ksu_root and args.susfs_def and args.diagnostics):
        ap.error("Expected KSU root, pinned SUSFS header and diagnostics path")
    if blob(args.susfs_def.read_bytes()) != SUSFS_DEF_BLOB:
        raise ValueError("CCTV18 SUSFS header changed; refuse compatibility patch")
    if MARKER in args.susfs_def.read_text():
        raise ValueError("Priority UID filter has a native API; do not change new code")
    changes = {}
    for rel, sha in SU_SRC.items():
        path = args.ksu_root / rel
        data = path.read_bytes()
        if blob(data) != sha:
            raise ValueError("Pinned SukiSU source changed: " + rel)
        old = data.decode("utf-8")
        new = patch_exact(old, PKG_OLD, PKG_NEW) if "pkg_observer" in rel else patch_exact(old, DISPATCH_OLD, DISPATCH_NEW)
        if new.count("susfs_parse_priority_app_strings();") != old.count("susfs_parse_priority_app_strings();"):
            raise ValueError("Unexpected change to call count")
        changes[rel] = (path, old, new)
    diag = ["SukiSU optional priority-UID extension: disabled at compile time because pinned CCTV18 SUSFS 2.2.0 has no API.",
            "SUSFS and root core features unchanged; no exported dummy stubs.",
            "This is not a device boot test."]
    for rel, (path, old, new) in changes.items():
        path.write_text(new, encoding="utf-8", newline="")
        diag.extend(difflib.unified_diff(old.splitlines(), new.splitlines(), fromfile=rel+"@pinned", tofile=rel+"@guarded", lineterm=""))
    args.diagnostics.parent.mkdir(parents=True, exist_ok=True)
    args.diagnostics.write_text("\\n".join(diag) + "\\n", encoding="utf-8")
    print("PASS: guarded only the unsupported new priority-UID filter interface in 2 pinned builtin files")


if __name__ == "__main__":
    main()
