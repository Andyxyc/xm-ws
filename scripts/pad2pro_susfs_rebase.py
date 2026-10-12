#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Rebase cctv18 SUSFS 2919a9a onto OnePlus OPD2413 039d4b06c.

Retains SUS_MAP, KSTAT, OPEN_REDIRECT, OEM padded-VMA handling and
last_vma_end tracking. Other file sections are copied byte-for-byte.
This prepares a patch; the caller must still require a zero-fuzz dry-run.
"""
from __future__ import annotations
import argparse
import hashlib
import re
from pathlib import Path

PATCH_BLOB = 'fc7dc191d881d3e764ed7985998c00c43960e1e2'
SOURCE_BLOB = 'f70d8709cc4b6016fe078b33131af37024d0ecc2'
HEADER = 'diff --git a/fs/proc/task_mmu.c b/fs/proc/task_mmu.c\n'
POSITIONS = [23, 260, 275, 892, 955, 999, 1021, 1800, 1809]
HUNK = re.compile(r'^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)\n', re.M)
FOLD_OLD = (
    '+\t\t\t\tend = VMA_PAD_START(vma);\n'
    '+#ifdef __fold_filemap_fixup_entry\n'
    '+\t\t\t\t__fold_filemap_fixup_entry(&((struct proc_maps_private *)m->private)->iter, &end);\n'
    '+else\n'
    '+\t\t\t\tif (flags & __VM_NO_COMPAT)\n'
    '+\t\t\t\t\treturn;\n'
    '+#endif\n'
)
FOLD_NEW = (
    '+\t\t\t\tend = vma->vm_end;\n'
    '+\t\t\t\t__fold_filemap_fixup_entry(&((struct proc_maps_private *)m->private)->iter, &end);\n'
)
CURSOR_OLD = (
    '+#ifdef CONFIG_KSU_SUSFS_SUS_MAP\n'
    '+\t\t\t\tif (!vma->vm_file || !(SUSFS_IS_INODE_SUS_MAP(file_inode(vma->vm_file)))) {\n'
    '+\t\t\t\t\tsmap_gather_stats(vma, &mss, last_vma_end);\n'
    '+\t\t\t\t\tlast_vma_end = vma->vm_end;\n'
    '+\t\t\t\t}\n'
    '+#else\n'
    ' \t\t\t\tsmap_gather_stats(vma, &mss, last_vma_end);\n'
    ' \t\t\t\tlast_vma_end = vma->vm_end;\n'
    '+#endif // #ifdef CONFIG_KSU_SUSFS_SUS_MAP\n'
)
# The SUSFS macro expands to an unparenthesized && chain. Negation must
# enclose the complete expansion, including null guards and the app check.
CURSOR_NEW = (
    '+#ifdef CONFIG_KSU_SUSFS_SUS_MAP\n'
    '+\t\t\t\tif (!vma->vm_file || !(SUSFS_IS_INODE_SUS_MAP(file_inode(vma->vm_file)))) {\n'
    '+\t\t\t\t\tsmap_gather_stats(vma, &mss, last_vma_end);\n'
    '+\t\t\t\t}\n'
    '+#else\n'
    ' \t\t\t\tsmap_gather_stats(vma, &mss, last_vma_end);\n'
    '+#endif // #ifdef CONFIG_KSU_SUSFS_SUS_MAP\n'
    ' \t\t\t\tlast_vma_end = vma->vm_end;\n'
)

def git_blob(data: bytes) -> str:
    return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()

def once(text: str, before: str, after: str) -> str:
    if text.count(before) != 1:
        raise ValueError('Pinned patch anchor missing or duplicated: '+repr(before[:90]))
    return text.replace(before, after, 1)

def rebase_text(text: str) -> str:
    if text.count(HEADER) != 1:
        raise ValueError('Expected one task_mmu.c section')
    start = text.index(HEADER)
    end = text.find('\ndiff --git ', start+len(HEADER))
    if end < 0:
        raise ValueError('Missing following file section')
    end += 1
    section = text[start:end]
    matches = list(HUNK.finditer(section))
    if [int(m[1]) for m in matches] != POSITIONS:
        raise ValueError('Unexpected upstream task_mmu.c hunk layout')
    pieces = [section[:matches[0].start()]]
    for i, match in enumerate(matches):
        pos = int(match[1])
        body = section[match.end():matches[i+1].start() if i+1<len(matches) else len(section)]
        if pos == 999:
            # Alternative non-braced Case-4 code does not exist in the pinned
            # OEM file. Its braced implementation remains in the 1021 hunk.
            if '-\t\t\tif (vma->vm_end > last_vma_end)\n' not in body:
                raise ValueError('Unexpected alternative rollup implementation')
            continue
        if pos == 892:
            body = once(body, ' \tstruct vm_area_struct *vma = v;\n',
                        ' \tstruct vm_area_struct *vma = get_data_vma(v);\n')
        elif pos == 275:
            # Use this OEM file's existing fold API rather than the malformed
            # alternative "else" branch in the upstream insertion.
            body = once(body, FOLD_OLD, FOLD_NEW)
        elif pos == 1021:
            body = once(body, CURSOR_OLD, CURSOR_NEW)
        lines = body.splitlines(keepends=True)
        if any(not line or line[0] not in ' +-\\' for line in lines):
            raise ValueError('Malformed unified hunk body')
        old_count = sum(line[0] in ' -' for line in lines)
        new_count = sum(line[0] in ' +' for line in lines)
        pieces.append(f'@@ -{match[1]},{old_count} +{match[3]},{new_count} @@{match[5]}\n'+body)
    amended = ''.join(pieces)
    for feature in ('CONFIG_KSU_SUSFS_SUS_MAP', 'CONFIG_KSU_SUSFS_SUS_KSTAT',
                    'CONFIG_KSU_SUSFS_OPEN_REDIRECT', 'get_data_vma(v)',
                    'srcu_read_unlock', 'smap_gather_stats', 'walk_page_range'):
        if feature not in amended:
            raise ValueError('Required implementation missing: '+feature)
    if '+else\n' in amended or 'VMA_PAD_START' in amended:
        raise ValueError('Wrong OEM VMA adapter remains')
    return text[:start]+amended+text[end:]

def rebase(patch_path: Path, source_path: Path, output_path: Path) -> None:
    patch = patch_path.read_bytes()
    source = source_path.read_bytes()
    if git_blob(patch) != PATCH_BLOB or git_blob(source) != SOURCE_BLOB:
        raise ValueError('Source or patch fingerprint changed; refuse automatic rebasing')
    if output_path.exists():
        raise ValueError('Output exists; preserve prior evidence')
    updated = rebase_text(patch.decode('utf-8'))
    with output_path.open('x', encoding='utf-8', newline='\n') as out:
        out.write(updated)
    print('PASS: OPD2413 SUSFS padded-VMA rebase prepared; all features retained; full dry-run required')

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('patch', type=Path)
    ap.add_argument('source', type=Path)
    ap.add_argument('output', type=Path)
    args = ap.parse_args()
    rebase(args.patch, args.source, args.output)

if __name__ == '__main__':
    main()
