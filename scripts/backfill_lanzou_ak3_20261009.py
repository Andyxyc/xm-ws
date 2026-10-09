#!/usr/bin/env python3
"""Upload all distinct, available, successful OnePlus SukiSU 40959 AK3 artifacts."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from publish_lanzou_ak3 import PublishError, github_api, validated_artifact_name

REPO = os.environ["GITHUB_REPOSITORY"]
TOKEN = os.environ["GH_TOKEN"]
REPORT = Path("lanzou-backfill-report.json")
SOURCE_WORKFLOW = ".github/workflows/Build Kernel OnePlus.yml"
BRANCH = "SukiSU-Ultra"
TEST_RUN_ID = 37884290075  # Previously verified OnePlusAce5Race AK3 build.


def gather(api_suffix: str, key: str, max_pages: int = 24) -> list:
    all_items = []
    for page in range(1, max_pages + 1):
        response = github_api(
            f"repos/{REPO}/actions/{api_suffix}?per_page=100&page={page}", TOKEN
        )
        items = response.get(key)
        if not isinstance(items, list):
            raise PublishError(f"GitHub did not return {key}")
        all_items.extend(items)
        total = int(response.get("total_count", len(all_items)))
        if len(items) < 100 or len(all_items) >= total:
            return all_items
    raise PublishError(f"{key} inventory exceeded {max_pages * 100}, refusing partial inventory")


def inventory() -> list[dict]:
    runs = gather("runs", "workflow_runs")
    eligible_runs = {
        x["id"]: x
        for x in runs
        if x.get("path") == SOURCE_WORKFLOW
        and x.get("head_branch") == BRANCH
        and x.get("status") == "completed"
        and x.get("conclusion") == "success"
        and x.get("repository", {}).get("full_name", "").lower() == REPO.lower()
    }
    print(f"GitHub runs: {len(runs)}; successful eligible source runs: {len(eligible_runs)}", flush=True)
    artifacts = gather("artifacts", "artifacts")
    chosen = {}
    for item in artifacts:
        if item.get("expired"):
            continue
        name = item.get("name", "")
        identity = validated_artifact_name(name)
        if identity is None:
            continue
        run_id = (item.get("workflow_run") or {}).get("id")
        if run_id not in eligible_runs:
            continue
        key = name
        old = chosen.get(key)
        if old is None or (item.get("created_at", ""), item["id"]) > (
            old.get("created_at", ""), old["id"]
        ):
            chosen[key] = item
    selected = sorted(chosen.values(), key=lambda a: a["name"])
    preferred = [x for x in selected if x["workflow_run"]["id"] == TEST_RUN_ID]
    selected = preferred + [x for x in selected if x not in preferred]
    if len(selected) > 220:
        raise PublishError(f"{len(selected)} artifacts found; limit 220 requires deliberate review")
    print(f"GitHub artifacts: {len(artifacts)}; unique eligible AK3 artifacts: {len(selected)}", flush=True)
    for item in selected:
        identity = validated_artifact_name(item["name"])
        print(f"  {identity[0]} | source run {item['workflow_run']['id']} | {item['name']}", flush=True)
    return selected


def main() -> int:
    report = {
        "status": "preparing",
        "repository": REPO,
        "directory_pattern": "一加suki/suki-40959/{model}",
        "requested_scope": "latest unexpired successful unbound OnePlus SukiSU 40959 AK3 per artifact name",
        "published": [],
        "already_exists_unverified": [],
        "failed": [],
        "skipped": [],
    }
    try:
        candidates = inventory()
        report["candidate_count"] = len(candidates)
        if not candidates:
            report["status"] = "no_matching_artifacts"
            print("No eligible unexpired AK3 artifacts", flush=True)
            return 0
        env = os.environ.copy()
        for pos, item in enumerate(candidates, start=1):
            run_id = item["workflow_run"]["id"]
            print(f"[{pos}/{len(candidates)}] Uploading run {run_id}", flush=True)
            try:
                result = subprocess.run(
                    [
                        sys.executable, "-u", "scripts/publish_lanzou_ak3.py",
                        "--repo", REPO, "--run-id", str(run_id),
                    ],
                    env=env, capture_output=True, text=True, timeout=650,
                    check=False,
                )
            except subprocess.TimeoutExpired:
                report["failed"].append({"run_id": run_id, "reason": "upload_timeout"})
                print(f"::warning::Run {run_id} upload timed out", flush=True)
                continue
            published = None
            for line in result.stdout.splitlines():
                if line.startswith("PUBLISHED "):
                    published = json.loads(line.removeprefix("PUBLISHED "))
            if result.returncode == 0 and published:
                report["published"].append(published)
                print(f"SUCCESS {run_id}: {published['remote']['folder']}/{published['remote']['remote_name']}", flush=True)
            elif result.returncode == 0 and result.stdout.startswith("SKIP:"):
                report["skipped"].append({"run_id": run_id, "reason": "source_no_longer_eligible"})
                print(f"SKIP {run_id}: source no longer eligible", flush=True)
            else:
                # The public upload script intentionally doesn't print cookie values.
                reason = result.stderr.strip().splitlines()[-1][:320] if result.stderr.strip() else f"process_exit_{result.returncode}"
                if "Remote filename already exists" in reason:
                    report["already_exists_unverified"].append({"run_id": run_id, "reason": "remote_name_exists_no_overwrite"})
                    print(f"SKIP {run_id}: same remote filename already exists; no overwrite", flush=True)
                else:
                    report["failed"].append({"run_id": run_id, "reason": reason})
                    print(f"::error::Run {run_id}: {reason}", flush=True)
                if "session expired" in reason.lower() or "login refused" in reason.lower():
                    report["status"] = "authentication_failed"
                    print("::error::Stopped batch: invalid authentication; update GitHub Secrets", flush=True)
                    break
            # Light pacing, without exceeding the host's supported rate limits.
            time.sleep(2)
        else:
            report["status"] = "completed_with_failures" if report["failed"] else "completed"
        print(
            "Batch result: candidates={candidate_count}, new={new}, already_exists={exists}, "
            "failed={failed}, skipped={skipped}".format(
                candidate_count=report["candidate_count"],
                new=len(report["published"]),
                exists=len(report["already_exists_unverified"]),
                failed=len(report["failed"]),
                skipped=len(report["skipped"]),
            ),
            flush=True,
        )
        return 1 if report["failed"] or report["status"] == "authentication_failed" else 0
    except (PublishError, ValueError, KeyError, OSError) as exc:
        report["status"] = "inventory_failed"
        report["failed"].append({"run_id": None, "reason": str(exc)[:320]})
        print(f"::error::Backfill failed: {type(exc).__name__}: {str(exc)[:250]}", flush=True)
        return 1
    finally:
        REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())
