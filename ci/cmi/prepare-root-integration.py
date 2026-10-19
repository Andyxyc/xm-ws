#!/usr/bin/env python3
"""CMI root integration stage; no phone access or flashable packaging.

Reuse the verified MiCode driver baseline. Keep the previous source archives
unchanged. Compile the pinned upstream SukiSU first; independently record the
legacy SUSFS patch's actual applicability before resolving its newer-KSU bridge.
Integration: xiaomo. Upstream notices and licenses are preserved.
"""
from pathlib import Path
import difflib
import hashlib
import json
import re
import shutil
import subprocess
import sys

SUKI_SHA = '7f1c299af463d008e66e714077eb6a8079ff722b'
SUSFS_SHA = '001e69919c6271f690fd00b17e4c721c9e599152'
SUKI_URL = 'https://github.com/SukiSU-Ultra/SukiSU-Ultra.git'
SUSFS_URL = 'https://github.com/ShirkNeko/susfs4ksu.git'


def run(argv, **kw):
    return subprocess.run(argv, check=True, timeout=600, **kw)


def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def checkout(destination, url, commit):
    if destination.exists():
        raise RuntimeError('Refusing to replace an existing source directory')
    run(['git', 'init', '-q', str(destination)])
    run(['git', '-C', str(destination), 'fetch', '--depth=1', url, commit])
    run(['git', '-C', str(destination), 'checkout', '-q', '--detach', 'FETCH_HEAD'])
    actual = run(['git', '-C', str(destination), 'rev-parse', 'HEAD'],
                 capture_output=True, text=True).stdout.strip()
    if actual != commit:
        raise RuntimeError('Pinned checkout mismatch')


def prepare(kernel, results):
    if run(['git', '-C', str(kernel), 'rev-parse', 'HEAD'],
           capture_output=True, text=True).stdout.strip() != '64b40409431988d060f7484369c8c2d7deca1bb3':
        raise RuntimeError('Not the reviewed MiCode baseline')
    suki = kernel.parent / 'sukisu-pinned'
    susfs = kernel.parent / 'susfs-pinned'
    checkout(suki, SUKI_URL, SUKI_SHA)
    checkout(susfs, SUSFS_URL, SUSFS_SHA)
    target = kernel / 'drivers/kernelsu'
    if target.exists() or target.is_symlink():
        raise RuntimeError('KernelSU destination is not empty')
    shutil.copytree(suki / 'kernel', target, symlinks=True)
    mf = target / 'Makefile'
    before = mf.read_bytes()
    if blob(before) != '124d7955116d509477769a07a61d46ccb185e483':
        raise RuntimeError('SukiSU Makefile revision changed')
    text = before.decode('utf-8')
    start = text.index('MDIR    :=')
    stop = text.index('KERNEL_VERSION :=', start)
    replacement = ('REPO_NAME := SukiSU-Ultra\n'
                   'KSU_VERSION := 41023\n'
                   'KSU_VERSION_FULL := v4.2.1-7f1c299a@builtin-cmi\n'
                   'ccflags-y += -DKSU_VERSION=$(KSU_VERSION)\n'
                   'ccflags-y += -DKSU_VERSION_FULL=\\\"$(KSU_VERSION_FULL)\\\"\n\n')
    after = text[:start] + replacement + text[stop:]
    mf.write_text(after, encoding='utf-8')
    (results / 'sukisu-version-lock.patch').write_text(''.join(difflib.unified_diff(
        text.splitlines(True), after.splitlines(True),
        fromfile='a/drivers/kernelsu/Makefile', tofile='b/drivers/kernelsu/Makefile')))
    for relative, addition in (
        ('drivers/Makefile', 'obj-$(CONFIG_KSU) += kernelsu/\n'),
        ('drivers/Kconfig', 'source "drivers/kernelsu/Kconfig"\n'),
    ):
        path = kernel / relative
        source = path.read_text()
        if 'kernelsu/' in source:
            raise RuntimeError('Existing KernelSU integration must be reconciled')
        path.write_text(source.rstrip() + '\n\n' + addition, encoding='utf-8')
    patch = susfs / 'kernel_patches/50_add_susfs_in_kernel-4.19.patch'
    if blob(patch.read_bytes()) != 'a374b74e3535daa08b331851b6c8d9a27d8edb9e':
        raise RuntimeError('SUSFS 4.19 patch revision changed')
    header = susfs / 'kernel_patches/include/linux/susfs.h'
    if blob(header.read_bytes()) != 'ef31283dbc419a7bb20a0042b939d7dc93114859':
        raise RuntimeError('SUSFS header revision changed')
    if '#define SUSFS_VERSION "v1.5.5"' not in header.read_text():
        raise RuntimeError('Unexpected SUSFS protocol')
    # This is a diagnostic dry run, never silent application or a success claim.
    probe = subprocess.run(['git', '-C', str(kernel), 'apply', '--check', '--verbose', str(patch)],
                           text=True, capture_output=True, timeout=120)
    (results / 'susfs-apply-check.log').write_text(probe.stdout + probe.stderr)
    public_sources = results / 'susfs-upstream'
    public_sources.mkdir()
    for relative in (
        'kernel_patches/50_add_susfs_in_kernel-4.19.patch',
        'kernel_patches/include/linux/susfs.h',
        'kernel_patches/include/linux/susfs_def.h',
        'kernel_patches/fs/susfs.c',
    ):
        source = susfs / relative
        shutil.copyfile(source, public_sources / source.name)
    report = {
        'device': 'cmi', 'target_rom': 'V12.5.10.0.RJACNXM',
        'driver_baseline_successful_run': 39289618434,
        'sukisu_source': {'url': SUKI_URL, 'commit': SUKI_SHA, 'version_code': 41023},
        'susfs_source': {'url': SUSFS_URL, 'original_url': 'https://gitlab.com/simonpunk/susfs4ksu.git',
                         'commit': SUSFS_SHA, 'version': '1.5.5'},
        'susfs_apply_check_returncode': probe.returncode,
        'susfs_integration': 'pending_legacy_to_modern_ksu_bridge',
        'stage': 'SukiSU compiler and link compatibility; SUSFS source applicability',
        'previous_custom_source_archive_modified': False,
        'KPM': False, 'flashable': False, 'phone_test': 'not_performed',
    }
    (results / 'root-integration.json').write_text(json.dumps(report, indent=2) + '\n')
    print('SukiSU 41023 source connected to the CMI build; KPM disabled.')
    print('SUSFS 1.5.5 original patch applicability return code:', probe.returncode)
    print('This stage does not claim SUSFS runtime integration or a flashable release.')


