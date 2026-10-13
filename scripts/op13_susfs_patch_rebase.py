#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Pinned CCTV18 SUSFS task_mmu.c rebase for OP13 PJZ110 A16 6.6.89.

Changes only the task_mmu.c patch section. Fails closed on source/patch drift.
Does not bypass a failed patch, disable KPM/SUSFS, or rewrite the stock kernel.
"""
from __future__ import annotations

import argparse
import hashlib
import re
from pathlib import Path

SOURCE_BLOB = "ad94f3ee623db2b38015168a94fa1ee947552833"
PATCH_BLOB = "dc3ba5b8e70130a62cfdb3116ddc523e7a45a3b9"
HEADER = "diff --git a/fs/proc/task_mmu.c b/fs/proc/task_mmu.c\n"
POSITIONS = (23, 260, 275, 892, 955, 999, 1021, 1800, 1809)
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@([^\n]*)\n", re.M)
FOLD_OLD = (
    "+\t\t\t\tend = VMA_PAD_START(vma);\n"
    "+#ifdef __fold_filemap_fixup_entry\n"
    "+\t\t\t\t__fold_filemap_fixup_entry(&((struct proc_maps_private *)m->private)->iter, &end);\n"
    "+else\n"
    "+\t\t\t\tif (flags & __VM_NO_COMPAT)\n"
    "+\t\t\t\t\treturn;\n"
    "+#endif\n"
)
FOLD_NEW = (
    "+\t\t\t\tend = VMA_PAD_START(vma);\n"
    "+\t\t\t\t__fold_filemap_fixup_entry(&((struct proc_maps_private *)m->private)->iter, &end);\n"
)
CURSOR_OLD = (
    "+#ifdef CONFIG_KSU_SUSFS_SUS_MAP\n"
    "+\t\t\t\tif (!vma->vm_file || !(SUSFS_IS_INODE_SUS_MAP(file_inode(vma->vm_file)))) {\n"
    "+\t\t\t\t\tsmap_gather_stats(vma, &mss, last_vma_end);\n"
    "+\t\t\t\t\tlast_vma_end = vma->vm_end;\n"
    "+\t\t\t\t}\n"
    "+#else\n"
    " \t\t\t\tsmap_gather_stats(vma, &mss, last_vma_end);\n"
    " \t\t\t\tlast_vma_end = vma->vm_end;\n"
    "+#endif // #ifdef CONFIG_KSU_SUSFS_SUS_MAP\n"
)
CURSOR_NEW = (
    "+#ifdef CONFIG_KSU_SUSFS_SUS_MAP\n"
    "+\t\t\t\tif (!vma->vm_file || !(SUSFS_IS_INODE_SUS_MAP(file_inode(vma->vm_file)))) {\n"
    "+\t\t\t\t\tsmap_gather_stats(vma, &mss, last_vma_end);\n"
    "+\t\t\t\t}\n"
    "+#else\n"
    " \t\t\t\tsmap_gather_stats(vma, &mss, last_vma_end);\n"
    "+#endif // #ifdef CONFIG_KSU_SUSFS_SUS_MAP\n"
    " \t\t\t\tlast_vma_end = vma->vm_end;\n"
)

def git_blob(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()

def exact_once(body: str, old: str, new: str) -> str:
    if body.count(old) != 1:
        raise ValueError("Pinned SUSFS patch insertion not unique or absent: " + repr(old[:100]))
    return body.replace(old, new, 1)

def rebase_text(text: str) -> str:
    if text.count(HEADER) != 1:
        raise ValueError("Expected one fs/proc/task_mmu.c patch section")
    start = text.index(HEADER)
    end = text.find("\ndiff --git ", start + len(HEADER))
    if end == -1:
        raise ValueError("Cannot locate end of pinned task_mmu.c patch")
    end += 1
    section = text[start:end]
    matches = list(HUNK.finditer(section))
    actual = tuple(int(x.group(1)) for x in matches)
    if actual != POSITIONS:
        raise ValueError("Unexpected task_mmu hunk layout: " + repr(actual))
    output = [section[:matches[0].start()]]
    for i, match in enumerate(matches):
        pos = int(match.group(1))
        hunk_end = matches[i + 1].start() if i + 1 < len(matches) else len(section)
        body = section[match.end():hunk_end]
        if pos == 999:
            # Variant not present in the OEM source; its braced counterpart follows.
            required = "-\t\t\tif (vma->vm_end > last_vma_end)\n"
            if required not in body:
                raise ValueError("Unexpected non-braced Case-4 hunk")
            continue
        if pos == 275:
            # OEM has __fold_filemap_fixup_entry as a real function, not a macro.
            body = exact_once(body, FOLD_OLD, FOLD_NEW)
        if pos == 1021:
            # Advance cursor even when a hidden VMA is intentionally excluded.
            body = exact_once(body, CURSOR_OLD, CURSOR_NEW)
        lines = body.splitlines(keepends=True)
        if not lines or any(not l or l[0] not in " +-\\"
                            for l in lines):
            raise ValueError("Invalid unified patch hunk")
        before = sum(l[0] in " -" for l in lines)
        after = sum(l[0] in " +" for l in lines)
        output.append(f"@@ -{match.group(1)},{before} +{match.group(3)},{after} @@{match.group(5)}\n" + body)
    amended = "".join(output)
    for feature in ("CONFIG_KSU_SUSFS_SUS_MAP", "CONFIG_KSU_SUSFS_SUS_KSTAT",
                    "CONFIG_KSU_SUSFS_OPEN_REDIRECT", "__fold_filemap_fixup_entry",
                    "last_vma_end = vma->vm_end", "srcu_read_unlock", "walk_page_range"):
        if feature not in amended:
            raise ValueError("Missing required SUSFS feature: " + feature)
    if "+else\n" in amended or "VMA_PAD_START" not in amended or "@@ -999," in amended:
        raise ValueError("Malformed conditional or redundant hunk remains")
    return text[:start] + amended + text[end:]

def prepare(patch: Path, original: Path, output: Path) -> None:
    patch_bytes, src_bytes = patch.read_bytes(), original.read_bytes()
    if git_blob(patch_bytes) != PATCH_BLOB:
        raise ValueError("SUSFS patch blob changed: fail closed")
    if git_blob(src_bytes) != SOURCE_BLOB:
        raise ValueError("OP13 6.6.89 source blob changed: fail closed")
    src = src_bytes.decode("utf-8")
    assert "VMA_PAD_START(vma)" in src and "__fold_filemap_fixup_entry(" in src
    assert "if (vma->vm_end > last_vma_end) {" in src
    assert src.count("last_vma_end = vma->vm_end;") == 3
    amended = rebase_text(patch_bytes.decode("utf-8"))
    with output.open("x", encoding="utf-8", newline="\n") as f:
        f.write(amended)
    print("PASS: pinned OEM source and SUSFS upstream patch fingerprints verified")
    print("PASS: task_mmu redundant Case-4 variant removed; OEM fold & cursor restored")
    print("Rebased patch SHA256:", hashlib.sha256(output.read_bytes()).hexdigest())

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("upstream_patch", type=Path)
    parser.add_argument("pinned_source_task_mmu", type=Path)
    parser.add_argument("output_patch", type=Path)
    args = parser.parse_args()
    prepare(args.upstream_patch, args.pinned_source_task_mmu, args.output_patch)
