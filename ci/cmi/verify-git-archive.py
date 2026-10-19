#!/usr/bin/env python3
"""Verify every archived blob and mode against a pinned upstream Git tree."""
import argparse
import hashlib
import json
import posixpath
import tarfile
from pathlib import Path


def oid(kind, data):
    return hashlib.sha1(kind.encode() + b' ' + str(len(data)).encode() + b'\0' + data).digest()


def inspect_archive(path):
    root = {}
    seen = set()
    links = set()
    count = 0
    total = 0
    with tarfile.open(path, 'r:gz') as archive:
        for member in archive:
            name = member.name.removeprefix('./').rstrip('/')
            if not name and member.isdir():
                continue
            parts = name.split('/')
            if not name or name.startswith('/') or any(p in ('', '.', '..', '.git') for p in parts):
                raise ValueError(f'Unsafe archive path: {member.name!r}')
            if member.isdir():
                continue
            if name in seen:
                raise ValueError(f'Duplicate archive member: {name}')
            seen.add(name)
            node = root
            for part in parts[:-1]:
                node = node.setdefault(part, {})
                if not isinstance(node, dict):
                    raise ValueError('Archive parent is not a directory')
            if member.issym():
                target = member.linkname
                normalized = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
                if target.startswith('/') or normalized == '..' or normalized.startswith('../'):
                    raise ValueError(f'Link escapes archive: {name}')
                data = target.encode('utf-8', 'surrogateescape')
                blob = oid('blob', data)
                mode = b'120000'
                links.add(name)
            elif member.isfile():
                h = hashlib.sha1(b'blob ' + str(member.size).encode() + b'\0')
                nread = 0
                with archive.extractfile(member) as src:
                    while chunk := src.read(1024 * 1024):
                        h.update(chunk)
                        nread += len(chunk)
                if nread != member.size:
                    raise ValueError(f'Truncated archive member: {name}')
                blob = h.digest()
                mode = b'100755' if member.mode & 0o111 else b'100644'
                total += member.size
            else:
                raise ValueError(f'Unexpected archive entry type: {name}')
            if parts[-1] in node:
                raise ValueError(f'File/directory collision: {name}')
            node[parts[-1]] = (mode, blob)
            count += 1
    for name in seen:
        if any('/'.join(name.split('/')[:i]) in links for i in range(1, len(name.split('/')))):
            raise ValueError(f'Archive member beneath a symlink: {name}')

    def tree_id(node):
        entries = []
        for name, value in node.items():
            encoded = name.encode('utf-8', 'surrogateescape')
            if isinstance(value, dict):
                entries.append((encoded + b'/', b'40000 ' + encoded + b'\0' + tree_id(value)))
            else:
                mode, blob = value
                entries.append((encoded, mode + b' ' + encoded + b'\0' + blob))
        return oid('tree', b''.join(value for _, value in sorted(entries)))
    return {'git_tree': tree_id(root).hex(), 'files_and_symlinks': count, 'regular_bytes': total}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('archive', type=Path)
    ap.add_argument('expected_tree')
    ap.add_argument('report', type=Path)
    args = ap.parse_args()
    h = hashlib.sha256()
    with args.archive.open('rb') as src:
        while chunk := src.read(4 * 1024 * 1024):
            h.update(chunk)
    result = inspect_archive(args.archive)
    result.update(archive_sha256=h.hexdigest(), expected_git_tree=args.expected_tree)
    result['matches_pinned_tree'] = result['git_tree'] == args.expected_tree
    result['matches_previous_archive_sha256'] = h.hexdigest() == '466310a4275ee9fd8ed31527feb5f1e6b95eb5501c31f58b7325727aa5bbaf38'
    args.report.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    if not result['matches_pinned_tree']:
        raise SystemExit('Upstream Git tree mismatch; refusing to use compiler')


if __name__ == '__main__':
    main()
