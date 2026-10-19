#!/usr/bin/env python3
"""Fix the incomplete RX address-check backport in the pinned MiCode WLAN tree.

Integration: xiaomo. Keep upstream file notices and module version checks.
This is a compile experiment, not evidence of phone or Wi-Fi functionality.
Reference for the comparison, not a wholesale driver replacement:
https://android.googlesource.com/kernel/google-modules/wlan/qcom/wcn6740/wlan/+/refs/heads/android-gs-akita-android16/qca-wifi-host-cmn/dp/wifi3.0/dp_rx_err.c
The target MiCode call site already requires this check; never stub it true.
"""
import hashlib
import json
import pathlib
import subprocess
import sys

HELPER = '''
/* Complete the RX ring/nbuf DMA address check required by dp_rx_err.c. */
static inline bool
dp_rx_desc_paddr_sanity_check(struct dp_rx_desc *rx_desc, uint64_t ring_paddr)
{
\tif (qdf_unlikely(!rx_desc || !rx_desc->nbuf))
\t\treturn false;

\treturn ring_paddr ==
\t\t(uint64_t)qdf_nbuf_get_frag_paddr(rx_desc->nbuf, 0);
}

'''


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


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
        raise RuntimeError('unrecognized dp_rx.h: do not apply to another revision')
    if blob_sha(caller.read_bytes()) != '44e7b894bf6f5e1a6c7f4a5a5337e8e18c6d6613':
        raise RuntimeError('unrecognized dp_rx_err.c: inspect the actual caller first')
    text = before.decode('utf-8')
    anchor = '#endif /* _DP_RX_H */'
    if text.count(anchor) != 1 or 'dp_rx_desc_paddr_sanity_check' in text:
        raise RuntimeError('header does not match the incomplete backport')
    if '!dp_rx_desc_paddr_sanity_check(rx_desc, msdu_list.paddr[0])' not in caller.read_text():
        raise RuntimeError('required call site changed')
    after = text.replace(anchor, HELPER + anchor)
    # Test the exact helper being inserted, with an instrumented QDF stand-in.
    test_source = r'''#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#define qdf_unlikely(x) (x)
struct fake_nbuf { uint64_t address; };
struct dp_rx_desc { struct fake_nbuf *nbuf; };
static unsigned calls;
static uint64_t qdf_nbuf_get_frag_paddr(struct fake_nbuf *buf, unsigned frag)
{ assert(buf != NULL); assert(frag == 0); calls++; return buf->address; }
''' + HELPER + r'''
int main(void) {
    struct fake_nbuf b = {UINT64_C(0x123456789)};
    struct dp_rx_desc d = {&b}, empty = {NULL};
    assert(dp_rx_desc_paddr_sanity_check(&d, UINT64_C(0x123456789)));
    assert(!dp_rx_desc_paddr_sanity_check(&d, UINT64_C(0x123456788)));
    assert(!dp_rx_desc_paddr_sanity_check(&d, UINT64_C(0x223456789)));
    assert(!dp_rx_desc_paddr_sanity_check(NULL, b.address));
    assert(!dp_rx_desc_paddr_sanity_check(&empty, b.address));
    assert(calls == 3);
    b.address = 0;
    assert(dp_rx_desc_paddr_sanity_check(&d, 0));
    b.address = UINT64_MAX;
    assert(dp_rx_desc_paddr_sanity_check(&d, UINT64_MAX));
    assert(!dp_rx_desc_paddr_sanity_check(&d, UINT64_MAX - 1));
    assert(calls == 6);
    return 0;
}
'''
    unit = results / 'rx-address-check-test.c'
    binary = results / 'rx-address-check-test'
    unit.write_text(test_source, encoding='utf-8')
    subprocess.run(['cc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    str(unit), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
    header.write_text(after, encoding='utf-8')
    (results / 'dp_rx.h.before').write_bytes(before)
    (results / 'dp_rx.h.after').write_text(after, encoding='utf-8')
    (results / 'rx-address-check-result.json').write_text(json.dumps({
        'source_header_blob': blob_sha(before),
        'source_caller_blob': blob_sha(caller.read_bytes()),
        'after_sha256': hashlib.sha256(after.encode()).hexdigest(),
        'test_cases': 8,
        'host_regression': 'passed',
        'real_QDF_compile': 'pending_full_kernel_build',
        'phone_runtime': 'not_tested',
        'CRC_checks_disabled': False,
        'return_true_stub': False,
        'references': [
            'https://github.com/MiCode/vendor_qcom_opensource_wlan/tree/89be27c877aa52bf2fb53ca1ced645d7779bd51a',
            'https://github.com/AstideLabs/android_kernel_xiaomi_sm8250'
        ]
    }, indent=2) + '\n', encoding='utf-8')
    print('RX address-check helper restored; 8 host regression cases passed.')


if __name__ == '__main__':
    main()
