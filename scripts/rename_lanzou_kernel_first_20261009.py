#!/usr/bin/env python3
"""Rename only generated OnePlus SukiSU 40959 AK3 files to kernel-version-first.

No upload, deletion, replacement, folder rename, or source ZIP modification.
Uses the pre-existing LanZouCloud GitHub Secrets and read-back verification.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from publish_lanzou_ak3 import (
    ROOT_FOLDER,
    VERSION_FOLDER,
    PublishError,
    make_secure_client,
    version_first_filename,
)

REPORT = Path("lanzou-kernel-first-rename-report.json")
MAX_FILES = 220


def unique_dir(client, parent: int, target: str):
    children = [x for x in client.get_dir_list(parent) if x.name == target]
    if len(children) != 1:
        raise PublishError(
            f"Expected exactly one existing folder {target!r}; got {len(children)}"
        )
    return int(children[0].id)


def credentials():
    uid = os.environ.get("LANZOU_YLOGIN", "")
    passwd = os.environ.get("LANZOU_PHPDISK_INFO", "")
    if not uid.isdecimal() or not passwd.strip():
        raise PublishError("LanZouCloud credentials are unavailable or malformed")
    cookie = {"ylogin": uid, "phpdisk_info": passwd}
    session = os.environ.get("LANZOU_PHPSESSID", "")
    if session:
        cookie["PHPSESSID"] = session
    return cookie


def list_candidates(client):
    root = unique_dir(client, -1, ROOT_FOLDER)
    version = unique_dir(client, root, VERSION_FOLDER)
    candidates = []
    skipped = []
    for model in client.get_dir_list(version):
        name = model.name
        if not re.fullmatch(r"OnePlus[A-Za-z0-9_-]{2,80}", name):
            skipped.append({"folder": name, "reason": "not_generated_model_folder"})
            continue
        files = list(client.get_file_list(int(model.id)))
        names = {x.name for x in files}
        for f in files:
            if not f.name.startswith("AnyKernel3_SukiSUUltra_40959_"):
                continue
            if not f.name.endswith(".zip") or "_run" not in f.name:
                skipped.append({"folder": name, "old_name": f.name,
                                "reason": "not_generated_ak3_name"})
                continue
            try:
                replacement = version_first_filename(f.name)
            except PublishError:
                skipped.append({"folder": name, "old_name": f.name,
                                "reason": "unknown_kernel_version_format"})
                continue
            # Folder identity must agree with the filename to prevent renaming
            # an unrelated file or silently mixing models.
            if not replacement.startswith(replacement.split("_", 1)[0] + "_" + name + "_"):
                skipped.append({"folder": name, "old_name": f.name,
                                "reason": "model_folder_mismatch"})
                continue
            if replacement in names:
                skipped.append({"folder": name, "old_name": f.name,
                                "reason": "destination_name_already_exists"})
                continue
            candidates.append({
                "model": name, "folder_id": int(model.id), "remote_file_id": int(f.id),
                "old_name": f.name, "new_name": replacement,
            })
    if len(candidates) > MAX_FILES:
        raise PublishError(f"Rename count exceeded safe limit ({MAX_FILES})")
    return candidates, skipped


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    result = {
        "state": "preparing",
        "mode": "dry_run" if args.dry_run else "apply",
        "directory_scope": f"{ROOT_FOLDER}/{VERSION_FOLDER}/OnePlus*",
        "renamed": [],
        "skipped": [],
        "failed": [],
        "planned": [],
    }
    try:
        from lanzou.api import LanZouCloud
        cloud = make_secure_client()
        if cloud.login_by_cookie(credentials()) != LanZouCloud.SUCCESS:
            raise PublishError("LanZouCloud read-only authentication failed")
        candidates, skipped = list_candidates(cloud)
        result["skipped"] = skipped
        result["planned"] = candidates
        print(
            f"Kernel-version-first rename: eligible={len(candidates)}, "
            f"skipped={len(skipped)}, mode={result['mode']}", flush=True
        )
        if args.dry_run:
            result["state"] = "preflight_complete"
            return 0
        for idx, c in enumerate(candidates, 1):
            # Only alter the basename. SDK preserves the existing ZIP extension.
            target_stem = c["new_name"][:-4]
            code = cloud.rename_file(c["remote_file_id"], target_stem)
            if code != LanZouCloud.SUCCESS:
                result["failed"].append({
                    "model": c["model"], "remote_file_id": c["remote_file_id"],
                    "old_name": c["old_name"], "reason": f"rename_api_code_{code}",
                })
                result["state"] = "rename_rejected_stop"
                print(f"::error::Rename rejected by LanZouCloud for "
                      f"{c['model']} (code={code}); stopping without fallback", flush=True)
                return 1
            latest = list(cloud.get_file_list(c["folder_id"]))
            matches = [f for f in latest if int(f.id) == c["remote_file_id"]]
            if len(matches) != 1 or matches[0].name != c["new_name"]:
                # Never retry blindly after a possible remote mutation.
                result["failed"].append({
                    "model": c["model"], "remote_file_id": c["remote_file_id"],
                    "old_name": c["old_name"], "expected_new_name": c["new_name"],
                    "observed_name": matches[0].name if len(matches) == 1 else None,
                    "reason": "rename_readback_mismatch",
                })
                result["state"] = "rename_verify_failed_stop"
                print("::error::Rename readback mismatch; stopped for manual diagnosis",
                      flush=True)
                return 1
            result["renamed"].append({
                "model": c["model"], "remote_file_id": c["remote_file_id"],
                "old_name": c["old_name"], "new_name": c["new_name"],
                "verification": "same_file_id_and_exact_new_filename",
            })
            if idx % 10 == 0 or idx == len(candidates):
                print(f"Rename progress {idx}/{len(candidates)}", flush=True)
            # Small pause reduces load on third-party web endpoints.
            time.sleep(0.25)
        result["state"] = "completed"
        return 0
    except (PublishError, OSError, ValueError, KeyError) as exc:
        result["failed"].append({"reason": f"{type(exc).__name__}: {str(exc)[:220]}"})
        result["state"] = "failed"
        print(f"::error::Rename workflow halted: {type(exc).__name__}: "
              f"{str(exc)[:220]}", flush=True)
        return 1
    finally:
        REPORT.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        print(f"Rename result: {result['state']}, "
              f"renamed={len(result['renamed'])}, "
              f"failed={len(result['failed'])}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
