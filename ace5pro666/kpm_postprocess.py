#!/usr/bin/env python3
"""Cloud-only KPM postprocess, pinned official ABI2 pair; never patch in place.

Checks Image entry, payload body, saved original header, hashed random key,
disabled KP su-config and resolved linker symbols. This is not boot acceptance.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import struct
import subprocess
import sys

TOOL_SHA = 'a6b912ca964d35427d7fbcd87273abac604970e9746fa0613362be971f07259d'
PAYLOAD_SHA = '14fc6564fa092afe4a2293268cd061da64a20f61dc91396a404daf13d053f5ca'
PAYLOAD_BYTES = 294384
SOURCE = '1c5b608916357ac86a94cc736e235db1fac4a29d'

def require(ok, message):
    if not ok:
        raise ValueError(message)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def inspect_entry(image):
    require(len(image) >= 128 and image[56:60] == b'ARMd', 'Not a raw ARM64 Image')
    offset = 4 if image[:2] == b'MZ' else 0
    insn = struct.unpack_from('<I', image, offset)[0]
    require(insn & 0xfc000000 == 0x14000000, 'Primary Image entry is not B')
    imm = insn & 0x3ffffff
    if imm & (1 << 25):
        imm -= 1 << 26
    target = offset + 4 * imm
    require(64 <= target <= len(image) - 64, 'Entry targets bytes outside raw Image')
    code = image[target:target + 64]
    require(any(code) and code != b'\xff' * 64, 'Entry points to empty bytes')
    return {'branch_offset': offset, 'entry_offset': target,
            'entry_code_sha256': sha(code), 'image_bytes': len(image), 'sha256': sha(image)}

def verify_relative_kallsyms(image, symbols, base, tool_log):
    """Validate every relative entry against the independent linker map.

    The pinned resolver logs table locations but omits an absolute kernel-base
    line on this path. Location logs are only locators; names and values are
    decoded from the actual unpatched Image and compared with System.map.
    """
    def location(pattern, label):
        values = set(re.findall(pattern, tool_log))
        require(len(values) == 1, 'Missing/ambiguous relative table: ' + label)
        return int(next(iter(values)), 16)
    require('try kallsyms_offsets first for 64-bit relative-base kernel' in tool_log,
            'Absent base log without a recognized relative-kallsyms path')
    offsets = location(r'kallsyms_offsets offset: 0x([0-9a-fA-F]+)', 'offsets')
    names = location(r'kallsyms_names offset: 0x([0-9a-fA-F]+)', 'names')
    table = location(r'kallsyms_token_table offset: 0x([0-9a-fA-F]+)', 'tokens')
    index = location(r'kallsyms_token_index offset: 0x([0-9a-fA-F]+)', 'token index')
    number = location(r'kallsyms_num_syms offset: 0x([0-9a-fA-F]+)', 'number')
    markers = location(r'kallsyms_markers range: \[0x([0-9a-fA-F]+),', 'markers')
    require(0 <= number <= len(image) - 8, 'Kallsyms count is outside Image')
    count = struct.unpack_from('<Q', image, number)[0]
    require(10000 <= count <= 2000000 and offsets + count * 4 <= len(image),
            'Relative kallsyms size/count invalid')
    require(0 <= names < markers <= table < index <= len(image) - 512,
            'Relative kallsyms table order/bounds invalid')
    tokens = []
    for off in struct.unpack_from('<256H', image, index):
        start = table + off
        require(table <= start < index, 'Token begins outside token table')
        end = image.find(b'\0', start, index)
        require(end >= start, 'Token lacks bounded NUL')
        tokens.append(image[start:end].decode('ascii'))
    pos = names
    for i in range(count):
        require(pos < markers, 'Names table truncated')
        length = image[pos]
        pos += 1
        if length & 0x80:
            require(pos < markers, 'Long name length truncated')
            length = (length & 0x7f) | (image[pos] << 7)
            pos += 1
        require(length > 0 and pos + length <= markers, 'Compressed symbol bounds invalid')
        name = ''.join(tokens[token] for token in image[pos:pos + length])
        pos += length
        require(len(name) > 1 and name[0].isalpha(), 'Malformed relative symbol name/type')
        address = base + struct.unpack_from('<I', image, offsets + i * 4)[0]
        require(address in symbols.get(name[1:], ()), 'Relative kallsyms differs from System.map: ' + name[1:])
    require(pos == markers, 'Decoded names do not exactly reach kallsyms markers')
    return {'status': 'PASS_ALL_RELATIVE_KALLSYMS_AGAINST_SYSTEM_MAP',
            'symbols_checked': count, 'base_source': 'independent System.map _text',
            'base': hex(base), 'table_offsets': {'offsets': offsets, 'names': names,
            'tokens': table, 'index': index, 'num_syms': number, 'markers': markers}}

def verify(image, before, kp, system_map, tool_log, key_hash=None):
    orig = inspect_entry(before)
    entry = inspect_entry(image)
    align = (len(before) + 4095) & ~4095
    require(kp[:8] == b'KP1158\0\0' and len(kp) == PAYLOAD_BYTES, 'Payload format/length changed')
    require(sha(kp) == PAYLOAD_SHA, 'Wrong payload SHA256')
    require(b'KP1158\0\0' not in before, 'Raw input already contains a KP payload')
    require(image[align:align + 64] == kp[:64], 'Injected KP header/version differs')
    require(len(image) >= align + len(kp), 'Truncated payload')
    require(image[align + 4096:align + len(kp)] == kp[4096:], 'Injected executable payload body differs')
    require(entry['entry_offset'] == align + 4096, 'Primary entry does not target payload executable entry')
    setup = align + 64
    values = struct.unpack_from('<12q', image, setup + 8)
    require(values[0] == len(before) and values[1] == len(kp), 'Saved image/payload lengths differ')
    require(values[2] == struct.unpack_from('<Q', before, 16)[0], 'Saved original memory Image size differs')
    require(values[3] == 12 and values[4] == align, 'Wrong page shift or setup offset')
    require(values[5] % 4096 == 0 and values[5] >= align, 'Invalid payload runtime start offset')
    require(image[setup + 160:setup + 168] == before[:8], 'Saved primary entry header differs')
    require(image[setup + 168:setup + 232] == bytes(64), 'Direct superkey must remain empty')
    if key_hash is not None:
        require(image[setup + 232:setup + 264] == key_hash, 'Random root key verifier mismatch')
    else:
        require(any(image[setup + 232:setup + 264]), 'Existing image root verifier is empty')
    # setup_preset_t.patch_config follows 64B reserved area after root hash.
    # Its 14 symbol uint64 slots precede patch_su_config. Official tool does
    # not enable it; APatch root install calls are disabled in paired source.
    patch_config = setup + 328
    require(image[patch_config + 14 * 8] == 0, 'Unexpected KP SU configuration enabled')
    symbols = {}
    for line in system_map.splitlines():
        items = line.split()
        if len(items) == 3:
            symbols.setdefault(items[2], set()).add(int(items[0], 16))
    require(len(symbols.get('_text', ())) == 1, 'Missing/ambiguous linker _text')
    base = next(iter(symbols['_text']))
    resolved_base = re.findall(r'kernel base address: 0x([0-9a-fA-F]+)', tool_log)
    require(len(resolved_base) <= 1, 'Multiple resolver base records')
    relative_validation = None
    if resolved_base:
        require(int(resolved_base[0], 16) == base, 'Resolver base differs from System.map')
    else:
        relative_validation = verify_relative_kallsyms(before, symbols, base, tool_log)
    checked = []
    for name, off in re.findall(r'^\[\+\] (\w+): type: \w, offset: 0x([0-9a-fA-F]+)', tool_log, re.M):
        require(len(symbols.get(name, ())) == 1, 'Missing/ambiguous resolved symbol: ' + name)
        require(next(iter(symbols[name])) - base == int(off, 16), 'Resolved offset differs: ' + name)
        checked.append(name)
    require(len(set(checked)) >= 10, 'Too few independently matched linker anchors')
    bridge = next((n for n in ('__arm64_sys_truncate', '__arm64_sys_truncate.cfi_jt', '__arm64_sys_truncate.cfi')
                   if len(symbols.get(n, ())) == 1), None)
    require(bridge is not None, 'Required ABI2 bridge syscall symbol missing')
    bridge_offset = next(iter(symbols[bridge])) - base
    require(0 <= bridge_offset <= len(before) - 16, 'Bridge target lacks file-backed code')
    require(any(before[bridge_offset:bridge_offset + 16]), 'Bridge target code is empty')
    config_names = ('kallsyms_lookup_name', 'printk', 'panic', 'rest_init', 'cgroup_init', 'kernel_init',
                    'report_cfi_failure', '__cfi_slowpath_diag', '__cfi_slowpath', 'copy_process',
                    'cgroup_post_fork', 'avc_denied', 'slow_avc_audit', 'input_handle_event')
    config_checked = []
    for i, name in enumerate(config_names):
        off = struct.unpack_from('<Q', image, patch_config + 8 * i)[0]
        if not off:
            continue
        # try_get_symbol_offset_zero accepts compiler suffix variants.
        alternatives = [n for n in symbols if n == name or n.startswith(name + '.')]
        if name == 'printk':
            alternatives += ['_printk']
        require(any(base + off in symbols.get(n, ()) for n in alternatives), 'Saved patch symbol differs: ' + name)
        config_checked.append(name)
    require('panic' in config_checked and ('rest_init' in config_checked or 'cgroup_init' in config_checked),
            'Missing primary KP init anchors')
    warnings = [l for l in tool_log.splitlines() if l.startswith('[?]')]
    return {'status': 'PASS_STATIC_KPM_ABI2_STRUCTURE_AND_LINKER_ANCHORS', 'hardware_validated': False,
            'source_pin': SOURCE, 'kpimg_sha256': PAYLOAD_SHA, 'kpimg_bytes': len(kp),
            'kpimg_offset': align, 'before': orig, 'patched': entry,
            'bridge_symbol': bridge, 'bridge_offset': bridge_offset,
            'linker_symbols_checked': sorted(set(checked)), 'saved_config_symbols_checked': config_checked,
            'resolver_warnings': warnings, 'kp_su_config': 0,
            'relative_kallsyms_validation': relative_validation,
            'root_key_generation_verified': key_hash is not None,
            'root_key_policy': ('48 random hex characters via stdin FD0; only SHA256 verifier retained in image; plaintext not retained'
                                if key_hash is not None else
                                'Existing stored nonzero verifier only; original key generation and plaintext were not observed'),
            'limitation': 'Static structure/source pairing only. Real boot, KASLR, KPM lifecycle and event behavior require device tests.'}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('tool', 'before', 'kpimg', 'system-map', 'output', 'report', 'log'):
        p.add_argument('--' + name, type=Path, required=True)
    a = p.parse_args()
    require(sys.platform.startswith('linux'), 'Execute official Linux ELF only in the cloud Linux builder')
    require(__debug__, 'Normal Python mode required')
    require(a.before.resolve() != a.output.resolve(), 'Never patch in place')
    for path in (a.output, a.report, a.log):
        require(not path.exists(), 'Preserve earlier result: ' + str(path))
        path.parent.mkdir(parents=True, exist_ok=True)
    before = a.before.read_bytes()
    inspect_entry(before)
    require(b'KP1158\0\0' not in before, 'Input is already patched')
    kp = a.kpimg.read_bytes()
    require(len(kp) == PAYLOAD_BYTES and sha(kp) == PAYLOAD_SHA, 'Unexpected official payload')
    require(sha(a.tool.read_bytes()) == TOOL_SHA, 'Unexpected official kptools binary')
    key = secrets.token_hex(24).encode('ascii')
    key_hash = hashlib.sha256(key).digest()
    command = [str(a.tool.resolve()), '-p', '-i', str(a.before.resolve()), '-k', str(a.kpimg.resolve()),
               '-o', str(a.output.resolve()), '--root-skey-fd', '0']
    result = subprocess.run(command, input=key + b'\n', capture_output=True, timeout=180)
    rawlog = result.stdout + result.stderr
    leaked = key in rawlog
    key = None
    require(not leaked, 'Tool leaked key; raw log not saved')
    require(len(rawlog) <= 4 * 1024 * 1024, 'Tool log exceeded limit')
    log = rawlog.decode('utf-8', 'replace')
    a.log.write_text(log, encoding='utf-8')
    require(result.returncode == 0, 'KPM postprocessor failed; retained bounded tool log')
    require(sha(a.before.read_bytes()) == sha(before), 'Tool modified raw input')
    report = verify(a.output.read_bytes(), before, kp, a.system_map.read_text(encoding='utf-8'), log, key_hash)
    report['kptools_sha256'] = TOOL_SHA
    a.report.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'output_sha256': report['patched']['sha256'],
                      'checked_symbols': len(report['linker_symbols_checked']), 'hardware_validated': False}))

if __name__ == '__main__':
    main()
