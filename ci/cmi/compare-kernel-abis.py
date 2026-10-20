#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Fail-closed A/B kernel ABI regression; cannot prove stock vendor module support."""
import hashlib
import json
from pathlib import Path
import re
import sys


def symvers(path):
    result = {}
    for n, line in enumerate(path.read_text().splitlines(), 1):
        fields = line.split()
        if len(fields) < 4 or not re.fullmatch(r'0x[0-9a-fA-F]{8}', fields[0]):
            raise ValueError(f'Bad Module.symvers row {path}:{n}')
        key = fields[1]
        if key in result:
            raise ValueError(f'Duplicate exported symbol {key}')
        result[key] = {'crc': fields[0], 'module': fields[2], 'export': fields[3]}
    if len(result) < 10000:
        raise ValueError('Unexpectedly small Module.symvers')
    return result


def check_image(p):
    with p.open('rb') as f:
        f.seek(56)
        if f.read(4) != b'ARM\x64':
            raise ValueError('Invalid native AArch64 image header: ' + str(p))
    h = hashlib.sha256()
    with p.open('rb') as f:
        for chunk in iter(lambda:f.read(1 << 20), b''):
            h.update(chunk)
    return {'bytes': p.stat().st_size, 'sha256': h.hexdigest()}


def check_config(p, expect_susfs):
    lines = set(p.read_text().splitlines())
    mandatory = {'CONFIG_KSU=y', 'CONFIG_MODVERSIONS=y', 'CONFIG_QCA_CLD_WLAN=y'}
    for flag in mandatory:
        if flag not in lines: raise ValueError('Missing required config: '+flag)
    if ('CONFIG_KSU_SUSFS=y' in lines) != expect_susfs:
        raise ValueError('SUSFS variant mismatch')
    if any(x in lines for x in ('CONFIG_KPM=y','CONFIG_KPM=m', 'CONFIG_KSU_DEBUG=y')):
        raise ValueError('Unexpected debug or KPM flag')
    return {'SUSFS': expect_susfs, 'KPM': False, 'MODVERSIONS': True}


def main(a,b,output):
    out = Path(output)
    out.mkdir(parents=True,exist_ok=True)
    dirs = [Path(a),Path(b)]
    data = []
    for p,sus in zip(dirs,(False,True)):
        abi = symvers(p/'Module.symvers')
        cfg = check_config(p/'kernel.config',sus)
        img = check_image(p/'Image')
        data.append((abi,cfg,img))
    a_syms,b_syms = data[0][0], data[1][0]
    missing = sorted(set(a_syms) - set(b_syms))
    extra = sorted(set(b_syms) - set(a_syms))
    altered = sorted(name for name in set(a_syms)&set(b_syms) if a_syms[name] != b_syms[name])
    result = {
        'device':'cmi','rom':'V12.5.10.0.RJACNXM',
        'A_build':39313741454,'B_build':39323904314,
        'A':{'exported_symbols':len(a_syms),'kernel_image':data[0][2], 'config':data[0][1]},
        'B':{'exported_symbols':len(b_syms),'kernel_image':data[1][2], 'config':data[1][1]},
        'export_added_in_B':extra[:50], 'export_missing_in_B':missing[:50],
        'export_changed_in_B':altered[:50],
        'A_B_export_table_identical':not (missing or extra or altered),
        'stock_vendor_module_crc_compatible':'unknown_without_original_vendor_modules',
        'stock_boot_dtbo_compatible':'unknown','phone_boot_tested':False,
        'can_make_flashable_AK3':False
    }
    (out/'cmi-abi-compare.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    if missing or extra or altered:
        raise RuntimeError(f'Export ABI differs: missing {len(missing)}, extra {len(extra)}, changed {len(altered)}')
    print('A/B Module.symvers exports identical. Stock vendor compatibility still unknown.')


if __name__=='__main__':
    if len(sys.argv)!=4:raise SystemExit('usage: cmi-abi-compare.py A_DIRECTORY B_DIRECTORY OUT_DIRECTORY')
    main(*sys.argv[1:])
