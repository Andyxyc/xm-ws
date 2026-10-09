#!/usr/bin/env python3
"""Rename owned OnePlus SukiSU 40959 AK3 display names in LanZouCloud.

Within the existing 一加suki/suki-40959 directory, rename known model folders
to explicit Chinese labels, and promote Android/HMBIRD/kernel details in filenames.
Never modify ZIP bytes, delete/move/copy/replace files, rename unknown directories,
or touch any folder outside this selected release tree.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from lanzou_display_names import MODEL_NAMES, display_filename, folder_name
from publish_lanzou_ak3 import (
    ROOT_FOLDER, VERSION_FOLDER, PublishError, make_secure_client,
)

REPORT = Path("lanzou-display-rename-report.json")
MAX_RENAMES = 220
RELEASE_SCOPE = f"{ROOT_FOLDER}/{VERSION_FOLDER}"


def auth_cookies() -> dict:
    uid = os.environ.get("LANZOU_YLOGIN", "")
    token = os.environ.get("LANZOU_PHPDISK_INFO", "")
    if not uid.isdecimal() or not token.strip():
        raise PublishError("LanZouCloud credentials unavailable")
    cookie = {"ylogin": uid, "phpdisk_info": token}
    session = os.environ.get("LANZOU_PHPSESSID", "")
    if session:
        cookie["PHPSESSID"] = session
    return cookie


def find_unique(client, parent: int, name: str) -> int:
    found = [x for x in client.get_dir_list(parent) if x.name == name]
    if len(found) != 1:
        raise PublishError(f"Expected unique release folder {name}, found {len(found)}")
    return int(found[0].id)


def get_release(client) -> int:
    return find_unique(client, find_unique(client, -1, ROOT_FOLDER), VERSION_FOLDER)


def plan(client, chosen: str):
    release = get_release(client)
    folders = list(client.get_dir_list(release))
    by_name = {}
    for fld in folders:
        by_name.setdefault(fld.name, []).append(fld)
    file_changes, folder_changes, skipped = [], [], []
    for model, localized in MODEL_NAMES.items():
        if chosen != "all" and chosen != model:
            continue
        old = by_name.get(model, [])
        translated = by_name.get(localized, [])
        if len(old) > 1 or len(translated) > 1 or (old and translated):
            raise PublishError(f"Conflicting model folder names for {model}; no changes made")
        selected = old or translated
        if not selected:
            continue
        entry = selected[0]
        did = int(entry.id)
        all_files = list(client.get_file_list(did))
        existing_names = {f.name for f in all_files}
        related = 0
        for f in all_files:
            # Restrict to the original generated ZIPs, or the already-updated
            # display naming style. Unrecognized or personal files stay intact.
            try:
                label = display_filename(f.name, expected_model=model)
            except ValueError:
                continue
            related += 1
            if label == f.name:
                continue
            if label in existing_names:
                skipped.append({"model": model, "old_name": f.name,
                                "reason": "new_file_name_already_exists"})
                continue
            file_changes.append({
                "model": model, "folder_id": did, "file_id": int(f.id),
                "old": f.name, "new": label,
                "old_size": str(getattr(f, "size", "")),
            })
        if old and related:
            folder_changes.append({
                "model": model, "parent_id": release,
                "folder_id": did, "old": model, "new": localized,
            })
        elif old and not related:
            skipped.append({"model": model, "reason": "no_owned_ak3_files"})
    if len(file_changes) + len(folder_changes) > MAX_RENAMES:
        raise PublishError("Unexpected number of rename operations")
    targets = [(v["folder_id"], v["new"]) for v in file_changes]
    if len(targets) != len(set(targets)):
        raise PublishError("Duplicate destination file names detected")
    return file_changes, folder_changes, skipped


def rename_files(client, candidates: list, report: dict) -> bool:
    from lanzou.api import LanZouCloud

    for index, item in enumerate(candidates, 1):
        listing = list(client.get_file_list(item["folder_id"]))
        old = [x for x in listing if int(x.id) == item["file_id"]]
        if len(old) != 1 or old[0].name != item["old"]:
            report["failed"].append({"stage": "file", "model": item["model"],
                "file_id": item["file_id"], "reason": "source_changed_before_rename"})
            return False
        if any(x.name == item["new"] for x in listing):
            report["failed"].append({"stage": "file", "model": item["model"],
                "file_id": item["file_id"], "reason": "destination_name_collision"})
            return False
        # Same cloud file ID; extension maintained by provider.
        code = client.rename_file(item["file_id"], item["new"][:-4])
        if code != LanZouCloud.SUCCESS:
            report["failed"].append({"stage": "file", "model": item["model"],
                "file_id": item["file_id"], "reason": f"rename_rejected_code_{code}"})
            return False
        after = list(client.get_file_list(item["folder_id"]))
        found = [x for x in after if int(x.id) == item["file_id"]]
        if (len(found) != 1 or found[0].name != item["new"] or
                str(getattr(found[0], "size", "")) != item["old_size"]):
            report["failed"].append({"stage": "file", "model": item["model"],
                "file_id": item["file_id"], "reason": "rename_readback_or_size_mismatch"})
            return False
        report["files"].append({
            "model": item["model"], "file_id": item["file_id"],
            "old": item["old"], "new": item["new"],
            "readback": "same_id_name_and_size",
        })
        if index % 10 == 0 or index == len(candidates):
            print(f"File names verified {index}/{len(candidates)}", flush=True)
        time.sleep(0.2)
    return True


def rename_folders(client, candidates: list, report: dict) -> bool:
    from lanzou.api import LanZouCloud

    for index, item in enumerate(candidates, 1):
        children = list(client.get_dir_list(item["parent_id"]))
        origin = [x for x in children if int(x.id) == item["folder_id"]]
        if len(origin) != 1 or origin[0].name != item["old"]:
            report["failed"].append({"stage": "folder", "model": item["model"],
                "folder_id": item["folder_id"], "reason": "source_folder_changed"})
            return False
        if any(x.name == item["new"] for x in children):
            report["failed"].append({"stage": "folder", "model": item["model"],
                "folder_id": item["folder_id"], "reason": "destination_folder_exists"})
            return False
        before_files = {int(x.id): (x.name, str(getattr(x, "size", "")))
                        for x in client.get_file_list(item["folder_id"])}
        code = client.rename_dir(item["folder_id"], item["new"])
        if code != LanZouCloud.SUCCESS:
            report["failed"].append({"stage": "folder", "model": item["model"],
                "folder_id": item["folder_id"], "reason": f"rename_rejected_code_{code}"})
            return False
        after_dirs = list(client.get_dir_list(item["parent_id"]))
        new_refs = [x for x in after_dirs if int(x.id) == item["folder_id"]]
        after_files = {int(x.id): (x.name, str(getattr(x, "size", "")))
                       for x in client.get_file_list(item["folder_id"])}
        if (len(new_refs) != 1 or new_refs[0].name != item["new"] or
                any(x.name == item["old"] for x in after_dirs) or
                before_files != after_files):
            report["failed"].append({"stage": "folder", "model": item["model"],
                "folder_id": item["folder_id"], "reason": "folder_or_contents_readback_mismatch"})
            return False
        report["folders"].append({
            "folder_id": item["folder_id"], "old": item["old"],
            "new": item["new"], "readback": "same_id_and_children",
        })
        if index % 10 == 0 or index == len(candidates):
            print(f"Chinese folders verified {index}/{len(candidates)}", flush=True)
        time.sleep(0.2)
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="all")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.model != "all" and args.model not in MODEL_NAMES:
        print("::error::Unknown model; no changes made")
        return 2
    receipt = {
        "status": "not_started", "mode": "preview" if args.dry_run else "apply",
        "selected_model": args.model, "scope": RELEASE_SCOPE,
        "files": [], "folders": [], "skipped": [], "failed": [],
        "planned_file_count": 0, "planned_folder_count": 0,
    }
    try:
        from lanzou.api import LanZouCloud
        client = make_secure_client()
        if client.login_by_cookie(auth_cookies()) != LanZouCloud.SUCCESS:
            raise PublishError("Authenticated release folder API refused session")
        files, folders, skipped = plan(client, args.model)
        receipt["planned_file_count"] = len(files)
        receipt["planned_folder_count"] = len(folders)
        receipt["skipped"] = skipped
        print(f"Display rename plan: model={args.model} "
              f"files={len(files)}, folders={len(folders)}, skipped={len(skipped)}, "
              f"mode={'dry_run' if args.dry_run else 'apply'}", flush=True)
        print("Examples (max 5):", flush=True)
        for c in files[:5]:
            print(f"{c['model']}: {c['old']} => {c['new']}", flush=True)
        for c in folders[:5]:
            print(f"{c['old']} => {c['new']}", flush=True)
        if args.dry_run:
            receipt["status"] = "preview_ok"
            return 0
        # Do not rename folders until every eligible contained file is proven
        # correctly renamed. On any conflict, stop, keep cloud file IDs and
        # leave all existing content in place.
        if not rename_files(client, files, receipt):
            receipt["status"] = "stopped_file_rename"
            return 1
        if not rename_folders(client, folders, receipt):
            receipt["status"] = "stopped_folder_rename"
            return 1
        receipt["status"] = "completed"
        return 0
    except (PublishError, ValueError, OSError, KeyError) as exc:
        receipt["status"] = "failed"
        receipt["failed"].append({"reason": f"{type(exc).__name__}: {str(exc)[:220]}"})
        print(f"::error::Display rename stopped: {type(exc).__name__}: "
              f"{str(exc)[:220]}", flush=True)
        return 1
    finally:
        REPORT.write_text(json.dumps(receipt, ensure_ascii=False, indent=2),
                          encoding="utf-8")
        print(f"Display rename result={receipt['status']}, "
              f"files={len(receipt['files'])}, folders={len(receipt['folders'])}, "
              f"failed={len(receipt['failed'])}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
