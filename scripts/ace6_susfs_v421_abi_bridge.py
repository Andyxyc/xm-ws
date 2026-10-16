#!/usr/bin/env python3
"""Adapt exactly SukiSU v4.2.1's ksud hook to the SUSFS v2.3.0 dispatcher ABI.

Keep v4.2.1's second-stage side effects, forced features and module blocklist.
Do not remove SUSFS guard checks. Fail closed for unknown source changes.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import tempfile
import subprocess

OLD = 'void ksu_handle_execveat_ksud(const char *path, struct user_arg_ptr *argv)'
NEW = 'int ksu_handle_execveat_ksud(int *fd, struct filename **filename_ptr,'
AFTER = 'static ssize_t (*orig_read)(struct file *, char __user *, size_t, loff_t *);'
TAG = 'ACE6_V421_NATIVE_KSUD_TO_DISPATCH_ADAPTER_20261016'

IMPLEMENTATION = r'''/* ACE6_V421_NATIVE_KSUD_TO_DISPATCH_ADAPTER_20261016
 * Keep the SukiSU 4.2.1 second-stage lifecycle/forced options while bridging
 * to SUSFS' fd/filename dispatcher. The former path/argv entrypoint was
 * removed from the dispatcher by SUSFS 2.3.0.
 */
int ksu_handle_execveat_ksud(int *fd, struct filename **filename_ptr,
                             struct user_arg_ptr *argv,
                             struct user_arg_ptr *envp, int *flags)
{
    struct filename *filename;
    static const char app_process[] = "/system/bin/app_process";
    static const char system_bin_init[] = "/system/bin/init";

    (void)fd;
    (void)envp;
    (void)flags;
    if (!filename_ptr || !argv)
        return 0;

    filename = *filename_ptr;
    if (IS_ERR_OR_NULL(filename) || !filename->name)
        return 0;

    if (static_branch_unlikely(&is_init_second_stage_not_executed) &&
        unlikely(!memcmp(filename->name, system_bin_init,
                         sizeof(system_bin_init) - 1))) {
        char buf[16];

        if (check_argv(*argv, 1, "second_stage", buf, sizeof(buf))) {
            pr_info("/system/bin/init second_stage executed\n");
            ksu_selinux_hide_handle_second_stage();
            apply_kernelsu_rules();
            cache_sid();
            setup_ksu_cred();
            /* SukiSU v4.2.1 extras: do not drop these on older patchsets. */
            ksu_feature_apply_forced();
            ksu_module_blacklist_apply();
            static_branch_disable(&is_init_second_stage_not_executed);
        }
    }

    if (static_branch_unlikely(&is_first_zygote) &&
        unlikely(!memcmp(filename->name, app_process,
                         sizeof(app_process) - 1))) {
        char buf[16];

        if (check_argv(*argv, 1, "-Xzygote", buf, sizeof(buf))) {
            pr_info("exec zygote, /data prepared, second_stage: %d\n",
                    !static_key_enabled(&is_init_second_stage_not_executed));
            on_post_fs_data();
            static_branch_disable(&is_first_zygote);
        }
    }
    return 0;
}

'''


def transform(src: str) -> str:
    if TAG in src:
        if src.count(TAG) != 1 or src.count(NEW) != 1 or OLD in src:
            raise ValueError('Already adapted source was altered or duplicated')
        return src
    checks = [
        (src.count(OLD) == 1, 'exact native function signature'),
        (src.count(AFTER) == 1, 'read hook following native callback'),
        (src.count('DEFINE_STATIC_KEY_TRUE(is_init_second_stage_not_executed)') == 1,
         'SUSFS second-stage key'),
        (src.count('DEFINE_STATIC_KEY_TRUE(is_first_zygote)') == 1,
         'SUSFS first-zygote key'),
        ('ksu_handle_execveat_ksud(path, &argv);' not in src,
         'old SukiSU dispatcher was not removed'),
    ]
    for ok,desc in checks:
        if not ok:
            raise ValueError('Unsupported KSUD source state: '+desc)
    start = src.index(OLD)
    after = src.index(AFTER)
    if after <= start:
        raise ValueError('SukiSU function is after read hook')
    segment = src[start:after]
    for sentinel in (
        'ksu_feature_apply_forced();',
        'ksu_module_blacklist_apply();',
        'ksu_selinux_hide_handle_second_stage();',
        'on_post_fs_data();',
        'ksu_stop_ksud_execve_hook();',
        'static bool first_zygote = true;',
        'static bool init_second_stage_executed = false;',
    ):
        if segment.count(sentinel) != 1:
            raise ValueError('Original SukiSU hook differs: '+sentinel)
    if segment.count('{') != segment.count('}'):
        raise ValueError('Original callback braces do not balance')
    if not segment.rstrip().endswith('}'):
        raise ValueError('Unexpected original callback end')
    out = src[:start] + IMPLEMENTATION + src[after:]
    if OLD in out or 'ksu_stop_ksud_execve_hook();' in out:
        raise ValueError('Old callback references remain after adaptation')
    assert out.count(NEW) == 1
    return out


def selftest() -> None:
    oldbody = '''void ksu_handle_execveat_ksud(const char *path, struct user_arg_ptr *argv)
{
    static bool first_zygote = true;
    static bool init_second_stage_executed = false;
    if (first_zygote) {
        ksu_selinux_hide_handle_second_stage();
        ksu_feature_apply_forced();
        ksu_module_blacklist_apply();
        on_post_fs_data();
        ksu_stop_ksud_execve_hook();
    }
}

'''
    fixture = ('DEFINE_STATIC_KEY_TRUE(is_init_second_stage_not_executed);\n'
               'DEFINE_STATIC_KEY_TRUE(is_first_zygote);\n' +
               oldbody + AFTER + '\n')
    result=transform(fixture)
    assert result.count(TAG)==1
    assert OLD not in result
    assert 'ksu_stop_ksud_execve_hook();' not in result
    for need in ['ksu_feature_apply_forced();','ksu_module_blacklist_apply();',
                 'ksu_selinux_hide_handle_second_stage();','on_post_fs_data();',
                 'static_branch_disable(&is_first_zygote);',
                 'static_branch_disable(&is_init_second_stage_not_executed);']:
        assert need in result
    assert transform(result)==result
    for broken in [
        fixture.replace('ksu_module_blacklist_apply();', ''),
        fixture.replace('DEFINE_STATIC_KEY_TRUE(is_first_zygote);',''),
        fixture.replace('ksu_stop_ksud_execve_hook();',''),
        fixture.replace(AFTER,''),
        fixture.replace('static bool first_zygote = true;', 'static bool first_zygote = false;'),
        fixture + 'ksu_handle_execveat_ksud(path, &argv);\n',
    ]:
        try:
            transform(broken)
        except ValueError:
            continue
        raise AssertionError('Bad source variant was not rejected')
    print('PASS: pinned SukiSU native hook, bridge, original lifecycle and negative variants')


def main() -> None:
    parser=argparse.ArgumentParser()
    parser.add_argument('--selftest',action='store_true')
    parser.add_argument('--apply',type=Path)
    a=parser.parse_args()
    if a.selftest:
        selftest()
    if a.apply:
        p=a.apply
        raw=p.read_text()
        result=transform(raw)
        if result!=raw:
            p.write_text(result)
        print('Ace6 SukiSU native KSUD ABI bridge validated and installed: '+str(p))
    if not (a.selftest or a.apply):
        parser.error('Use --selftest or --apply')
if __name__=='__main__':
    main()
