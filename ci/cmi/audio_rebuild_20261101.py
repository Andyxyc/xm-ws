#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Rebuild cmi stock audio baseline using fresh pinned public sources.

This is a compiler and ABI experiment. It does NOT build an RC3 replacement,
carry over ReSukiSU/SUSFS, package AnyKernel3, or write a phone partition.
"""
import difflib
import hashlib
import json
import re
import sys
from pathlib import Path

BRANCH = 'cmi-audio-abi-rebuild-20261101'
ORIGINAL_BRANCH = 'cmi-miui12510-driver-build-20261019'
KONA_BLOB = '89c9d588a4cc6818f5417d5b79cbc794f039e48b'
KONA_BEFORE = '''\tret = devm_snd_soc_register_card(&pdev->dev, card);
\tif (ret == -EPROBE_DEFER) {
\t\tif (codec_reg_done)
\t\t\tret = -EINVAL;
\t\tgoto err;
\t} else if (ret) {
'''
KONA_AFTER = '''\tret = devm_snd_soc_register_card(&pdev->dev, card);
\tif (ret == -EPROBE_DEFER) {
\t\t/* Allow deferred probing while component dependencies register. */
\t\tgoto err;
\t} else if (ret) {
'''


def exactly_one(text, anchor):
    if text.count(anchor) != 1:
        raise RuntimeError('Source revision mismatch or repeated patch: ' + anchor[:70])


def blob_sha(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode('ascii') + b'\0' + data).hexdigest()


def generated_scripts(root):
    deps = (root / 'ci/cmi/fetch-public-deps.sh').read_text()
    old_guard = f'[ "${{GITHUB_REF:?}}" = "refs/heads/{ORIGINAL_BRANCH}" ] || exit 2'
    exactly_one(deps, old_guard)
    deps = deps.replace(old_guard, f'[ "${{GITHUB_REF:?}}" = "refs/heads/{BRANCH}" ] || exit 2')

    original = (root / 'build-cmi-drivers.sh').read_text()
    exactly_one(original, 'https://api.github.com/repos/Andyxyc/xm-ws/actions/artifacts/12186620532/zip')
    start_token = 'curl --fail --location --retry 2 --connect-timeout 30 --max-time 600 '
    end_token = 'fetch_source() {\n'
    exactly_one(original, start_token)
    exactly_one(original, end_token)
    start = original.index(start_token)
    end = original.index(end_token)
    if end <= start:
        raise RuntimeError('Unexpected dependency step order')
    fresh = '''# Consume freshly verified dependencies from the previous CI step.
cp "$ROOT/public-deps/"*.tar.gz "$WORK/deps/"
cp "$ROOT/public-deps/SOURCES.txt" "$WORK/deps/SOURCES.txt"
cp "$ROOT/public-deps/SHA256SUMS" "$WORK/deps/SHA256SUMS"
(cd "$WORK/deps"; sha256sum -c SHA256SUMS)
'''
    output = original[:start] + fresh + original[end:]
    anchor = 'export ARCH=arm64 TARGET_PRODUCT=cmi TARGET_BUILD_VARIANT=user\n'
    exactly_one(output, anchor)
    inject = '''# Keep the previous pinned WLAN and kernel link repairs; no ABI checks disabled.
python3 "$ROOT/repair-cmi-wlan.py" "$WORK/kernel" "$ROOT/driver-results"
python3 "$ROOT/repair-cmi-sysfs.py" "$WORK/kernel" "$ROOT/driver-results"
python3 "$ROOT/repair-cmi-link.py" apply "$WORK/kernel" "$ROOT/driver-results"
python3 "$ROOT/ci/cmi/audio_rebuild_20261101.py" patch-kona "$WORK/kernel" "$ROOT/driver-results"
'''
    output = output.replace(anchor, inject + anchor, 1)
    # Build an independent non-flashable compiler baseline only.
    exactly_one(output, 'driver baseline. Not flashable.')
    output = output.replace('driver baseline. Not flashable.', 'audio compatibility experiment. NOT FLASHABLE.', 1)
    if '12186620532/zip' in output or 'sha256sum -c -' in output:
        raise RuntimeError('Expired dependency artifact still referenced')
    if 'CONFIG_MODVERSIONS=y' not in output:
        raise RuntimeError('Kernel module version verification was removed')
    return deps, output


def transform_kona(raw, require_blob=True):
    if require_blob and blob_sha(raw) != KONA_BLOB:
        raise RuntimeError('Official cmi Kona file revision differs')
    src = raw.decode('utf-8')
    exactly_one(src, KONA_BEFORE)
    if KONA_AFTER in src:
        raise RuntimeError('Kona defer patch already present')
    dst = src.replace(KONA_BEFORE, KONA_AFTER, 1)
    if dst.replace(KONA_AFTER, KONA_BEFORE, 1) != src:
        raise RuntimeError('Kona patch not reversible')
    return dst.encode('utf-8')


def patch_kona(kernel, results):
    kernel = kernel.resolve(strict=True)
    target = kernel / 'techpack/audio/asoc/kona.c'
    if not target.resolve(strict=True).is_relative_to(kernel):
        raise RuntimeError('Kona path outside checked out kernel')
    before = target.read_bytes()
    after = transform_kona(before)
    results.mkdir(parents=True, exist_ok=True)
    patch = ''.join(difflib.unified_diff(
        before.decode().splitlines(keepends=True),
        after.decode().splitlines(keepends=True),
        fromfile='a/techpack/audio/asoc/kona.c',
        tofile='b/techpack/audio/asoc/kona.c'))
    if 'EPROBE_DEFER' not in patch or 'codec_reg_done' not in patch:
        raise RuntimeError('Unexpected diff content')
    (results / 'cmi-kona-probe-defer-experiment.patch').write_text(patch)
    target.write_bytes(after)
    if target.read_bytes() != after:
        raise RuntimeError('Kona source write did not persist')
    (results / 'cmi-audio-patch-check.json').write_text(json.dumps({
        'source': 'MiCode/vendor_qcom_opensource_audio-kernel@b85ef7488ff5a99105a67714d4406f690c62c34e',
        'kona_blob_sha1': KONA_BLOB,
        'before_sha256': hashlib.sha256(before).hexdigest(),
        'after_sha256': hashlib.sha256(after).hexdigest(),
        'change': 'Keep -EPROBE_DEFER instead of converting it to -EINVAL after codec_reg_done',
        'condition_observed_on_phone': False,
        'proof_of_audio_fix': False,
        'stock_module_CRC_compatible': 'unverified',
        'preserves_existing_RC3': 'This experimental source is not an RC3 replacement',
    }, indent=2) + '\n')


def verify(root):
    out = root / 'driver-results'
    required = ['Image', 'Image.gz', 'Module.symvers', 'System.map', 'kernel.config']
    for name in required:
        if not (out / name).is_file() or (out / name).stat().st_size == 0:
            raise RuntimeError('Missing compiled result: ' + name)
    if 'CONFIG_MODVERSIONS=y' not in (out / 'kernel.config').read_text().splitlines():
        raise RuntimeError('CONFIG_MODVERSIONS missing')
    map_text = (out / 'System.map').read_text()
    if ' snd_soc_register_card' not in map_text:
        raise RuntimeError('ALSA SoC card registration is not linked')
    versions = (out / 'Module.symvers').read_text().splitlines()
    if len(versions) < 10000:
        raise RuntimeError('Too few exported symbol versions')
    sound_symbols = [l for l in map_text.splitlines() if re.search(r'\b(msm_asoc_machine_probe|kona_asoc_machine_driver)\b', l)]
    if not sound_symbols:
        raise RuntimeError('No Kona sound machine symbols linked')
    report = {
        'device': 'cmi', 'rom': 'V12.5.10.0.RJACNXM',
        'compiler_build': 'compiled MiCode 4.19.113 experimental audio-enabled baseline',
        'linked_kona_symbols': sound_symbols[:10],
        'exported_symbol_rows': len(versions),
        'image_sha256': hashlib.sha256((out/'Image').read_bytes()).hexdigest(),
        'vermagic_runtime_compatibility': 'not established',
        'stock_vendor_module_CRC_compatibility': 'not established',
        'RC3_ReSukiSU_SUSFS_and_camera_preserved': False,
        'flashable': False, 'phone_tested': False,
    }
    (out / 'audio-link-report.json').write_text(json.dumps(report, indent=2) + '\n')
    (out / 'NOT_FLASHABLE.txt').write_text('Experimental 4.19.113 audio kernel baseline. Not RC3. DO NOT FLASH.\n')


def main():
    if len(sys.argv) < 2:
        raise SystemExit('usage: prepare ROOT | patch-kona KERNEL RESULTS | verify ROOT')
    op = sys.argv[1]
    if op == 'prepare' and len(sys.argv) == 3:
        root = Path(sys.argv[2]).resolve(strict=True)
        deps, build = generated_scripts(root)
        (root / 'build-cmi-public-deps-audio.generated.sh').write_text(deps)
        (root / 'build-cmi-audio.generated.sh').write_text(build)
    elif op == 'patch-kona' and len(sys.argv) == 4:
        patch_kona(Path(sys.argv[2]), Path(sys.argv[3]))
    elif op == 'verify' and len(sys.argv) == 3:
        verify(Path(sys.argv[2]))
    else:
        raise SystemExit('invalid arguments')


if __name__ == '__main__':
    main()