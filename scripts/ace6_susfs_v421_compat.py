#!/usr/bin/env python3
"""Guard the one known SUSFS patch ABI mismatch for pinned SukiSU v4.2.1.

This only changes the CI reconciliation script, never Android device partitions,
never alters the original KSU execveat hook, and does not waive other rejects.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import tempfile

TAG = 'ACE6_V421_KSUD_ABI_ONLY_REJECT_GUARD_20261016'
ANCHOR = 'EXPECTED_SUKISU_REJECTS=(\n'
ITEM = '  "kernel/core/init.c.rej"\n'

# Only a hunk that tries to replace SukiSU's v4.2.1 native *path/argv*
# callback with a DIFFERENT fd/filename callback may be deliberately retained.
# The existing v4.2.1 call site must still match the native interface, and
# the hunk must NOT add SUSFS symbols, or the run fails (no silent patch loss).
GUARD = r'''# ACE6_V421_KSUD_ABI_ONLY_REJECT_GUARD_20261016
# The latest SukiSU v4.2.1 retains its native path/argv execveat callback.
# SUSFS's generic 10_enable patch has one ABI-rewrite hunk from another KSU
# variant. Preserve SukiSU's native callback only when every invariant below
# proves this specific hunk is the one being rejected; fail on other changes.
_ace6_rej="kernel/runtime/ksud_integration.c.rej"
_ace6_target="kernel/runtime/ksud_integration.c"
if [ -f "$_ace6_rej" ]; then
  [ "$(grep -c '^@@ ' "$_ace6_rej")" -eq 1 ] || {
    echo "::error::Unexpected number of ksud_integration reject hunks"; exit 1;
  }
  grep -Fq -- '-void ksu_handle_execveat_ksud(const char *path, struct user_arg_ptr *argv)' "$_ace6_rej" || {
    echo "::error::Reject is not the recognized v4.2.1 old hook signature"; exit 1;
  }
  grep -Fq -- '+int ksu_handle_execveat_ksud(int *fd, struct filename **filename_ptr,' "$_ace6_rej" || {
    echo "::error::Reject is not the known generic KSU hook ABI rewrite"; exit 1;
  }
  grep -Fq 'void ksu_handle_execveat_ksud(const char *path, struct user_arg_ptr *argv)' "$_ace6_target" || {
    echo "::error::Pinned SukiSU path/argv implementation changed"; exit 1;
  }
  grep -Fq 'ksu_handle_execveat_ksud(path, &argv);' "$_ace6_target" || {
    echo "::error::Pinned SukiSU callsite missing"; exit 1;
  }
  if grep -Eq '^\+[^+].*(susfs_|CONFIG_KSU_SUSFS)' "$_ace6_rej"; then
    echo "::error::Rejected hunk carries SUSFS additions; manual merge required"; exit 1;
  fi
  echo "Ace6: verified native SukiSU execveat ABI retained; only generic ABI rewrite rejected"
fi

'''


def transform(src: str) -> str:
    if TAG in src:
        if src.count(TAG) != 1:
            raise ValueError('Duplicated guard')
        return src
    if src.count(ANCHOR) != 1 or src.count(ITEM) != 1:
        raise ValueError('Upstream reconcile script layout changed')
    if src.count('fix_sukisu_ksud_integration_c   "kernel/runtime/ksud_integration.c"') != 1:
        raise ValueError('Upstream no longer has the native KSU compatibility fix')
    pos = src.index(ANCHOR)
    if 'patch -p1 --forward < "$SUSFS_FOLDER/kernel_patches/KernelSU/10_enable_susfs_for_ksu.patch"' not in src[:pos]:
        raise ValueError('SUSFS patch application layout changed')
    patched = src.replace(ANCHOR, GUARD + ANCHOR, 1)
    patched = patched.replace(ITEM, ITEM + '  "kernel/runtime/ksud_integration.c.rej"\n', 1)
    return patched


def selftest() -> None:
    fixture = '''patch -p1 --forward < "$SUSFS_FOLDER/kernel_patches/KernelSU/10_enable_susfs_for_ksu.patch" || true
EXPECTED_SUKISU_REJECTS=(
  "kernel/core/init.c.rej"
)
fix_sukisu_ksud_integration_c   "kernel/runtime/ksud_integration.c"
'''
    result = transform(fixture)
    assert result.count(TAG) == 1
    assert result.count('  "kernel/runtime/ksud_integration.c.rej"') == 1
    assert transform(result) == result
    for corrupted in (fixture.replace('EXPECTED_SUKISU_REJECTS=(', 'OTHER_REJECTS=('),
                      fixture.replace('  "kernel/core/init.c.rej"', '  "kernel/foo.c.rej"'),
                      fixture.replace('fix_sukisu_ksud_integration_c', 'missing_ksud_fix')):
        try:
            transform(corrupted)
        except ValueError:
            pass
        else:
            raise AssertionError('Mutation should fail closed')
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / 'example.sh'
        p.write_text(result)
        import subprocess
        subprocess.run(['bash', '-n', str(p)], check=True)
    print('PASS: idempotence, anchored signature, negative mutation cases, bash syntax')


def main() -> None:
    p=argparse.ArgumentParser()
    p.add_argument('--selftest', action='store_true')
    p.add_argument('--apply', type=Path)
    args=p.parse_args()
    if args.selftest:
        selftest()
    if args.apply:
        src=args.apply.read_text(encoding='utf-8')
        new=transform(src)
        if src==new:
            print('Compatible guard already present')
        else:
            args.apply.write_text(new, encoding='utf-8')
            print(f'Patched reconcile script: {args.apply}')
    if not (args.selftest or args.apply):
        p.error('Specify --selftest or --apply')

if __name__=='__main__':
    main()
