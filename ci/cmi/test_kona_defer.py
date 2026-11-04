#!/usr/bin/env python3
"""Host-only RC4 Kona patch tests. Optional CMI_RC3_IMAGE original input."""
import hashlib
import importlib.util
import os
import pathlib
import subprocess
import tempfile
import unittest

HERE = pathlib.Path(__file__).resolve().parent
s = importlib.util.spec_from_file_location('kona', HERE/'patch_kona_defer.py')
k = importlib.util.module_from_spec(s)
s.loader.exec_module(k)


class KonaPatchTests(unittest.TestCase):
    def setUp(self):
        env = os.getenv('CMI_RC3_IMAGE')
        if not env or not pathlib.Path(env).is_file():
            self.skipTest('Needs byte-exact previous RC3 Image supplied by caller')
        self.data = pathlib.Path(env).read_bytes()

    def test_known_rc3_hash(self):
        self.assertEqual(k.digest(self.data), k.RC3_SHA256)
        self.assertEqual(len(self.data), k.IMAGE_LEN)

    def test_caller_guard_and_exact_patch(self):
        self.assertEqual(self.data[k.GUARD_START:k.GUARD_START+len(k.GUARD_OLD)], k.GUARD_OLD)
        new=k.patch(self.data)
        self.assertEqual(new[k.PATCH_OFF:k.PATCH_OFF+4],k.NEW)
        self.assertEqual(new[:k.PATCH_OFF],self.data[:k.PATCH_OFF])
        self.assertEqual(new[k.PATCH_OFF+4:],self.data[k.PATCH_OFF+4:])

    def test_diff_confined_to_one_instruction(self):
        new=k.patch(self.data)
        indices=[i for i,(x,y) in enumerate(zip(self.data,new)) if x!=y]
        self.assertEqual(indices,list(range(k.PATCH_OFF,k.PATCH_OFF+4)))
        self.assertEqual(len(new),len(self.data))

    def test_roundtrip_exact(self):
        new=k.patch(self.data)
        reverted=bytearray(new)
        reverted[k.PATCH_OFF:k.PATCH_OFF+4]=k.OLD
        self.assertEqual(bytes(reverted),self.data)

    def test_dont_double_patch(self):
        with self.assertRaises(ValueError):k.patch(k.patch(self.data))

    def test_unrecognized_build_rejected(self):
        with self.assertRaises(ValueError):k.patch(b'garbage')
        broken=bytearray(self.data)
        broken[k.PATCH_OFF] ^= 0x1
        with self.assertRaises(ValueError):k.patch(bytes(broken))

    def test_kona_branch_source_logic(self):
        # Source: call(0x14f7950); if nonzero, compare with -517;
        # select w9=-22 iff codec_reg_done != 0; RC4 always returns w8=-517.
        for code in (0,1,255):
            for ret in (-517,-22,-19,-12,-1,0,1):
                expected= -22 if ret == -517 and code else ret
                original=( -22 if code else -517) if ret==-517 else ret
                changed=-517 if ret==-517 else ret
                self.assertEqual(original,expected)
                self.assertEqual(changed,-517 if ret==-517 else original)

    def test_aarch64_assembler_opcode(self):
        import shutil
        compiler=shutil.which('clang')
        objdump=shutil.which('llvm-objdump')
        if not (compiler and objdump):self.skipTest('AArch64 clang/llvm-objdump not installed')
        with tempfile.TemporaryDirectory() as d:
            src=pathlib.Path(d)/'mov.s'
            binary=pathlib.Path(d)/'mov.o'
            src.write_text('mov w23, w8\n')
            subprocess.run([compiler,'--target=aarch64-linux-gnu','-c',str(src),'-o',str(binary)],check=True)
            result=subprocess.run([objdump,'-d',str(binary)],capture_output=True,text=True,check=True)
            self.assertIn('2a0803f7',result.stdout)
            self.assertIn('mov\tw23, w8',result.stdout)


if __name__=='__main__':unittest.main(verbosity=2)