def verify(output, results):
    config = (output / '.config').read_text()
    if 'CONFIG_KSU=y\n' not in config or re.search(r'^CONFIG_KPM=[ym]$', config, re.M):
        raise RuntimeError('Unexpected root feature selection')
    if re.search(r'^CONFIG_KSU_SUSFS=[ym]$', config, re.M):
        raise RuntimeError('Do not silently enable the unadapted SUSFS 2.x bridge')
    obj = output / 'drivers/kernelsu/ksu.o'
    if not obj.is_file() or obj.stat().st_size < 10000:
        raise RuntimeError('Missing real KernelSU object')
    elf = run(['readelf', '-h', str(obj)], capture_output=True, text=True).stdout
    if 'AArch64' not in elf:
        raise RuntimeError('Wrong object architecture')
    symbols = (output / 'System.map').read_text()
    if not re.search(r'\b[Tt]\s+kernelsu_init$', symbols, re.M):
        raise RuntimeError('KernelSU initialization not linked')
    shutil.copyfile(obj, results / 'kernelsu-41023-arm64.o')
    (results / 'kernelsu-object-elf.txt').write_text(elf)
    report = json.loads((results / 'root-integration.json').read_text())
    report['sukisu_object_sha256'] = hashlib.sha256(obj.read_bytes()).hexdigest()
    report['sukisu_full_link'] = 'passed'
    report['susfs_integration'] = 'still_pending_not_in_this_image'
    (results / 'root-integration.json').write_text(json.dumps(report, indent=2) + '\n')
    (results / 'NOT_FLASHABLE.txt').write_text(
        'SukiSU compiler/link experiment, not a tested phone kernel.\n'
        'SUSFS bridge and phone boot hooks are not yet validated.\n'
        'Do not flash this artifact or extract its Image for flashing.\n')
    print('Real ARM64 SukiSU object and kernelsu_init link verified; SUSFS remains pending.')


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] not in ('prepare', 'verify'):
        raise SystemExit('usage: prepare-root-integration.py prepare|verify KERNEL_OR_OUT RESULTS')
    first = Path(sys.argv[2]).resolve(strict=True)
    second = Path(sys.argv[3]).resolve(strict=True)
    (prepare if sys.argv[1] == 'prepare' else verify)(first, second)
