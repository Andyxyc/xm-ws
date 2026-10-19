#!/usr/bin/env python3
"""Expose MiCode's existing RX DMA check for the non-debug QCA6390 build.

Integration: xiaomo. No replacement driver, CRC bypass or always-true stub.
MiCode defines the function under RX_DESC_DEBUG_CHECK but calls it outside
that guard. AstideLabs has an else-side stub; this experiment instead moves
the original real comparison outside the guard, leaving debug allocation
and descriptor bookkeeping conditional. The function body is unchanged.
The first repair attempt incorrectly assumed the definition was absent;
its revision guard stopped before modifying the header. This corrects that
assumption, with preprocessor regression tests for both configurations.
"""
import hashlib
import json
import pathlib
import re
import subprocess
import sys

NAME = 'dp_rx_desc_paddr_sanity_check'
FUNCTION = re.compile(r'static\s+inline\s+bool\s+' + NAME + r'\s*\([^)]*\)\s*\{[^}]*\}')
START = '#ifdef RX_DESC_DEBUG_CHECK\n/**\n * ' + NAME + '()'
END = '#endif /* RX_DESC_DEBUG_CHECK */'
GUARD = '#ifdef RX_DESC_DEBUG_CHECK\n'
PREFIX = r'''#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
struct fake_nbuf { uint64_t address; };
struct dp_rx_desc { struct fake_nbuf *nbuf; };
static unsigned calls;
static uint64_t qdf_nbuf_get_frag_paddr(struct fake_nbuf *buf, unsigned frag)
{ assert(buf != NULL); assert(frag == 0); calls++; return buf->address; }
'''
TEST = r'''
int main(void) {
    const uint64_t cases[][2] = {
        {UINT64_C(0x123456789), UINT64_C(0x123456789)},
        {UINT64_C(0x123456789), UINT64_C(0x123456788)},
        {UINT64_C(0x123456789), UINT64_C(0x223456789)},
        {0, 0}, {0, 1}, {UINT64_MAX, UINT64_MAX},
        {UINT64_MAX, UINT64_MAX - 1}, {1, 1}
    };
    const bool expected[] = {true, false, false, true, false, true, false, true};
    struct fake_nbuf b;
    struct dp_rx_desc d = {&b};
    for (unsigned i = 0; i < 8; i++) {
        b.address = cases[i][0];
        assert(dp_rx_desc_paddr_sanity_check(&d, cases[i][1]) == expected[i]);
    }
    assert(calls == 8);
    return 0;
}
'''


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def preprocess(section: str, debug: bool) -> str:
    args = ['cc', '-E', '-P', '-x', 'c']
    if debug:
        args.append('-DRX_DESC_DEBUG_CHECK=1')
    result = subprocess.run(args + ['-'], input=section, text=True,
                            capture_output=True, check=True)
    return result.stdout


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit('usage: repair-cmi-wlan.py KERNEL_DIRECTORY RESULTS_DIRECTORY')
    kernel = pathlib.Path(sys.argv[1]).resolve(strict=True)
    results = pathlib.Path(sys.argv[2]).resolve(strict=True)
    relative = pathlib.Path('drivers/staging/qca-wifi-host-cmn/dp/wifi3.0')
    header = kernel / relative / 'dp_rx.h'
    caller = kernel / relative / 'dp_rx_err.c'
    before = header.read_bytes()
    if blob_sha(before) != '866c2b62158e809923aedc527ef04ebdb312457b':
        raise RuntimeError('unrecognized dp_rx.h or repeated patch; inspect revision')
    if blob_sha(caller.read_bytes()) != '44e7b894bf6f5e1a6c7f4a5a5337e8e18c6d6613':
        raise RuntimeError('unrecognized dp_rx_err.c; inspect caller')
    text = before.decode('utf-8')
    if text.count(START) != 1 or len(FUNCTION.findall(text)) != 1:
        raise RuntimeError('expected exactly one debug-guarded definition')
    if '!dp_rx_desc_paddr_sanity_check(rx_desc, msdu_list.paddr[0])' not in caller.read_text():
        raise RuntimeError('required unconditional call site changed')
    start = text.index(START)
    stop = text.index(END, start) + len(END)
    section = text[start:stop]
    match = FUNCTION.search(section)
    if match is None or section.count(GUARD) != 1:
        raise RuntimeError('unexpected conditional section')
    original_function = match.group(0)
    if 'return (ring_paddr == qdf_nbuf_get_frag_paddr(rx_desc->nbuf, 0));' not in original_function:
        raise RuntimeError('DMA address comparison changed')
    # Only relocate the preprocessor guard. Preserve the existing function.
    replacement = section[len(GUARD):match.end()] + '\n\n' + GUARD + section[match.end():]
    if len(FUNCTION.findall(replacement)) != 1:
        raise RuntimeError('duplicate function introduced')
    off_before = FUNCTION.findall(preprocess(section, False))
    on_before = FUNCTION.findall(preprocess(section, True))
    if off_before or len(on_before) != 1:
        raise RuntimeError('the original non-debug failure was not reproduced')
    checks = []
    for debug in (False, True):
        output = preprocess(replacement, debug)
        functions = FUNCTION.findall(output)
        if len(functions) != 1 or functions[0] != on_before[0]:
            raise RuntimeError('function body changed or not visible in both builds')
        suffix = 'debug' if debug else 'nondebug'
        unit = results / ('rx-address-check-' + suffix + '.c')
        binary = results / ('rx-address-check-' + suffix)
        unit.write_text(PREFIX + functions[0] + TEST, encoding='utf-8')
        subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                        str(unit), '-o', str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
        checks.append({'configuration': suffix, 'cases': 8, 'result': 'passed'})
    after = text[:start] + replacement + text[stop:]
    if FUNCTION.search(after).group(0) != original_function:
        raise RuntimeError('original helper was not preserved byte-for-byte')
    header.write_text(after, encoding='utf-8')
    (results / 'dp_rx.h.before').write_bytes(before)
    (results / 'dp_rx.h.after').write_text(after, encoding='utf-8')
    (results / 'rx-address-check-result.json').write_text(json.dumps({
        'source_header_blob': blob_sha(before),
        'source_caller_blob': blob_sha(caller.read_bytes()),
        'after_sha256': hashlib.sha256(after.encode()).hexdigest(),
        'original_nondebug_failure_reproduced': True,
        'original_comparison_body_preserved': True,
        'debug_and_nondebug_regression': checks,
        'real_QDF_compile': 'pending_full_kernel_build',
        'phone_runtime': 'not_tested',
        'CRC_checks_disabled': False,
        'return_true_stub_added': False,
        'previous_attempt': 'Stopped at an incorrect source assumption before modifying the header.',
        'references': [
            'https://github.com/MiCode/vendor_qcom_opensource_wlan/blob/89be27c877aa52bf2fb53ca1ced645d7779bd51a/qca-wifi-host-cmn/dp/wifi3.0/dp_rx.h',
            'https://github.com/AstideLabs/android_kernel_xiaomi_sm8250/blob/android17-aptusitu/drivers/staging/qca-wifi-host-cmn/dp/wifi3.0/dp_rx.h'
        ]
    }, indent=2) + '\n', encoding='utf-8')
    print('Existing RX DMA comparison exposed in both configurations; 16 host cases passed.')


if __name__ == '__main__':
    main()
