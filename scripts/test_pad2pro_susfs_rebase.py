import re, tempfile, unittest
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

if __name__=='__main__': unittest.main(verbosity=2)
