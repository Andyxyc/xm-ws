#!/usr/bin/env python3
"""Prepare SUSFS 6.6 hook patch for minimal PKR110 builds.

Remove ONLY the six fs/proc/task_mmu.c unified hunks guarded solely by the
disabled CONFIG_KSU_SUSFS_SUS_MAP option. Preserve all three KSTAT and
OPEN_REDIRECT-bearing hunks and all other files unchanged.

The upstream patch, source revision, and number and identity of rejected
hunks are pinned. Never suppress patch failures elsewhere. Follow with a
full --fuzz=0 --dry-run before applying the resulting patch.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

TASK_HEADER = "diff --git a/fs/proc/task_mmu.c b/fs/proc/task_mmu.c\n"
REMOVE_OLD_POSITIONS = (892, 955, 999, 1021, 1800, 1809)
RETAIN_OLD_POSITIONS = (23, 260, 275)
HUNK_HEADER = re.compile(r"@@ -(\d+)(?:,\d+)? \+\d+(?:,\d+)? @@")
DISABLED_FEATURE = "# CONFIG_KSU_SUSFS_SUS_MAP is not set"


def pruned_patch(original: str) -> str:
    if original.count(TASK_HEADER) != 1:
        raise ValueError("Unexpected number of task_mmu.c diff sections")
    start = original.index(TASK_HEADER)
    end = original.find("\ndiff --git ", start + len(TASK_HEADER))
    if end == -1:
        raise ValueError("Expected next file diff after task_mmu.c")
    end += 1

    section = original[start:end]
    matches = list(re.finditer(r"(?m)^@@ -\d+(?:,\d+)? \+\d+(?:,\d+)? @@[^\n]*\n", section))
    if len(matches) != len(RETAIN_OLD_POSITIONS) + len(REMOVE_OLD_POSITIONS):
        raise ValueError("Unexpected number of task_mmu.c hunks")

    head = section[:matches[0].start()]
    result = [head]
    removed = []
    retained = []
    for i, m in enumerate(matches):
        this = section[m.start():matches[i+1].start() if i+1<len(matches) else len(section)]
        h = HUNK_HEADER.match(this)
        if not h:
            raise ValueError("Malformed SUSFS task_mmu.c hunk")
        line = int(h.group(1))
        if line in REMOVE_OLD_POSITIONS:
            if "CONFIG_KSU_SUSFS_SUS_MAP" not in this:
                raise ValueError(f"Unexpected behavior in removed hunk {line}")
            if any(x in this for x in ("CONFIG_KSU_SUSFS_SUS_KSTAT", "CONFIG_KSU_SUSFS_OPEN_REDIRECT")):
                raise ValueError(f"Cannot remove required SUSFS KSTAT/redirect hunk {line}")
            removed.append(line)
        elif line in RETAIN_OLD_POSITIONS:
            retained.append(line)
            result.append(this)
        else:
            raise ValueError(f"Unknown task_mmu.c patch hunk starting {line}")
    if tuple(removed) != REMOVE_OLD_POSITIONS or tuple(retained) != RETAIN_OLD_POSITIONS:
        raise ValueError("Unexpected order of verified task_mmu.c hunks")
    amended = original[:start] + "".join(result) + original[end:]
    if len(original) - len(amended) < 450:
        raise ValueError("Expected optional map-only patch changes not removed")
    # The two failing hunks are among the removed six. Strictly preserve all
    # other SUSFS source file modifications for compile/link-time validation.
    assert amended.count(TASK_HEADER) == 1
    assert "CONFIG_KSU_SUSFS_SUS_KSTAT" in amended
    return amended


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("upstream_patch", type=pathlib.Path)
    ap.add_argument("--builder", type=pathlib.Path, required=True)
    args = ap.parse_args()

    builder = args.builder.read_text(encoding="utf-8")
    if DISABLED_FEATURE not in builder:
        raise ValueError("SUS_MAP is not proven disabled in this build. Refusing patch pruning")
    source = args.upstream_patch.read_text(encoding="utf-8")
    amended = pruned_patch(source)
    args.upstream_patch.write_text(amended, encoding="utf-8")
    print(
        "SUSFS minimal: kept KSTAT/map-vma logic, removed six inactive "
        "SUS_MAP-only /proc/task_mmu hunks; strict full dry-run required",
        flush=True,
    )


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as exc:
        sys.exit(f"::error::SUSFS patch compatibility refused: {exc}")
