import re, shutil, subprocess, tempfile, unittest
from pathlib import Path
import pad2pro_susfs_rebase as r

class RebaseTests(unittest.TestCase):
    def fixture(self):
        heads = r.HEADER + '--- a/fs/proc/task_mmu.c\n+++ b/fs/proc/task_mmu.c\n'
        self.pre = 'diff --git a/untouched.c b/untouched.c\n--- a/untouched.c\n+++ b/untouched.c\n@@ -1,1 +1,1 @@\n-a\n+b\n'
        self.post = 'diff --git a/another.c b/another.c\n--- a/another.c\n+++ b/another.c\n@@ -1,1 +1,1 @@\n-c\n+d\n'
        bodies = {
            23: '+#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT\n+#endif\n',
            260: '+#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT\n+srcu_read_unlock();\n+#endif\n',
            275: r.FOLD_OLD,
            892: ' \tstruct vm_area_struct *vma = v;\n \tstruct mem_size_stats mss;\n \n+#ifdef CONFIG_KSU_SUSFS_SUS_MAP\n+\tif (vma->vm_file && SUSFS_IS_INODE_SUS_MAP(file_inode(vma->vm_file)))\n+\t\treturn 0;\n+#endif\n \tmemset(&mss, 0, sizeof(mss));\n',
            955: '+#ifdef CONFIG_KSU_SUSFS_SUS_MAP\n+walk_page_range();\n+#endif\n',
            999: '-\t\t\tif (vma->vm_end > last_vma_end)\n+\t\t\tif (vma->vm_end > last_vma_end) {\n+\t\t\t}\n',
            1021: r.CURSOR_OLD,
            1800: ' \twhile (count) {\n+\tstruct vm_area_struct *vma;\n \t}\n',
            1809: ' \tret = walk_page_range();\n+\treturn ret;\n',
        }
        return self.pre + heads + ''.join(f'@@ -{p},1 +{p},1 @@ function\n{bodies[p]}' for p in r.POSITIONS) + self.post
    def test_features_and_unrelated_files(self):
        result = r.rebase_text(self.fixture())
        self.assertTrue(result.startswith(self.pre))
        self.assertTrue(result.endswith(self.post))
        for text in ('CONFIG_KSU_SUSFS_SUS_MAP','CONFIG_KSU_SUSFS_SUS_KSTAT','CONFIG_KSU_SUSFS_OPEN_REDIRECT','get_data_vma(v)','srcu_read_unlock','__fold_filemap_fixup_entry'):
            self.assertIn(text,result)
        self.assertNotIn('+else\n',result)
        self.assertNotIn('VMA_PAD_START',result)
        self.assertNotIn('@@ -999,',result)
    def test_headers_recount(self):
        result=r.rebase_text(self.fixture())
        sec=result[result.index(r.HEADER):result.index(self.post)]
        matches=list(r.HUNK.finditer(sec))
        self.assertEqual(len(matches),8)
        for i,m in enumerate(matches):
            body=sec[m.end():matches[i+1].start() if i+1<len(matches) else len(sec)]
            ls=body.splitlines()
            self.assertEqual(int(m[2]),sum(x[0] in ' -' for x in ls))
            self.assertEqual(int(m[4]),sum(x[0] in ' +' for x in ls))
    def test_cursor_outside_filter(self):
        result=r.rebase_text(self.fixture())
        self.assertIn('+#endif // #ifdef CONFIG_KSU_SUSFS_SUS_MAP\n \t\t\t\tlast_vma_end = vma->vm_end;\n',result)
    def test_reapplication_refused(self):
        updated=r.rebase_text(self.fixture())
        with self.assertRaises(ValueError): r.rebase_text(updated)
    def test_modified_anchor_refused(self):
        fixture=self.fixture().replace('struct vm_area_struct *vma = v;', 'struct vm_area_struct *vma = NULL;')
        with self.assertRaises(ValueError): r.rebase_text(fixture)
    def test_duplicate_section_refused(self):
        fixture=self.fixture()
        with self.assertRaises(ValueError): r.rebase_text(fixture+fixture)
    def test_wrong_fingerprints_no_output(self):
        with tempfile.TemporaryDirectory(prefix='平板 & 空格 ! ') as d:
            d=Path(d); patch=d/'a.patch'; source=d/'b.c'; output=d/'out.patch'
            patch.write_text(self.fixture()); source.write_text('not exact source')
            with self.assertRaises(ValueError): r.rebase(patch,source,output)
            self.assertFalse(output.exists())
    def test_git_blob(self):
        self.assertEqual(r.git_blob(b''),'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391')


    def test_macro_negation_groups_entire_expansion(self):
        result=r.rebase_text(self.fixture())
        self.assertIn('!(SUSFS_IS_INODE_SUS_MAP(file_inode(vma->vm_file)))', result)
        self.assertNotIn('!SUSFS_IS_INODE_SUS_MAP(', result)
    def test_generated_predicate_compiles_and_all_null_flag_cases(self):
        compiler=shutil.which('clang') or shutil.which('cc')
        self.assertIsNotNone(compiler, 'A host C compiler is required; do not skip this regression')
        # Use the generated expression and the pinned upstream macro body.
        # This checks expansion semantics, not just Python or shell syntax.
        condition=next(line[1:].strip() for line in r.CURSOR_NEW.splitlines()
                       if 'if (!vma->vm_file ||' in line)
        source=r'''#include <stdbool.h>
#include <stddef.h>
struct address_space { unsigned long flags; };
struct inode { struct address_space *i_mapping; };
struct file { struct inode *node; };
struct vm_area_struct { struct file *vm_file; };
static bool app;
static bool test_bit(unsigned int bit, const unsigned long *flags) { return !!(*flags & (1UL << bit)); }
static bool susfs_is_current_proc_umounted_app(void) { return app; }
#define AS_FLAGS_SUS_MAP 0
#define unlikely(x) (x)
#define file_inode(f) ((f)->node)
#define SUSFS_IS_INODE_SUS_MAP(inode) \
        inode && inode->i_mapping && \
        unlikely(test_bit(AS_FLAGS_SUS_MAP, &inode->i_mapping->flags)) && \
        susfs_is_current_proc_umounted_app()
static bool should_gather(struct vm_area_struct *vma) {
    CONDITION
        return true;
    }
    return false;
}
int main(void) {
    for (unsigned int bits=0; bits<32; ++bits) {
        bool has_file=!!(bits & 1), has_inode=!!(bits & 2);
        bool has_mapping=!!(bits & 4), marked=!!(bits & 8);
        app=!!(bits & 16);
        struct address_space mapping={.flags=marked ? 1UL : 0UL};
        struct inode node={.i_mapping=has_mapping ? &mapping : NULL};
        struct file file={.node=has_inode ? &node : NULL};
        struct vm_area_struct vma={.vm_file=has_file ? &file : NULL};
        bool expected=!(has_file && has_inode && has_mapping && marked && app);
        if (should_gather(&vma) != expected) return (int)bits+1;
    }
    return 0;
}
'''.replace('CONDITION',condition)
        with tempfile.TemporaryDirectory(prefix='平板 C 宏 & 回归 ! ') as d:
            d=Path(d); c=d/'predicate.c'; binary=d/'predicate'
            c.write_text(source)
            flags=['-std=c11','-O2','-Wall','-Wextra','-Werror','-Wparentheses']
            if 'clang' in Path(compiler).name:
                flags.append('-Wlogical-op-parentheses')
            built=subprocess.run([compiler,*flags,str(c),'-o',str(binary)],
                                 capture_output=True,text=True,timeout=30)
            self.assertEqual(built.returncode,0,built.stderr)
            checked=subprocess.run([str(binary)],capture_output=True,text=True,timeout=10)
            self.assertEqual(checked.returncode,0,'Predicate/null case failed: '+str(checked.returncode))

if __name__=='__main__': unittest.main(verbosity=2)
