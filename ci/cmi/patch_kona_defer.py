#!/usr/bin/env python3
"""Strict 1-instruction patch of user-validated CMI RC3 AArch64 Image.

Only changes the Kona ASoC probe error conversion (-EPROBE_DEFER -> -EINVAL)
when codec_reg_done is set.  This only preserves driver retry semantics; it
cannot guarantee that an incompatible vendor driver will become operational.

Input: byte-exact RC3 Image.  Output: RC4 Image.  Never accesses device nodes.
"""
from pathlib import Path
import argparse
import hashlib
import json
import sys

RC3_SHA256 = '7805151f6dade48f4ac9bc2a478f38e0e04a3c7ee05046f4471c97dc5ebdfe32'
IMAGE_LEN = 47190032
PATCH_OFF = 0x14f7978
# csel w23, w9, w8, ne, after w9=-22, w8=-517 and test(codec_reg_done)
OLD = bytes.fromhex('3711881a')
# mov w23, w8: leave -EPROBE_DEFER unchanged rather than converting to -EINVAL
NEW = bytes.fromhex('f703082a')
# Four surrounding instructions MUST be exactly as analyzed in RC3.
GUARD_START = 0x14f7954
GUARD_OLD = bytes.fromhex('40020034 f703002a 1f140831 010d0054 c8ec00b0 a9028012 08417539 1f010071 88408012 3711881a 96ffff17'.replace(' ',''))


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def patch(raw):
    if len(raw) != IMAGE_LEN or digest(raw) != RC3_SHA256:
        raise ValueError('Refusing unknown Image: RC3 size or full SHA-256 mismatch')
    if raw[56:60] != b'ARM\x64':
        raise ValueError('Not an AArch64 Linux Image')
    assert PATCH_OFF == GUARD_START + 9 * 4
    if raw[GUARD_START:GUARD_START + len(GUARD_OLD)] != GUARD_OLD:
        raise ValueError('Unexpected Kona probe control-flow instructions')
    if raw[PATCH_OFF:PATCH_OFF+4] != OLD:
        raise ValueError('Expected conditional select is missing')
    output=bytearray(raw)
    output[PATCH_OFF:PATCH_OFF+4]=NEW
    changed=[i for i,(a,b) in enumerate(zip(raw,output)) if a!=b]
    if changed != list(range(PATCH_OFF, PATCH_OFF+4)):
        raise AssertionError('Changes outside the 4-byte instruction')
    if output[:PATCH_OFF] != raw[:PATCH_OFF] or output[PATCH_OFF+4:] != raw[PATCH_OFF+4:]:
        raise AssertionError('Unrelated original kernel bytes changed')
    return bytes(output)


def main():
    cli=argparse.ArgumentParser()
    cli.add_argument('rc3_image',type=Path)
    cli.add_argument('rc4_image',type=Path)
    cli.add_argument('--evidence',type=Path)
    a=cli.parse_args()
    if a.rc4_image.exists():
        cli.error('Refusing to overwrite existing output')
    data=a.rc3_image.read_bytes()
    new=patch(data)
    a.rc4_image.write_bytes(new)
    if a.rc4_image.read_bytes()!=new:
        raise RuntimeError('Write/read-back mismatch')
    if a.evidence:
        report={
          'name':'CMI Kona audio probe deferred error compatibility patch',
          'target':'Xiaomi cmi MIUI V12.5.10.0.RJACNXM Android 11, only known RC3 Image',
          'input_rc3_image_sha256':digest(data),
          'output_rc4_image_sha256':digest(new),
          'source_reference':'https://github.com/MiCode/vendor_qcom_opensource_audio-kernel/blob/cmi-r-oss/asoc/kona.c',
          'experimental_build':'https://github.com/Andyxyc/xm-ws/actions/runs/41581837302',
          'original_instruction': 'csel w23, w9, w8, ne',
          'patched_instruction': 'mov w23, w8',
          'patch_offset_hex':hex(PATCH_OFF),
          'before_bytes_hex':OLD.hex(), 'after_bytes_hex':NEW.hex(),
          'modified_byte_count':len([1 for x,y in zip(data,new) if x!=y]),
          'preserved':'RC3 OIS (22-byte changes), exact existing ReSukiSU/SUSFS/other Image bytes, no DTB/DTBO/vendor modifications',
          'logic':'Only on existing -EPROBE_DEFER path, return -EPROBE_DEFER rather than changing it to -EINVAL after codec_reg_done; other errors unchanged',
          'target_device_boot_test':'not_run', 'audio_recovery':'unverified', 'camera_regression':'unverified',
          'limits':['Does not repair module symbol CRC mismatch', 'Does not establish that the real Kona probe failed at this branch', 'Experimental, not assured to fix sound']
        }
        a.evidence.parent.mkdir(parents=True,exist_ok=True)
        a.evidence.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(f'RC3={digest(data)} RC4={digest(new)} changed=4 offset={hex(PATCH_OFF)}')

if __name__=='__main__':
    main()