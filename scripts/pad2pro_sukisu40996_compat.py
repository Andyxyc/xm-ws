#!/usr/bin/env python3
"""Minimal, fingerprint-locked repairs for official SukiSU builtin c95d6e2.
No ABI spoofing, scheduler changes, KPM removal, security bypass or auto flash.
The 106 manager ioctl and 200 KPM ioctl must remain distinct.
"""
from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

PIN = "c95d6e2c76adb11b0e438e518e32ac4e31f5b1d0"
EXPECTED_BLOBS = {
    "kernel/include/uapi/supercall.h": "b22818b4a8fa56309db11b5e267716d951191b71",
    "kernel/manager/throne_tracker.c": "358f333884897034558988f9b650edb61538ecbd",
    "kernel/manager/pkg_observer.c": "c33ac74a613504501193d4c3c18b2e9b4e331bf8",
    "kernel/supercall/dispatch.c": "36f603cb16b114303ece9ca1858f4e3f4477273b",
}
HEADER_OLD = "DECLARE(__u32, KSU_IOCTL_KPM, _IOWR('K', 106, ksu_manager_cmd));"
HEADER_NEW = "DECLARE(__u32, KSU_IOCTL_MANAGER, _IOWR('K', 106, struct ksu_manager_cmd));"
BUILTIN_FILTER_OLD = "if (strncmp(np->package, pkg, KSU_MAX_PACKAGE_NAME) == 0)\n            continue;"
BUILTIN_FILTER_NEW = "if (strncmp(np->package, KSU_PACKAGE_NAME, KSU_MAX_PACKAGE_NAME) == 0)\n            continue;"
OBSERVER_OLD = "track_throne(TRACK_THRONE_FORCE_SYNCHRONOUS);"
OBSERVER_NEW = "track_throne(false);"


def replace_exact(source: str, old: str, new: str, count: int = 1) -> str:
    actual = source.count(old)
    if actual != count:
        raise ValueError(f"Expected {count} matches for {old!r}; got {actual}")
    return source.replace(old, new)


def transform(header: str, throne: str, observer: str) -> tuple[str, str, str]:
    header = replace_exact(header, '#include "uapi/app_profile.h"',
                           '#include "uapi/app_profile.h"\n#include "manager.h"')
    header = replace_exact(header, HEADER_OLD, HEADER_NEW)
    # The KPM 200 ioctl is retained; the manager command uses 106.
    if header.count("KSU_IOCTL_KPM,") != 1 or header.count("KSU_IOCTL_MANAGER,") != 1:
        raise ValueError("KPM or manager ioctl enumeration conflict remains")
    if not re.search(r"DECLARE\(__u32, KSU_IOCTL_KPM, _IOC\(_IOC_READ \| _IOC_WRITE, 'K', 200, 0\)\);", header):
        raise ValueError("KPM ioctl 200 changed unexpectedly")
    throne = replace_exact(throne, BUILTIN_FILTER_OLD, BUILTIN_FILTER_NEW)
    observer = replace_exact(observer, OBSERVER_OLD, OBSERVER_NEW, 2)
    if "TRACK_THRONE_FORCE_SYNCHRONOUS" in observer:
        raise ValueError("Undefined tracker flag remains")
    return header, throne, observer


def git(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def apply(tree: Path) -> None:
    tree = tree.resolve()
    actual_pin = git(tree, "rev-parse", "HEAD")
    if actual_pin != PIN:
        raise ValueError(f"Wrong SukiSU source commit: {actual_pin}")
    for rel, blob in EXPECTED_BLOBS.items():
        file = tree / rel
        if not file.is_file():
            raise ValueError(f"Missing source: {rel}")
        actual = git(tree, "hash-object", rel)
        if actual != blob:
            raise ValueError(f"Pinned source fingerprint drift: {rel}: {actual}")
    paths = list(EXPECTED_BLOBS)
    header, throne, observer = transform(
        *((tree / p).read_text(encoding="utf-8") for p in paths[:3])
    )
    dispatch = (tree / paths[3]).read_text(encoding="utf-8")
    for name in ("struct ksu_manager_cmd *cmd;", ".cmd = KSU_IOCTL_MANAGER,",
                 ".cmd = KSU_IOCTL_KPM,", "ksu_dynamic_manager_set(cmd)"):
        if name not in dispatch:
            raise ValueError(f"Manager/KPM dispatch API missing: {name}")
    if "void track_throne(bool prune_only)" not in throne:
        raise ValueError("Tracker boolean API changed")
    for p, body in zip(paths[:3], (header, throne, observer)):
        (tree / p).write_text(body, encoding="utf-8")
    print("PASS: official SukiSU c95d6e2 manager ioctl 106, KPM ioctl 200, tracker and observer repaired")


def selftest() -> None:
    head = ('#include "uapi/app_profile.h"\n' + HEADER_OLD + '\n' +
            "DECLARE(__u32, KSU_IOCTL_KPM, _IOC(_IOC_READ | _IOC_WRITE, 'K', 200, 0));\n")
    throne = BUILTIN_FILTER_OLD + "\nvoid track_throne(bool prune_only) {}\n"
    observer = OBSERVER_OLD + "\n" + OBSERVER_OLD + "\n"
    patched = transform(head, throne, observer)
    assert patched[0].count("KSU_IOCTL_MANAGER,") == 1
    assert patched[0].count("KSU_IOCTL_KPM,") == 1
    assert "KSU_PACKAGE_NAME" in patched[1]
    assert patched[2].count("track_throne(false)") == 2
    for broken in (
        (head.replace(HEADER_OLD, ""), throne, observer),
        (head, throne.replace(BUILTIN_FILTER_OLD, ""), observer),
        (head, throne, observer.replace(OBSERVER_OLD, "", 1)),
    ):
        try:
            transform(*broken)
        except ValueError:
            pass
        else:
            raise AssertionError("Malformed upstream source silently accepted")
    print("PASS: positive and negative pinned interface compatibility selftests")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["selftest", "apply"])
    parser.add_argument("ksu_tree", type=Path, nargs="?")
    args = parser.parse_args()
    if args.action == "selftest":
        selftest()
    else:
        if args.ksu_tree is None:
            parser.error("apply requires SukiSU tree path")
        apply(args.ksu_tree)
