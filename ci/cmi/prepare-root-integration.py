#!/usr/bin/env python3
"""CMI root integration stage; no phone access or flashable packaging.

Reuse the verified MiCode driver baseline. Preserve original source archives.
Compile pinned upstream SukiSU and record the legacy SUSFS patch applicability.
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


def repair_legacy_compile(target, results):
    expected = {
        'policy/allowlist.c': 'da3cff356f76c7bcfbac06e9ada58247cc775c7e',
        'policy/feature.c': 'e5116ab2cd0ce2ef58df912959be5d7c3faebf05',
        'runtime/ksud.c': '2213078c429a9a6766f85f306897d54b96c27220',
        'sulog/event.c': 'e45f01fac4799c4955cb17019132c227706a9e98',
        'include/uapi/feature.h': 'a27a9aa8e03c31040f206376c5d777246350234f',
        'ksu.c': '558037d101c3488bd7eec8a2475c876b2d13d5a6',
    }
    original = {}
    for relative, sha in expected.items():
        path = target / relative
        if not path.resolve(strict=True).is_relative_to(target.resolve()):
            raise RuntimeError('Source path escapes KernelSU directory')
        data = path.read_bytes()
        if blob(data) != sha:
            raise RuntimeError('Unreviewed source or repeated patch: ' + relative)
        original[relative] = data.decode('utf-8')
    edited = dict(original)
    guard = '#if LINUX_VERSION_CODE >= KERNEL_VERSION(5, 10, 0)\n'
    # The pinned unity build, declaration and init are already gated at 5.10.
    for include in ('feature/selinux_hide.h', 'feature/selinux_hide.c'):
        if guard + '#include "' + include + '"\n#endif' not in original['ksu.c']:
            raise RuntimeError('Upstream SELinux-hide support boundary changed')
    feature_line = '    [KSU_FEATURE_SELINUX_HIDE] = "selinux_hide",\n'
    if edited['policy/feature.c'].count(feature_line) != 1:
        raise RuntimeError('Ambiguous optional feature-name entry')
    feature_block = guard + feature_line + '#endif\n'
    edited['policy/feature.c'] = edited['policy/feature.c'].replace(feature_line, feature_block)
    call_blocks = []
    for name, count in (('ksu_selinux_hide_handle_post_fs_data', 1),
                        ('ksu_selinux_hide_handle_second_stage', 2)):
        pattern = re.compile(r'(?m)^([ \t]*)' + name + r'\(\);\n')
        matches = list(pattern.finditer(edited['runtime/ksud.c']))
        if len(matches) != count:
            raise RuntimeError('Unexpected optional feature call count: ' + name)
        def wrap(match):
            block = guard + match.group(0) + '#endif\n'
            call_blocks.append(block)
            return block
        edited['runtime/ksud.c'] = pattern.sub(wrap, edited['runtime/ksud.c'])
    old = '        fallthrough;\n'
    new = '        __attribute__((__fallthrough__));\n'
    if edited['policy/allowlist.c'].count(old) != 1:
        raise RuntimeError('Profile migration fallthrough changed')
    edited['policy/allowlist.c'] = edited['policy/allowlist.c'].replace(old, new)
    old = '    #define USER_ARG_NULL user_arg_null_ptr()\n'
    macro = ('#ifdef CONFIG_KSU_SUSFS\n'
             '#define USER_ARG_NULL user_arg_null_ptr()\n'
             '#else\n#define USER_ARG_NULL (*user_arg_null_ptr())\n#endif\n')
    if edited['sulog/event.c'].count(old) != 1:
        raise RuntimeError('Sulog null-argument call changed')
    if 'const struct user_arg_ptr argv, gfp_t gfp)' not in original['sulog/event.c']:
        raise RuntimeError('Non-SUSFS sulog no longer uses by-value argv')
    edited['sulog/event.c'] = edited['sulog/event.c'].replace(old, macro)
    # Compile the exact changed conditional fragments with both source versions
    # and both argv ABIs. No SELinux-hide implementation is invented for 4.19.
    prefix = r'''#include <assert.h>
#include <stddef.h>
#define KERNEL_VERSION(a,b,c) (((a) << 16) + ((b) << 8) + (c))
static unsigned hide_calls;
#if LINUX_VERSION_CODE >= KERNEL_VERSION(5,10,0)
static void ksu_selinux_hide_handle_post_fs_data(void) { ++hide_calls; }
static void ksu_selinux_hide_handle_second_stage(void) { ++hide_calls; }
#endif
struct user_arg_ptr { int is_compat; union { const void *native; const void *compat; } ptr; };
static struct user_arg_ptr *user_arg_null_ptr(void)
{ static struct user_arg_ptr null_arg = {0}; return &null_arg; }
#ifdef CONFIG_KSU_SUSFS
static void capture(struct user_arg_ptr *argv)
{ assert(argv && !argv->ptr.native && !argv->is_compat); }
#else
static void capture(struct user_arg_ptr argv)
{ assert(!argv.ptr.native && !argv.is_compat); }
#endif
'''
    source = prefix + original['include/uapi/feature.h']
    source += 'static const char *const feature_names[KSU_FEATURE_MAX] = {\n'
    source += '    [KSU_FEATURE_SU_COMPAT] = "su_compat",\n' + feature_block + '};\n'
    source += macro + 'static void invoke_optional_hooks(void) {\n' + ''.join(call_blocks) + '}\n'
    source += ('static int migration(int version) {\n    int result = 0;\n'
               '    switch (version) { case 2: result += 2;\n' + new +
               '    case 3: result += 3; break; }\n    return result;\n}\n')
    source += r'''int main(void) {
    capture(USER_ARG_NULL);
    invoke_optional_hooks();
    assert(migration(2) == 5 && migration(3) == 3 && migration(1) == 0);
    assert(KSU_FEATURE_MAX == 7 && feature_names[0]);
#if LINUX_VERSION_CODE >= KERNEL_VERSION(5,10,0)
    assert(hide_calls == 3 && feature_names[4]);
#else
    assert(hide_calls == 0 && !feature_names[4]);
#endif
    return 0;
}
'''
    test = results / 'sukisu-legacy-compile-regression.c'
    test.write_text(source, encoding='utf-8')
    checks = []
    for version, code in (('4.19', 267008), ('5.10', 330240)):
        for susfs in (False, True):
            name = version.replace('.', '-') + ('-pointer' if susfs else '-value')
            binary = results / ('sukisu-compile-test-' + name)
            argv = ['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-Wimplicit-fallthrough=5', '-DLINUX_VERSION_CODE=' + str(code)]
            if susfs:
                argv += ['-DCONFIG_KSU_SUSFS=1']
            run(argv + [str(test), '-o', str(binary)])
            run([str(binary)])
            checks.append({'version_boundary': version, 'argv_abi': name, 'result': 'passed'})
    diffs = []
    hashes = {}
    for relative in expected:
        if edited[relative] == original[relative]:
            continue
        diffs.extend(difflib.unified_diff(original[relative].splitlines(True),
                     edited[relative].splitlines(True),
                     fromfile='a/drivers/kernelsu/' + relative,
                     tofile='b/drivers/kernelsu/' + relative))
        (target / relative).write_text(edited[relative], encoding='utf-8')
        hashes[relative] = hashlib.sha256((target / relative).read_bytes()).hexdigest()
    (results / 'sukisu-legacy-compile.patch').write_text(''.join(diffs), encoding='utf-8')
    (results / 'sukisu-legacy-compile-checks.json').write_text(json.dumps({
        'upstream_commit': SUKI_SHA, 'source_blobs': expected, 'after_sha256': hashes,
        'host_configurations': checks, 'real_arm64_compile': 'pending',
        'selinux_enforcing_changed': False, 'CRC_checks_disabled': False,
        'SUSFS_runtime_claimed': False, 'phone_test': 'not_performed'
    }, indent=2) + '\n')
    print('SukiSU legacy guards and argv types repaired; four host configuration tests passed.')


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
    repair_legacy_compile(target, results)
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
        'compile_repairs': 'sukisu-legacy-compile-checks.json',
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
