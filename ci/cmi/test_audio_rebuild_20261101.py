#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Isolated host regression tests; does not download, build or flash a kernel."""
import importlib.util
import hashlib
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('audio_build', Path(__file__).with_name('audio_rebuild_20261101.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class TestAudioRebuild(unittest.TestCase):
    def test_kona_preserve_defer(self):
        orig = ('before\n' + m.KONA_BEFORE + 'after\n').encode()
        new = m.transform_kona(orig, require_blob=False)
        self.assertEqual(new.count(b'EPROBE_DEFER'), 1)
        self.assertIn(b'goto err;', new)
        self.assertNotIn(b'ret = -EINVAL;', new)
        self.assertEqual(new.replace(m.KONA_AFTER.encode(), m.KONA_BEFORE.encode()), orig)

    def test_kona_wrong_revision_rejected(self):
        with self.assertRaises(RuntimeError):
            m.transform_kona(m.KONA_BEFORE.encode())

    def test_kona_duplicate_or_changed_rejected(self):
        with self.assertRaises(RuntimeError):
            m.transform_kona((m.KONA_BEFORE * 2).encode(), require_blob=False)
        with self.assertRaises(RuntimeError):
            m.transform_kona(m.KONA_AFTER.encode(), require_blob=False)

    def test_generated_build_scripts(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p/'ci/cmi').mkdir(parents=True)
            (p/'ci/cmi/fetch-public-deps.sh').write_text('#!/bin/bash\n[ "${GITHUB_REF:?}" = "refs/heads/cmi-miui12510-driver-build-20261019" ] || exit 2\necho dependency\n')
            src = '''#!/usr/bin/env bash
mkdir "$WORK/deps"
curl --fail --location --retry 2 --connect-timeout 30 --max-time 600 \\
  https://api.github.com/repos/Andyxyc/xm-ws/actions/artifacts/12186620532/zip \\
  -o "$WORK/deps.zip"
printf 'expected  file' | sha256sum -c -
unzip -q "$WORK/deps.zip" -d "$WORK/deps"
fetch_source() {
  echo source
}
export ARCH=arm64 TARGET_PRODUCT=cmi TARGET_BUILD_VARIANT=user
CONFIG_MODVERSIONS=y
echo 'driver baseline. Not flashable.'
'''
            (p/'build-cmi-drivers.sh').write_text(src)
            a,b = m.generated_scripts(p)
            self.assertIn(m.BRANCH, a)
            self.assertNotIn('12186620532/zip', b)
            self.assertIn('SHA256SUMS', b)
            self.assertIn('cp -- "$ROOT/public-deps/"* "$WORK/deps/"', b)
            self.assertNotIn('"$ROOT/public-deps/"*.tar.gz "$WORK/deps/"', b)
            self.assertIn('repair-cmi-wlan.py', b)
            self.assertIn('repair-cmi-link.py', b)
            self.assertIn('patch-kona', b)
            self.assertIn('CONFIG_MODVERSIONS=y', b)

    def test_full_dependency_manifest_and_corruption_rejected(self):
        # The previous failure was caused by checking manifest entries that had
        # not been copied alongside the tarballs.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / 'ci/cmi').mkdir(parents=True)
            (root / 'ci/cmi/fetch-public-deps.sh').write_text(
                '#!/bin/bash\n[ "${GITHUB_REF:?}" = "refs/heads/cmi-miui12510-driver-build-20261019" ] || exit 2\n')
            source = '''#!/bin/bash
mkdir "$WORK/deps"
curl --fail --location --retry 2 --connect-timeout 30 --max-time 600 https://api.github.com/repos/Andyxyc/xm-ws/actions/artifacts/12186620532/zip
fetch_source() {
  :
}
export ARCH=arm64 TARGET_PRODUCT=cmi TARGET_BUILD_VARIANT=user
CONFIG_MODVERSIONS=y
echo 'driver baseline. Not flashable.'
'''
            (root / 'build-cmi-drivers.sh').write_text(source)
            _, build = m.generated_scripts(root)
            block = build.split('# Copy the *whole* verified output,')[1].split('fetch_source() {')[0]
            script = '#!/bin/sh\nset -eu\n# Copy the *whole* verified output,' + block
            out = root / 'public-deps'
            out.mkdir()
            expected = {
                'clang-r377782c.tar.gz': b'clang',
                'gcc64.tar.gz': b'gcc',
                'wlan.tar.gz': b'wlan',
                'README.txt': b'known provenance',
                'probe-linked.o': b'arm64 probe',
                'SOURCES.txt': b'git pin list',
            }
            for name, data in expected.items():
                (out / name).write_bytes(data)
            (out / 'SHA256SUMS').write_text(''.join(
                f'{hashlib.sha256(data).hexdigest()}  ./{name}\n'
                for name, data in sorted(expected.items())))
            env = dict(os.environ, ROOT=str(root), WORK=str(root / 'work'))
            (root / 'work/deps').mkdir(parents=True)
            valid = subprocess.run(['sh', '-c', script], env=env,
                                   capture_output=True, text=True)
            self.assertEqual(valid.returncode, 0, valid.stdout + '\n' + valid.stderr)
            self.assertIn('./README.txt: OK', valid.stdout)
            for f in (root / 'work/deps').iterdir():
                f.unlink()
            (out / 'probe-linked.o').write_bytes(b'tampered probe')
            invalid = subprocess.run(['sh', '-c', script], env=env,
                                     capture_output=True, text=True)
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn('./probe-linked.o: FAILED', invalid.stdout)

    def test_changed_source_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)
            (p/'ci/cmi').mkdir(parents=True)
            (p/'ci/cmi/fetch-public-deps.sh').write_text('# changed ref')
            (p/'build-cmi-drivers.sh').write_text('# changed build')
            with self.assertRaises(RuntimeError):
                m.generated_scripts(p)

if __name__ == '__main__':
    unittest.main(verbosity=2)