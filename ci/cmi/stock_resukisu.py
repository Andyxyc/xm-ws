#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""CMI official-source ReSukiSU bring-up, not a flashable release.

Stage one intentionally validates manual root hooks separately from SUSFS.
Never applies RC3/RC4 binary changes or the experimental Kona defer patch.
"""
from pathlib import Path
import argparse
import difflib
import hashlib
import importlib.util
import json
import re
import subprocess
import zipfile

BRANCH = 'cmi-stockboot-resukisu-20261104'
KERNEL_SHA = '64b40409431988d060f7484369c8c2d7deca1bb3'
ROOT_SHA = 'f1dd81dc96d7f3f6691e6ac8b50fba9ae8a2f17c'
ROOT_URL = 'https://github.com/xixiaobei-bei/ReSukiSU.git'
BLOBS = {
    'fs/exec.c': '2dcb4b2f512492a0ca898ac0fb1e6f67fe6cc568',
    'fs/open.c': 'b14aef04ee013c237bd023e8865f8bb495d1434e',
    'fs/stat.c': 'f8e6fb2c36576219e9ec81b44828ffc2b058fec1',
    'kernel/reboot.c': 'af4ceb7f95450f7c8f531dbcd5d511237e0507b0',
}
EXEC = '''static int do_execveat_common(int fd, struct filename *filename,
\t\t\t      struct user_arg_ptr argv,
\t\t\t      struct user_arg_ptr envp,
\t\t\t      int flags)
{
\treturn __do_execve_file(fd, filename, argv, envp, flags, NULL);
}
'''
ACCESS = '''SYSCALL_DEFINE3(faccessat, int, dfd, const char __user *, filename, int, mode)
{
\treturn do_faccessat(dfd, filename, mode);
}
'''

def run(argv, **kw):
    return subprocess.run(argv, check=True, timeout=900, **kw)


def git_blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def replace_one(text, old, new):
    if text.count(old) != 1:
        raise ValueError('Unexpected source anchor: ' + old[:90])
    return text.replace(old, new, 1)


def guarded(code):
    return '#ifdef CONFIG_KSU_MANUAL_HOOK\n' + code + '#endif\n'


def hook_source(name, raw, strict=True):
    if strict and git_blob(raw) != BLOBS[name]:
        raise ValueError('Unreviewed source revision: ' + name)
    s = raw.decode('utf-8')
    if 'ksu_handle_' in s:
        raise ValueError('Existing hooks require reconciliation')
    if name == 'fs/exec.c':
        decl = guarded('extern int ksu_handle_execveat(int *fd, struct filename **filename,\n'
                       '\t\tvoid *argv, void *envp, int *flags);\n')
        new = EXEC.replace('\treturn __do_execve_file', guarded(
            '\tksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);\n') + '\treturn __do_execve_file')
        s = replace_one(s, EXEC, decl + '\n' + new)
    elif name == 'fs/open.c':
        decl = guarded('extern int ksu_handle_faccessat(int *dfd, const char __user **filename,\n'
                       '\t\tint *mode, int *flags);\n')
        new = ACCESS.replace('\treturn do_faccessat', guarded(
            '\tksu_handle_faccessat(&dfd, &filename, &mode, NULL);\n') + '\treturn do_faccessat')
        s = replace_one(s, ACCESS, decl + '\n' + new)
    elif name == 'fs/stat.c':
        decl = guarded('extern int ksu_handle_stat(int *dfd, const char __user **filename, int *flags);\n'
                       'extern void ksu_handle_newfstat_ret(unsigned int *fd, struct stat __user **statbuf);\n'
                       '#if defined(__ARCH_WANT_STAT64) || defined(__ARCH_WANT_COMPAT_STAT64)\n'
                       'extern void ksu_handle_fstat64_ret(unsigned long *fd, struct stat64 __user **statbuf);\n'
                       '#endif\n')
        s = replace_one(s, 'SYSCALL_DEFINE2(newstat,', decl + '\nSYSCALL_DEFINE2(newstat,')
        for call, bit in [('newfstatat', 'at'), ('fstatat64', 'at'), ('newfstat', 'ret'), ('fstat64', 'ret')]:
            pat = re.compile(r'SYSCALL_DEFINE[24]\(' + call + r',.*?\n\}', re.S)
            matches = list(pat.finditer(s))
            if len(matches) != 1:
                raise ValueError('Ambiguous syscall ' + call)
            m = matches[0]; old = m.group(0)
            if bit == 'at':
                anchor = '\terror = vfs_fstatat(dfd, filename, &stat, flag);'
                new = replace_one(old, anchor, guarded('\tksu_handle_stat(&dfd, &filename, &flag);\n') + anchor)
            else:
                anchor = '\treturn error;'
                handler = 'ksu_handle_newfstat_ret' if call == 'newfstat' else 'ksu_handle_fstat64_ret'
                new = replace_one(old, anchor, guarded('\t' + handler + '(&fd, &statbuf);\n') + anchor)
            s = s[:m.start()] + new + s[m.end():]
    elif name == 'kernel/reboot.c':
        anchor = 'SYSCALL_DEFINE4(reboot, int, magic1, int, magic2, unsigned int, cmd,'
        decl = guarded('extern int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd, void __user **arg);\n')
        s = replace_one(s, anchor, decl + '\n' + anchor)
        s = replace_one(s, '\tif (check_poweroff_charger_mode()){',
                        guarded('\tksu_handle_sys_reboot(magic1, magic2, cmd, &arg);\n') + '\tif (check_poweroff_charger_mode()){')
    else:
        raise ValueError('Unexpected hook target')
    return s.encode()


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def prepare(root):
    old = load_module(root/'ci/cmi/audio_rebuild_20261101.py', 'audio_baseline')
    deps, build = old.generated_scripts(root)
    deps = replace_one(deps, 'refs/heads/' + old.BRANCH, 'refs/heads/' + BRANCH)
    build = replace_one(build,
        'python3 "$ROOT/ci/cmi/audio_rebuild_20261101.py" patch-kona "$WORK/kernel" "$ROOT/driver-results"\n',
        'python3 "$ROOT/ci/cmi/stock_resukisu.py" integrate "$WORK/kernel" "$ROOT/driver-results"\n')
    anchor = '"${MAKE[@]}" olddefconfig\n'
    options = ('"$WORK/kernel/scripts/config" --file "$WORK/out/.config" -e KSU -e KALLSYMS_ALL '
               '-e KSU_MANUAL_HOOK -e KSU_MANUAL_HOOK_AUTO_SETUID_HOOK '
               '-e KSU_MANUAL_HOOK_AUTO_INITRC_HOOK -e KSU_MANUAL_HOOK_AUTO_INPUT_HOOK '
               '-d KSU_TRACEPOINT_HOOK -d KSU_SUSFS -d KSU_DEBUG -d KPM\n')
    build = replace_one(build, anchor, options + anchor)
    # Configuration comparisons are evidence, not an excuse to relabel this as a stock binary.
    build = replace_one(build, '"${MAKE[@]}" Image.gz\n',
        '"${MAKE[@]}" Image.gz\n"${MAKE[@]}" modules\n'
        'mkdir -p "$ROOT/driver-results/rebuilt-modules"\n'
        'find "$WORK/out" -type f -name "*.ko" -exec cp --parents {} "$ROOT/driver-results/rebuilt-modules/" \\;\n')
    build = build.replace('audio compatibility experiment. NOT FLASHABLE.', 'official-source ReSukiSU bring-up. NOT FLASHABLE.')
    build = build.replace('Untested driver baseline, without SukiSU. NOT FLASHABLE.', 'ReSukiSU manual-root bring-up; SUSFS and stock boot repack pending. NOT FLASHABLE.')
    if 'patch-kona' in build or 'cmi-kona-probe-defer-experiment' in build:
        raise ValueError('Old experimental audio patch remained')
    for name, data in [('build-cmi-stock-deps.sh', deps), ('build-cmi-stock-root.sh', build)]:
        (root/name).write_text(data)


def integrate(kernel, results):
    kernel = kernel.resolve(strict=True)
    head = run(['git', '-C', str(kernel), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    if head != KERNEL_SHA:
        raise ValueError('Wrong kernel baseline')
    results.mkdir(parents=True, exist_ok=True)
    # Review every expected source file before making any changes.
    changes = {name: (kernel/name).read_bytes() for name in BLOBS}
    updates = {name: hook_source(name, raw) for name, raw in changes.items()}
    target = kernel/'ReSukiSU'
    link = kernel/'drivers/kernelsu'
    if target.exists() or link.exists() or link.is_symlink():
        raise ValueError('Existing root integration was not replaced')
    run(['git', 'clone', '--quiet', '--no-checkout', ROOT_URL, str(target)])
    run(['git', '-C', str(target), 'checkout', '--quiet', '--detach', ROOT_SHA])
    actual = run(['git', '-C', str(target), 'rev-parse', 'HEAD'], capture_output=True, text=True).stdout.strip()
    if actual != ROOT_SHA:
        raise ValueError('ReSukiSU checkout mismatch')
    # This pinned revision has no post-exec hook; never copy a newer incompatible guide.
    if 'int ksu_handle_execveat(' not in (target/'kernel/feature/sucompat.c').read_text():
        raise ValueError('Pinned root hook API changed')
    link.symlink_to('../ReSukiSU/kernel')
    patch = []
    for name, after in updates.items():
        before = changes[name]
        patch.extend(difflib.unified_diff(before.decode().splitlines(True), after.decode().splitlines(True),
                      fromfile='a/'+name, tofile='b/'+name))
        (kernel/name).write_bytes(after)
    for name, line in [('drivers/Makefile','obj-$(CONFIG_KSU) += kernelsu/\n'),
                       ('drivers/Kconfig','source "drivers/kernelsu/Kconfig"\n')]:
        p=kernel/name; before=p.read_text()
        if 'kernelsu/' in before:
            raise ValueError('Existing root include')
        p.write_text(before.rstrip()+'\n\n'+line)
    (results/'resukisu-manual-hooks.patch').write_text(''.join(patch))
    (results/'root-source-lock.json').write_text(json.dumps({
        'kernel_commit': KERNEL_SHA, 'root_repo': ROOT_URL, 'root_commit': ROOT_SHA,
        'hook_files': {n: {'before_blob': BLOBS[n], 'after_sha256': hashlib.sha256(updates[n]).hexdigest()} for n in BLOBS},
        'binary_patches_from_RC3_RC4': False, 'experimental_Kona_defer_patch': False,
        'SUSFS_enabled': False, 'SUSFS_status': 'not integrated in this manual-root bring-up stage',
        'stock_driver_sources': True, 'stock_binary_identical': False,
        'flashable': False, 'phone_tested': False,
    }, indent=2)+'\n')


def stock_reference(root):
    stock = load_module(root/'ci/cmi/stock-rom-probe.py', 'stock_probe')
    dest = root/'stock-reference'; dest.mkdir(exist_ok=False)
    remote = stock.RemoteRange(stock.OFFICIAL_ZIP)
    report = {'official_url':stock.OFFICIAL_ZIP, 'whole_rom_digest_verified':False, 'files':{}}
    with zipfile.ZipFile(remote) as z:
        meta = z.read('META-INF/com/android/metadata').decode()
        if not {'pre-device=cmi','post-build-incremental=V12.5.10.0.RJACNXM'} <= set(meta.splitlines()):
            raise ValueError('ROM identity mismatch')
        for name, maximum in [('boot.img',128*1024**2),('dtbo.img',64*1024**2)]:
            hits = [i for i in z.infolist() if Path(i.filename).name == name]
            if len(hits)!=1 or not 0<hits[0].file_size<=maximum:
                raise ValueError('Missing or excessive member: '+name)
            raw=z.read(hits[0])  # ZIP validates this member's CRC.
            if name=='boot.img' and not raw.startswith(b'ANDROID!'):
                raise ValueError('Not Android boot')
            if name=='dtbo.img' and not raw.startswith(bytes.fromhex('d7b7ab1e')):
                raise ValueError('Not Android DTBO')
            (dest/name).write_bytes(raw)
            report['files'][name]={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'zip_crc32':f'{hits[0].CRC:08x}'}
    (dest/'stock-identity.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


def verify(root):
    out=root/'driver-results'
    config=set((out/'kernel.config').read_text().splitlines())
    for line in ['CONFIG_KSU=y','CONFIG_KSU_MANUAL_HOOK=y','CONFIG_MODVERSIONS=y']:
        if line not in config:raise ValueError('Missing '+line)
    for line in ['CONFIG_KSU_SUSFS=y','CONFIG_KSU_TRACEPOINT_HOOK=y','CONFIG_KPM=y']:
        if line in config:raise ValueError('Unexpected unintegrated feature '+line)
    names={line.split()[-1] for line in (out/'System.map').read_text().splitlines() if line.split()}
    required=['ksu_handle_execveat','ksu_handle_stat','ksu_handle_faccessat','ksu_handle_sys_reboot',
              'ksu_handle_newfstat_ret','ksu_handle_fstat64_ret','kona_asoc_machine_driver','snd_soc_register_card']
    missing=set(required)-names
    if missing:raise ValueError('Missing linked root/audio symbols: '+repr(missing))
    (out/'root-link-report.json').write_text(json.dumps({'linked':required, 'phone_tested':False,
        'SUSFS_integrated':False,'flashable':False,'stock_boot_repacked':False},indent=2)+'\n')
    (out/'NOT_FLASHABLE.txt').write_text('Official-source ReSukiSU bring-up only. SUSFS, stock boot repack and runtime tests pending. DO NOT FLASH.\n')


def main():
    p=argparse.ArgumentParser();p.add_argument('op',choices=['prepare','integrate','stock-reference','verify'])
    p.add_argument('root',type=Path);p.add_argument('results',nargs='?',type=Path);a=p.parse_args()
    if a.op=='integrate':
        if a.results is None:p.error('results directory required')
        integrate(a.root,a.results)
    else:globals()[a.op.replace('-','_')](a.root.resolve(strict=True))

if __name__=='__main__':main()
