#!/usr/bin/env python3
"""Apply pinned SUSFS 2.3.0 hooks to the exact 6.6.66 source, or fail.

No configuration editing, no feature pruning, and no patch error suppression.
This checks source identity and does not certify compilation or boot.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("kernel_dir", type=Path)
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()
    bundle = Path(__file__).resolve().parent
    root = args.kernel_dir.resolve(strict=True)
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    head = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
    ).strip()
    if head != manifest["source_commit"]:
        raise SystemExit(f"Kernel source revision differs: {head}")
    for name, expected in manifest["published_files"].items():
        if digest(bundle / name) != expected:
            raise SystemExit(f"SUSFS bundle digest differs: {name}")
    for row in manifest["source_files"]:
        target = root / row["file"]
        if digest(target) != row["sha256"]:
            raise SystemExit(f"Kernel hook source differs: {row['file']}")
    files = {
        "susfs.c": root / "fs/susfs.c",
        "susfs.h": root / "include/linux/susfs.h",
        "susfs_def.h": root / "include/linux/susfs_def.h",
    }
    for target in files.values():
        if target.exists():
            raise SystemExit(f"SUSFS target already exists: {target}")
    patch = bundle / "50_add_susfs_230_cctv18_9a56.patch"
    subprocess.run(
        ["git", "-C", str(root), "apply", "--check", "--whitespace=error-all", str(patch)],
        check=True,
    )
    if args.check_only:
        print("SUSFS 2.3.0: pinned source and all 123 hook hunks checked.", flush=True)
        return
    subprocess.run(
        ["git", "-C", str(root), "apply", "--whitespace=error-all", str(patch)],
        check=True,
    )
    for name, target in files.items():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bundle / name, target)
        if digest(target) != manifest["published_files"][name]:
            raise SystemExit(f"SUSFS copied file digest differs: {target}")
    print("SUSFS 2.3.0: all hooks applied; all three core files verified.", flush=True)


if __name__ == "__main__":
    main()
