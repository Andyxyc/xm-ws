#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fingerprint-locked SUSFS 2.3.0 patch rebase for official Ace6 6.6.118 (.401).

Two known OEM differences only:
  fs/proc/base.c adds an additional <linux/dma-buf.h> include.
  fs/proc/task_mmu.c already uses the BRACED Case-4 VMA path.
Do not drop other functionality, use fuzzy patching, fake the kernel version,
or infer compatibility with the user's PLQ110_16.0.10.500 vendor modules.
"""
from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

SUSFS_PATCH_BLOB = "f546b7fe73965b43da9b327e33f76f49929a730a"
SOURCE_BLOBS = {
    "fs/proc/base.c": "68d01c9ab7c6c74a9b03d99b62ce4d9afcb90b80",
    "fs/proc/task_mmu.c": "e4380b37fc3161b40fc43044e44cc0e819e47d9b",
}
HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@([^\n]*)\n", re.M)
HEADER = re.compile(r"^diff --git a/([^\n ]+) b/\1\n", re.M)
UNBRACED_CASE4 = (
    "-\t\t\tif (vma->vm_end > last_vma_end)\n"
    "+\t\t\tif (vma->vm_end > last_vma_end) {\n"
)
BAD_CURSOR = (
    "+\t\t\t\t\tlast_vma_end = vma->vm_end;\n"
)
GOOD_CURSOR = (
    " \t\t\t\tlast_vma_end = vma->vm_end;\n"
)


def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def require_once(text: str, old: str, desc: str) -> None:
    n = text.count(old)
    if n != 1:
        raise ValueError(f"Unexpected {desc}, expected exactly once but found {n}")


def sections(text: str) -> list[tuple[str, str]]:
    parts = list(HEADER.finditer(text))
    if len(parts) < 20:
        raise ValueError("Truncated SUSFS patch")
    return [(p.group(1), text[p.start():(parts[i+1].start() if i+1 < len(parts) else len(text))])
            for i,p in enumerate(parts)]


def rebuild(section: str, modify: dict[int, str] | None = None,
            skip: frozenset[int] = frozenset()) -> str:
    matches = list(HUNK_RE.finditer(section))
    if not matches:
        raise ValueError("No patch hunks")
    out = [section[:matches[0].start()]]
    delta = 0
    for i, match in enumerate(matches):
        body = section[match.end():matches[i+1].start() if i+1 < len(matches) else len(section)]
        old_start = int(match.group(1))
        if i in skip:
            if "if (vma->vm_end > last_vma_end)" not in body or UNBRACED_CASE4 not in body:
                raise ValueError("Cannot safely omit an unrecognized alternate VMA patch hunk")
            continue
        if modify and i in modify:
            body = modify[i]
        original_lines = body.splitlines(keepends=True)
        if not original_lines or any(line[0] not in " +-\\"
                                     for line in original_lines):
            raise ValueError(f"Invalid patch line at hunk {i+1}")
        before = sum(line[0] in " -" for line in original_lines)
        after = sum(line[0] in " +" for line in original_lines)
        if before == 0 or after == 0:
            raise ValueError("Unexpected empty hunk")
        out.append(f"@@ -{old_start},{before} +{old_start+delta},{after} @@{match.group(5)}\n" + body)
        delta += after - before
    return "".join(out)


def adapt(text: str, base: str, task: str) -> str:
    if "#include <linux/dma-buf.h>\n#include <trace/events/oom.h>\n" not in base:
        raise ValueError("Official Ace6 proc/base.c header layout changed")
    if "if (vma->vm_end > last_vma_end) {\n" not in task:
        raise ValueError("Official Ace6 braced rollup source changed")
    pieces = sections(text)
    names = [p[0] for p in pieces]
    for p in SOURCE_BLOBS:
        if names.count(p) != 1:
            raise ValueError("Missing or duplicate patch section: "+p)
    out=[]
    for path,section in pieces:
        if path == "fs/proc/base.c":
            m=list(HUNK_RE.finditer(section))
            if len(m)!=4:
                raise ValueError("Unexpected base.c SUSFS patch layout")
            first = section[m[0].end():m[1].start()]
            required = " #include <linux/cpufreq_times.h>\n #include <trace/events/oom.h>\n"
            require_once(first, required, "base.c original include context")
            first = first.replace(required,
                " #include <linux/cpufreq_times.h>\n #include <linux/dma-buf.h>\n #include <trace/events/oom.h>\n")
            out.append(rebuild(section,{0:first}))
        elif path == "fs/proc/task_mmu.c":
            m=list(HUNK_RE.finditer(section))
            starts=[int(x.group(1)) for x in m]
            if starts!=[23,260,275,892,955,999,1021,1800,1809]:
                raise ValueError("Unexpected SUSFS task_mmu.c hunk positions: "+str(starts))
            no_brace=section[m[5].end():m[6].start()]
            require_once(no_brace, UNBRACED_CASE4, "alternate unbraced Case-4")
            braced=section[m[6].end():m[7].start()]
            require_once(braced, BAD_CURSOR, "hidden-VMA cursor advance inside conditional")
            require_once(braced, GOOD_CURSOR, "original Case-4 cursor advance")
            braced=braced.replace(BAD_CURSOR,"",1)
            braced=braced.replace(
                GOOD_CURSOR+"+#endif // #ifdef CONFIG_KSU_SUSFS_SUS_MAP\n",
                "+#endif // #ifdef CONFIG_KSU_SUSFS_SUS_MAP\n"+GOOD_CURSOR,
                1)
            if braced.count(GOOD_CURSOR)!=1 or braced.count("+#endif // #ifdef CONFIG_KSU_SUSFS_SUS_MAP")!=1:
                raise ValueError("Invalid VMA cursor relocation")
            out.append(rebuild(section,{6:braced},frozenset({5})))
        else:
            out.append(section)
    patched="".join(out)
    if "diff --git a/fs/proc/base.c" not in patched:
        raise ValueError("Missing proc/base")
    if "diff --git a/fs/proc/task_mmu.c" not in patched:
        raise ValueError("Missing task_mmu")
    if "@@ -999," in patched:
        raise ValueError("Redundant incompatible Case-4 hunk remains")
    if len(sections(patched)) != len(pieces):
        raise ValueError("SUSFS patch sections were lost")
    return patched


def prepare(upstream: Path, tree: Path, output: Path) -> None:
    if output.exists():
        raise ValueError("Output exists; do not overwrite a previous patch")
    patch=upstream.read_bytes()
    if git_blob(patch)!=SUSFS_PATCH_BLOB:
        raise ValueError("Upstream SUSFS patch fingerprint changed")
    for rel,blob in SOURCE_BLOBS.items():
        p=tree/rel
        if git_blob(p.read_bytes())!=blob:
            raise ValueError("Ace6 source fingerprint changed: "+rel)
    content=adapt(patch.decode("utf-8"),
                  (tree/"fs/proc/base.c").read_text(),
                  (tree/"fs/proc/task_mmu.c").read_text())
    output.write_text(content,encoding="utf-8",newline="\n")
    print("Ace6 SUSFS 2.3.0 strictly rebased, 2 known OEM source variants, zero fuzz")
    print("Output SHA-256:",hashlib.sha256(output.read_bytes()).hexdigest())


def selftest() -> None:
    sample_header="@@ -10,2 +10,3 @@\n a\n+b\n c\n"
    changed=rebuild(sample_header)
    assert "@@ -10,2 +10,3 @@" in changed
    for bad in ("", "@@ -1,2 +1,2 @@\n?x\n"):
        try:
            rebuild(bad)
        except ValueError:
            pass
        else:
            raise AssertionError("Invalid patch data accepted")
    data=b"hello"
    assert git_blob(data)=="b6fc4c620b67d95f953a5c1c1230aaab5db5a1b0"
    print("PASS: hunk recount, malformed patch refusals, Git blob fingerprint")


if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("action",choices=["selftest","apply"])
    a.add_argument("upstream_patch",type=Path,nargs="?")
    a.add_argument("common_source",type=Path,nargs="?")
    a.add_argument("output_patch",type=Path,nargs="?")
    ns=a.parse_args()
    if ns.action=="selftest":
        selftest()
    elif ns.upstream_patch is None or ns.common_source is None or ns.output_patch is None:
        a.error("apply needs upstream patch, Ace6 common source, output patch")
    else:
        prepare(ns.upstream_patch,ns.common_source,ns.output_patch)
