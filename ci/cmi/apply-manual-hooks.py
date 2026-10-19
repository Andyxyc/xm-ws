#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Connect the reviewed builtin SukiSU ABI to the pinned CMI kernel.

Integration: xiaomo. The upstream permission checks and normal error paths
remain in place. The volume-key input handler is already registered by SukiSU;
its obsolete no-op input function is deliberately not hooked a second time.
This script does not flash a device or claim hardware validation.
"""
from pathlib import Path
import difflib
import hashlib
import json
import re
import subprocess
import sys

KERNEL_SHA = '64b40409431988d060f7484369c8c2d7deca1bb3'
SUKI_SHA = '7f1c299af463d008e66e714077eb6a8079ff722b'
EXPECTED = {
    'fs/exec.c': '2dcb4b2f512492a0ca898ac0fb1e6f67fe6cc568',
    'fs/open.c': 'b14aef04ee013c237bd023e8865f8bb495d1434e',
    'fs/stat.c': 'f8e6fb2c36576219e9ec81b44828ffc2b058fec1',
    'fs/read_write.c': '4954fae7f73636c27b8a48d1e6d59cceaaeed3dd',
    'kernel/reboot.c': 'af4ceb7f95450f7c8f531dbcd5d511237e0507b0',
    'drivers/kernelsu/ksu.c': '558037d101c3488bd7eec8a2475c876b2d13d5a6',
}
OBJECT_HOOKS = {
    'fs/exec.o': ['ksu_handle_execveat'],
    'fs/open.o': ['ksu_handle_faccessat'],
    'fs/stat.o': ['ksu_handle_stat', 'ksu_handle_vfs_fstat'],
    'fs/read_write.o': ['ksu_handle_vfs_read'],
    'kernel/reboot.o': ['ksu_handle_sys_reboot'],
}
HEADER = '''/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef CMI_KSU_HOOKS_H
#define CMI_KSU_HOOKS_H
#include <linux/fs.h>
#include <linux/types.h>
#ifdef CONFIG_KSU
/* Shared with the implementation to make ABI mismatches compile errors. */
extern bool ksu_vfs_read_hook;
int ksu_handle_execveat(int *fd, struct filename **filename,
                       void *argv, void *envp, int *flags);
int ksu_handle_faccessat(int *dfd, const char __user **filename,
                       int *mode, int *flags);
int ksu_handle_stat(int *dfd, const char __user **filename, int *flags);
int ksu_handle_vfs_read(struct file **file, char __user **buf,
                       size_t *count, loff_t **pos);
void ksu_handle_vfs_fstat(int fd, loff_t *size);
int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd,
                         void __user **arg);
#endif
#endif
'''


def run(argv, **kw):
    return subprocess.run(argv, check=True, timeout=120, **kw)


def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def replace_once(text, old, new):
    if text.count(old) != 1:
        raise RuntimeError('Source anchor is absent or ambiguous: ' + repr(old[:120]))
    return text.replace(old, new, 1)


def function(text, name):
    match = re.search(r'(?m)^(?:static )?int ' + re.escape(name) + r'\([^;]*?\)\n\{', text)
    if not match:
        raise RuntimeError('Function not found: ' + name)
    end, depth = match.end(), 1
    while depth and end < len(text):
        depth += (text[end] == '{') - (text[end] == '}')
        end += 1
    if depth:
        raise RuntimeError('Unbalanced function: ' + name)
    return text[match.start():end]


def test_wrappers(original, edited, results):
    """Compile the exact changed wrappers with instrumented callees, not a phone."""
    prefix = r'''#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
typedef uint32_t u32;
#define EBADF 9
#define EINVAL 22
#define KSTAT_QUERY_FLAGS 0x6000U
#define IS_ERR_OR_NULL(p) (!(p) || (uintptr_t)(p) >= (uintptr_t)-4095L)
struct filename { const char *name; };
struct user_arg_ptr { int is_compat; const void *ptr; };
struct file { int f_path; };
struct fd { struct file *file; };
struct kstat { long long size; };
static unsigned exec_calls, hook_calls, put_calls, stat_hook_calls, attr_calls;
static int exec_return, attr_return;
static struct file file_object;
static struct user_arg_ptr expected_argv, expected_envp;
static int __do_execve_file(int fd, struct filename *filename,
    struct user_arg_ptr argv, struct user_arg_ptr envp, int flags, struct file *file)
{
    assert(fd == 11 && flags == 3 && file == NULL);
    assert(argv.is_compat == expected_argv.is_compat && argv.ptr == expected_argv.ptr);
    assert(envp.is_compat == expected_envp.is_compat && envp.ptr == expected_envp.ptr);
    (void)filename; ++exec_calls; return exec_return;
}
#ifdef CONFIG_KSU
static int ksu_handle_execveat(int *fd, struct filename **filename,
                             void *argv, void *envp, int *flags)
{
    struct user_arg_ptr *a = argv, *e = envp;
    assert(*fd == 11 && *flags == 3 && !IS_ERR_OR_NULL(*filename));
    assert(a->ptr == expected_argv.ptr && e->ptr == expected_envp.ptr);
    ++hook_calls; return 0;
}
static void ksu_handle_vfs_fstat(int fd, long long *size)
{ assert(fd == 12); ++stat_hook_calls; *size += 7; }
#endif
static struct fd fdget_raw(unsigned fd)
{ return (struct fd){ .file = fd == 12 ? &file_object : NULL }; }
static void fdput(struct fd f)
{ assert(f.file == &file_object); ++put_calls; }
static int vfs_getattr(int *path, struct kstat *stat, unsigned mask, unsigned flags)
{
    assert(path == &file_object.f_path && mask == 9 && flags == 0);
    ++attr_calls; if (!attr_return) stat->size = 20; return attr_return;
}
'''
    test = r'''int main(void)
{
    struct filename name = {"/system/bin/sh"};
    struct filename *names[] = {&name, NULL, (struct filename *)-2L};
    for (int compat = 0; compat <= 1; ++compat) {
        expected_argv = (struct user_arg_ptr){compat, &name};
        expected_envp = (struct user_arg_ptr){compat, names};
        for (unsigned i = 0; i < 3; ++i) {
            exec_return = i == 0 ? 0 : -2;
            assert(do_execveat_common(11, names[i], expected_argv, expected_envp, 3) == exec_return);
        }
    }
    assert(exec_calls == 6);
#ifdef CONFIG_KSU
    assert(hook_calls == 2);
#else
    assert(hook_calls == 0);
#endif
    struct kstat st = {0};
    assert(vfs_statx_fd(12, &st, 9, 1) == -EINVAL);
    assert(!attr_calls && !put_calls && !stat_hook_calls);
    assert(vfs_statx_fd(13, &st, 9, 0) == -EBADF);
    assert(!attr_calls && !put_calls && !stat_hook_calls);
    attr_return = -13;
    assert(vfs_statx_fd(12, &st, 9, 0) == -13);
    assert(attr_calls == 1 && put_calls == 1 && !stat_hook_calls && st.size == 0);
    attr_return = 0;
    assert(vfs_statx_fd(12, &st, 9, 0) == 0);
    assert(attr_calls == 2 && put_calls == 2);
#ifdef CONFIG_KSU
    assert(stat_hook_calls == 1 && st.size == 27);
#else
    assert(!stat_hook_calls && st.size == 20);
#endif
    return 0;
}
'''
    checks = []
    for enabled in (False, True):
        suffix = 'enabled' if enabled else 'disabled'
        source = prefix + function(edited['fs/exec.c'], 'do_execveat_common') + '\n'
        source += function(edited['fs/stat.c'], 'vfs_statx_fd') + '\n' + test
        unit = results / ('manual-wrapper-test-' + suffix + '.c')
        binary = results / ('manual-wrapper-test-' + suffix)
        unit.write_text(source, encoding='utf-8')
        command = ['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror']
        if enabled:
            command += ['-DCONFIG_KSU=1']
        run(command + [str(unit), '-o', str(binary)])
        run([str(binary)])
        if not enabled:
            for relative, name in (('fs/exec.c', 'do_execveat_common'), ('fs/stat.c', 'vfs_statx_fd')):
                outputs = []
                for sources in (original, edited):
                    value = run(['cc', '-E', '-P', '-x', 'c', '-'],
                                input=function(sources[relative], name), text=True,
                                capture_output=True).stdout
                    outputs.append(re.sub(r'\s+', '', value))
                if outputs[0] != outputs[1]:
                    raise RuntimeError('CONFIG_KSU=off changed the original wrapper: ' + name)
        checks.append({'CONFIG_KSU': enabled, 'result': 'passed',
                       'scope': 'exact exec/fstat wrappers, native/compat argv, invalid filename/fd/flags and getattr failure'})
    return checks


def apply(kernel, results):
    original = {}
    for relative, expected in EXPECTED.items():
        path = kernel / relative
        if not path.resolve(strict=True).is_relative_to(kernel):
            raise RuntimeError('Source escapes pinned tree')
        data = path.read_bytes()
        if blob(data) != expected:
            raise RuntimeError('Source changed or patch already applied: ' + relative)
        original[relative] = data.decode('utf-8')
    header = kernel / 'include/linux/cmi_ksu_hooks.h'
    if header.exists() or header.is_symlink():
        raise RuntimeError('Hook ABI header already exists')
    edited = dict(original)
    old = '\treturn __do_execve_file(fd, filename, argv, envp, flags, NULL);\n'
    edited['fs/exec.c'] = replace_once(edited['fs/exec.c'], old,
        '#ifdef CONFIG_KSU\n\tif (!IS_ERR_OR_NULL(filename))\n'
        '\t\tksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);\n#endif\n' + old)
    old = '\tunsigned int lookup_flags = LOOKUP_FOLLOW;\n\n\tif (mode & ~S_IRWXO)'
    edited['fs/open.c'] = replace_once(edited['fs/open.c'], old,
        '\tunsigned int lookup_flags = LOOKUP_FOLLOW;\n\n#ifdef CONFIG_KSU\n'
        '\tksu_handle_faccessat(&dfd, &filename, &mode, NULL);\n#endif\n\n\tif (mode & ~S_IRWXO)')
    old = '\tunsigned int lookup_flags = LOOKUP_FOLLOW | LOOKUP_AUTOMOUNT;\n\n'
    edited['fs/stat.c'] = replace_once(edited['fs/stat.c'], old, old +
        '#ifdef CONFIG_KSU\n\tksu_handle_stat(&dfd, &filename, &flags);\n#endif\n\n')
    old = ('\t\terror = vfs_getattr(&f.file->f_path, stat,\n'
           '\t\t\t\t    request_mask, query_flags);\n\t\tfdput(f);')
    edited['fs/stat.c'] = replace_once(edited['fs/stat.c'], old,
        old[:-len('\t\tfdput(f);')] + '#ifdef CONFIG_KSU\n\t\tif (!error)\n'
        '\t\t\tksu_handle_vfs_fstat(fd, &stat->size);\n#endif\n\t\tfdput(f);')
    old = ('ssize_t vfs_read(struct file *file, char __user *buf, size_t count, loff_t *pos)\n'
           '{\n\tssize_t ret;\n\n')
    edited['fs/read_write.c'] = replace_once(edited['fs/read_write.c'], old, old +
        '#ifdef CONFIG_KSU\n\tif (ksu_vfs_read_hook)\n'
        '\t\tksu_handle_vfs_read(&file, &buf, &count, &pos);\n#endif\n\n')
    old = '\tint ret = 0;\n\n\tif (check_poweroff_charger_mode())'
    edited['kernel/reboot.c'] = replace_once(edited['kernel/reboot.c'], old,
        '\tint ret = 0;\n\n#ifdef CONFIG_KSU\n'
        '\tksu_handle_sys_reboot(magic1, magic2, cmd, &arg);\n#endif\n\n'
        '\tif (check_poweroff_charger_mode())')
    # Host regression uses the actual modified wrappers before includes are added.
    checks = test_wrappers(original, edited, results)
    include = '#include <linux/cmi_ksu_hooks.h>\n'
    for relative in OBJECT_HOOKS:
        source_path = relative[:-1] + 'c'
        match = re.search(r'(?m)^#include ', edited[source_path])
        if not match:
            raise RuntimeError('No include boundary in ' + source_path)
        pos = match.start()
        edited[source_path] = edited[source_path][:pos] + include + edited[source_path][pos:]
    edited['drivers/kernelsu/ksu.c'] = replace_once(edited['drivers/kernelsu/ksu.c'],
        '#include "kernel_includes.h"\n', '#include "kernel_includes.h"\n' + include)
    diffs = []
    hashes = {}
    for relative, after in edited.items():
        diffs.extend(difflib.unified_diff(original[relative].splitlines(True), after.splitlines(True),
                                        fromfile='a/' + relative, tofile='b/' + relative))
        (kernel / relative).write_text(after, encoding='utf-8')
        hashes[relative] = hashlib.sha256(after.encode()).hexdigest()
    header.write_text(HEADER, encoding='utf-8')
    diffs.extend(difflib.unified_diff([], HEADER.splitlines(True), fromfile='/dev/null',
                                    tofile='b/include/linux/cmi_ksu_hooks.h'))
    (results / 'cmi-manual-hooks.patch').write_text(''.join(diffs), encoding='utf-8')
    (results / 'cmi_ksu_hooks.h').write_text(HEADER, encoding='utf-8')
    (results / 'manual-hooks-result.json').write_text(json.dumps({
        'kernel_commit': KERNEL_SHA, 'sukisu_commit': SUKI_SHA,
        'source_blobs': EXPECTED, 'after_sha256': hashes, 'host_tests': checks,
        'hook_sites': OBJECT_HOOKS, 'real_arm64_object_relocations': 'pending',
        'phone_boot': 'not_tested', 'SUSFS_runtime': 'not_integrated',
        'upstream_manager_authentication_modified': False,
        'SELinux_enforcement_disabled': False, 'obsolete_input_noop_hooked': False
    }, indent=2) + '\n')
    print('CMI builtin hook sites connected; exact exec/fstat host regression passed.')


def verify(output, results):
    config = (output / '.config').read_text()
    if 'CONFIG_KSU=y\n' not in config or 'CONFIG_KSU_SUSFS=y\n' in config:
        raise RuntimeError('Unexpected SukiSU hook ABI selection')
    symbols = (output / 'System.map').read_text()
    checks = {}
    for relative, hooks in OBJECT_HOOKS.items():
        path = output / relative
        elf = run(['readelf', '-h', str(path)], capture_output=True, text=True).stdout
        if 'AArch64' not in elf:
            raise RuntimeError('Wrong architecture: ' + relative)
        undefined = run(['nm', '-u', str(path)], capture_output=True, text=True).stdout
        for hook in hooks:
            if not re.search(r'\bU\s+' + hook + r'$', undefined, re.M):
                raise RuntimeError('Hook call missing from actual object: ' + relative + ': ' + hook)
            if not re.search(r'\b[Tt]\s+' + hook + r'$', symbols, re.M):
                raise RuntimeError('Hook implementation missing from final kernel: ' + hook)
        checks[relative] = {'undefined_hook_references': hooks,
                            'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    report_path = results / 'manual-hooks-result.json'
    report = json.loads(report_path.read_text())
    report['real_arm64_object_relocations'] = checks
    report['final_link'] = 'passed'
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    print('All six builtin hook calls verified in real ARM64 objects and final System.map.')


if __name__ == '__main__':
    if len(sys.argv) != 4 or sys.argv[1] not in ('apply', 'verify'):
        raise SystemExit('usage: apply-manual-hooks.py apply|verify KERNEL_OR_OUT RESULTS')
    root = Path(sys.argv[2]).resolve(strict=True)
    results = Path(sys.argv[3]).resolve(strict=True)
    (apply if sys.argv[1] == 'apply' else verify)(root, results)
