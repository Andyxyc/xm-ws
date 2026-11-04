#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Host tests of source transformations; not a phone test."""
import importlib.util
import subprocess
import tempfile
import unittest
from pathlib import Path
spec=importlib.util.spec_from_file_location('stock',Path(__file__).with_name('stock_resukisu.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class Tests(unittest.TestCase):
    def test_exec_single_pre_hook_original_call_preserved(self):
        out=m.hook_source('fs/exec.c',m.EXEC.encode(),strict=False).decode()
        self.assertEqual(out.count('ksu_handle_execveat(&fd'),1)
        self.assertIn('return __do_execve_file(fd, filename, argv, envp, flags, NULL);',out)
        self.assertNotIn('ksu_handle_post_execveat',out)
    def test_access_preserves_return(self):
        out=m.hook_source('fs/open.c',m.ACCESS.encode(),strict=False).decode()
        self.assertEqual(out.count('ksu_handle_faccessat(&dfd'),1)
        self.assertIn('return do_faccessat(dfd, filename, mode);',out)
    def test_stat_all_four_syscalls(self):
        s='SYSCALL_DEFINE2(newstat, int, unused)\n{\n}\n'
        for name in ['newfstatat','fstatat64']:
            s+='SYSCALL_DEFINE4('+name+', int, dfd)\n{\n\tint error;\n\terror = vfs_fstatat(dfd, filename, &stat, flag);\n\treturn error;\n}\n'
        for name in ['newfstat','fstat64']:
            s+='SYSCALL_DEFINE2('+name+', int, fd)\n{\n\tint error = 0;\n\treturn error;\n}\n'
        out=m.hook_source('fs/stat.c',s.encode(),strict=False).decode()
        self.assertEqual(out.count('ksu_handle_stat(&dfd'),2)
        self.assertEqual(out.count('ksu_handle_newfstat_ret(&fd'),1)
        self.assertEqual(out.count('ksu_handle_fstat64_ret(&fd'),1)
        self.assertEqual(out.count('return error;'),4)
    def test_reboot_keeps_permission_branch(self):
        s='SYSCALL_DEFINE4(reboot, int, magic1, int, magic2, unsigned int, cmd,\n void __user *, arg)\n{\n\tint ret = 0;\n\tif (check_poweroff_charger_mode()){\n\t} else {\n\t\tif (!ns_capable(pid_ns->user_ns, CAP_SYS_BOOT))\n\t\t\treturn -EPERM;\n\t}\n}\n'
        out=m.hook_source('kernel/reboot.c',s.encode(),strict=False).decode()
        self.assertIn('ksu_handle_sys_reboot(magic1, magic2, cmd, &arg);',out)
        self.assertIn('if (!ns_capable(pid_ns->user_ns, CAP_SYS_BOOT))',out)
    def test_wrong_revision_rejected(self):
        for name in m.BLOBS:
            with self.subTest(name=name),self.assertRaises(ValueError):m.hook_source(name,b'not the pinned source')
    def test_repeated_hook_rejected(self):
        once=m.hook_source('fs/exec.c',m.EXEC.encode(),strict=False)
        with self.assertRaises(ValueError):m.hook_source('fs/exec.c',once,strict=False)
    def test_duplicate_anchor_rejected(self):
        with self.assertRaises(ValueError):m.hook_source('fs/open.c',(m.ACCESS*2).encode(),strict=False)
    def test_unknown_target_rejected(self):
        with self.assertRaises(ValueError):m.hook_source('sound/unreviewed.c',b'',strict=False)
    def test_exec_compiles_with_hook_on_and_off(self):
        transformed=m.hook_source('fs/exec.c',m.EXEC.encode(),strict=False).decode()
        prefix='''#include <stddef.h>
struct filename { int x; }; struct user_arg_ptr { int x; };
static int calls;
static int __do_execve_file(int fd, struct filename *f, struct user_arg_ptr a, struct user_arg_ptr e, int flags, void *file)
{ (void)f; (void)a; (void)e; (void)flags; (void)file; return fd; }
'''
        suffix='''
int ksu_handle_execveat(int *fd, struct filename **f, void *a, void *e, int *flags)
{ (void)f; (void)a; (void)e; (void)flags; ++calls; *fd=7; return 0; }
int main(void) { struct filename f={0}; struct user_arg_ptr a={0};
int r=do_execveat_common(5,&f,a,a,0);
#ifdef CONFIG_KSU_MANUAL_HOOK
return !(r==7 && calls==1);
#else
return !(r==5 && calls==0);
#endif
}
'''
        with tempfile.TemporaryDirectory(prefix='cmi 空格 ') as d:
            p=Path(d);(p/'test.c').write_text(prefix+transformed+suffix)
            for enabled in [False,True]:
                argv=['cc','-std=gnu89','-Wall','-Wextra','-Werror']
                if enabled:argv+=['-DCONFIG_KSU_MANUAL_HOOK=1']
                subprocess.run(argv+[str(p/'test.c'),'-o',str(p/'test')],check=True,capture_output=True)
                subprocess.run([str(p/'test')],check=True)

    def test_prepare_real_successful_entry_syntax_and_no_kona_patch(self):
        root=Path(__file__).parent
        deps=(root/'build-cmi-public-deps-audio.generated.sh')
        build=(root/'build-cmi-audio.generated.sh')
        if not deps.exists() or not build.exists():
            self.skipTest('Previous successful build entry not provided')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'ci/cmi').mkdir(parents=True)
            stub='BRANCH="cmi-audio-abi-rebuild-20261101"\n'+'def generated_scripts(root):\n    return '+repr((deps.read_text(),build.read_text()))+'\n'
            (p/'ci/cmi/audio_rebuild_20261101.py').write_text(stub)
            m.prepare(p)
            a=(p/'build-cmi-stock-root.sh').read_text()
            self.assertNotIn('patch-kona',a)
            self.assertNotIn('without SukiSU',a)
            self.assertIn('-e KSU_MANUAL_HOOK',a)
            self.assertIn('-d KSU_SUSFS',a)
            self.assertIn('stock_resukisu.py" integrate',a)
            self.assertIn('"${MAKE[@]}" modules',a)
            subprocess.run(['bash','-n',str(p/'build-cmi-stock-root.sh')],check=True)
            subprocess.run(['bash','-n',str(p/'build-cmi-stock-deps.sh')],check=True)

if __name__=='__main__':unittest.main(verbosity=2)
