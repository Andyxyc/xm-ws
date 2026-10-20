#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read-only, bounded official cmi MIUI recovery ZIP reference probe.

HTTP Range reads metadata + selected boot/dtbo objects only. No stock partition
image is uploaded, repackaged, flashed or substituted into an AK3 installer.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import struct
import sys
import urllib.request
import zipfile

VERSION = 'V12.5.10.0.RJACNXM'
OFFICIAL_ZIP = (
    'https://hugeota.d.miui.com/V12.5.10.0.RJACNXM/'
    'miui_CMI_V12.5.10.0.RJACNXM_fcaa9c15ff_11.0.zip'
)
MAX_ARCHIVE_SIZE = 6 * 1024**3
CHUNK = 2 * 1024**2
MAX_REQUESTS = 400
LIMITS = {'boot.img': 128 * 1024**2, 'dtbo.img': 64 * 1024**2,
          'vendor_boot.img': 128 * 1024**2}


class RemoteRange(io.RawIOBase):
    def __init__(self, url):
        self.url = url
        self.count = 0
        self.offset = 0
        self.cache_offset = -1
        self.cache = b''
        # Avoid accepting a server that discards Range and sends gigabytes.
        initial = self.fetch_range(0, 0)
        if len(initial) != 1:
            raise RuntimeError('range capability check returned wrong byte count')
        self.offset = 0

    def fetch_range(self, start, end):
        if self.count >= MAX_REQUESTS:
            raise RuntimeError('Too many stock download requests (bounded)')
        req = urllib.request.Request(self.url, headers={
            'Range': f'bytes={start}-{end}', 'Accept-Encoding': 'identity',
            'User-Agent': 'cmi-stock-boot-static-verifier/1.0'})
        with urllib.request.urlopen(req, timeout=40) as resp:
            self.count += 1
            if resp.status != 206:
                raise RuntimeError(f'Official ROM endpoint lacks HTTP Range: {resp.status}')
            if not (resp.url.startswith('https://hugeota.d.miui.com/') or
                    resp.url.startswith('https://bigota.d.miui.com/')):
                raise RuntimeError('Unexpected redirect host for official MIUI ROM')
            header = resp.headers.get('Content-Range', '')
            match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', header)
            if not match or int(match[1]) != start or int(match[2]) != end:
                raise RuntimeError('Malformed HTTP Content-Range: ' + header)
            size = int(match[3])
            if not 1000000 < size <= MAX_ARCHIVE_SIZE:
                raise RuntimeError('Unexpected official ZIP size')
            if not hasattr(self, 'size'):
                self.size = size
            if size != self.size:
                raise RuntimeError('Stock archive size changed during probe')
            data = resp.read(end-start+2)
            if len(data) != end-start+1:
                raise RuntimeError('Incomplete HTTP Range response')
            return data

    def readable(self): return True
    def seekable(self): return True
    def tell(self): return self.offset
    def seek(self, offset, whence=os.SEEK_SET):
        new = offset if whence == os.SEEK_SET else (
            self.offset + offset if whence == os.SEEK_CUR else self.size + offset)
        if new < 0:
            raise ValueError('Negative seek')
        self.offset = new
        return new

    def read(self, n=-1):
        if n == -1:
            raise RuntimeError('Unbounded archive read refused')
        if n < 0: raise ValueError('Negative count')
        remaining = min(n, max(0, self.size - self.offset))
        blocks = []
        while remaining:
            if not self.cache_offset <= self.offset < self.cache_offset + len(self.cache):
                start = (self.offset // CHUNK) * CHUNK
                end = min(self.size, start + CHUNK) - 1
                self.cache = self.fetch_range(start, end)
                self.cache_offset = start
            idx = self.offset - self.cache_offset
            piece = self.cache[idx:idx + remaining]
            if not piece: raise RuntimeError('Empty HTTP cache read')
            blocks.append(piece)
            self.offset += len(piece)
            remaining -= len(piece)
        return b''.join(blocks)


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as source:
        for b in iter(lambda: source.read(1<<20), b''): h.update(b)
    return h.hexdigest()


def check_compiled_dtrees(ref):
    root = ref / 'cmi-device-trees'
    report = json.loads((ref / 'device-tree-verification.json').read_text())
    assert report['device'] == 'cmi'
    result = {}
    for name in ('kona.dtb', 'cmi-sm8250-overlay.dtbo'):
        p = root / name
        data = p.read_bytes()
        if not data.startswith(bytes.fromhex('d00dfeed')):
            raise RuntimeError('Official source output is not FDT: ' + name)
        digest = sha256(p)
        if report['sha256'].get(name) != digest:
            raise RuntimeError('Device tree artifact hash changed: ' + name)
        result[name] = {'size': len(data), 'sha256': digest}
    return result


def summarize_android_boot(data):
    if not data.startswith(b'ANDROID!'):
        raise RuntimeError('Selected stock boot.img lacks Android boot header')
    report = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data),
              'android_boot_magic': True}
    if len(data) >= 48:
        header_version = struct.unpack_from('<I', data, 40)[0]
        report['header_version_candidate'] = header_version
        if header_version in (0, 1, 2):
            report['page_size'] = struct.unpack_from('<I', data, 36)[0]
            report['kernel_size'] = struct.unpack_from('<I', data, 8)[0]
            report['ramdisk_size'] = struct.unpack_from('<I', data, 16)[0]
        elif header_version in (3, 4):
            report['v3_kernel_size'] = struct.unpack_from('<I', data, 8)[0]
            report['v3_ramdisk_size'] = struct.unpack_from('<I', data, 12)[0]
        else:
            report['header_parse_note'] = 'Unsupported header; do not assume stock boot layout'
    return report


def summarize_dtbo(data):
    report = {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
    if len(data) < 32: raise RuntimeError('Stock dtbo.img is too small')
    words = struct.unpack_from('<8I', data)
    if words[0] != 0xd7b7ab1e:
        raise RuntimeError('Stock dtbo.img lacks Android DT table magic')
    _, total, header_size, entry_size, count, entry_offset, page_size, version = words
    if not (32 <= header_size <= 4096 and 32 <= entry_size <= 256 and
            0 < count <= 512 and 0 < entry_offset < len(data) and
            entry_offset + count*entry_size <= len(data) and total <= len(data)):
        raise RuntimeError('Malformed Android DTBO table bounds')
    overlays = []
    for i in range(count):
        off = entry_offset + i*entry_size
        sz, blob_off, mid, rev = struct.unpack_from('<4I', data, off)
        if sz < 40 or blob_off + sz > len(data) or data[blob_off:blob_off+4] != bytes.fromhex('d00dfeed'):
            raise RuntimeError(f'Stock dtbo entry {i} invalid FDT or bounds')
        overlays.append({'entry': i, 'id': mid, 'rev': rev, 'sha256': hashlib.sha256(data[blob_off:blob_off+sz]).hexdigest(), 'size': sz})
    report.update({'dt_table_version': version, 'table_entries': overlays, 'page_size': page_size})
    return report


def inspect_zip(zf, ref_tree):
    report = {'target': 'cmi', 'rom': VERSION, 'official_rom_url': OFFICIAL_ZIP,
              'completeness': 'partial-range-only', 'whole_rom_digest_checked': False,
              'compiled_device_trees': check_compiled_dtrees(ref_tree)}
    infos = zf.infolist()
    report['zip_entries'] = len(infos)
    selected = {}
    for item in infos:
        base = item.filename.rsplit('/', 1)[-1].lower()
        if base in LIMITS:
            selected.setdefault(base, []).append(item)
    report['available_partitions'] = {k: [x.filename for x in v] for k,v in selected.items()}
    report['payload_present'] = any(x.filename.lower().endswith('payload.bin') for x in infos)
    for name, fn in (('boot.img', summarize_android_boot), ('dtbo.img', summarize_dtbo)):
        matches = selected.get(name, [])
        if len(matches) != 1:
            report[name] = {'status': 'missing-or-ambiguous', 'count': len(matches)}
            continue
        info = matches[0]
        if info.file_size <= 0 or info.file_size > LIMITS[name]:
            report[name] = {'status': 'oversize', 'bytes': info.file_size}
            continue
        with zf.open(info, 'r') as stream:
            content = stream.read(LIMITS[name]+1)
        if len(content) != info.file_size:
            raise RuntimeError('Unexpected extracted ROM entry length: '+name)
        report[name] = fn(content)
        report[name]['status'] = 'read-and-CRC-verified'
    metadata = [x for x in infos if x.filename == 'META-INF/com/android/metadata']
    if len(metadata) == 1 and metadata[0].file_size < 32768:
        s = zf.read(metadata[0]).decode('utf-8','replace')
        report['stock_metadata'] = [x for x in s.splitlines() if x.startswith(('pre-device=', 'post-build=', 'post-build-incremental=', 'post-timestamp='))][:12]
    report['stock_boot_dtbo_ready'] = all(report[x].get('status') == 'read-and-CRC-verified' for x in ('boot.img','dtbo.img'))
    report['compiled_vs_stock_exact_match'] = None
    if report['stock_boot_dtbo_ready']:
        report['compiled_vs_stock_exact_match'] = any(
            x['sha256'] == report['compiled_device_trees']['cmi-sm8250-overlay.dtbo']['sha256']
            for x in report['dtbo.img']['table_entries'])
    report['boot_compatibility_claimed'] = False
    report['phone_tested'] = False
    return report


def main():
    if len(sys.argv)!=3:
        raise SystemExit('usage: cmi-stock-rom-probe.py DTREE_ARTIFACT_DIR REPORT_DIR')
    dtree = Path(sys.argv[1]).resolve(strict=True)
    out = Path(sys.argv[2]).resolve()
    out.mkdir(parents=True,exist_ok=True)
    report_path = out/'cmi-stock-rom-reference.json'
    try:
        rom = RemoteRange(OFFICIAL_ZIP)
        with zipfile.ZipFile(rom) as archive:
            report = inspect_zip(archive, dtree)
        report['http_range_requests'] = rom.count
        report['rom_archive_bytes'] = rom.size
        print('Official MIUI archive metadata probed; no ROM files published.')
    except Exception as exc:
        report = {'target':'cmi','rom':VERSION,'stock_boot_dtbo_ready':False,
                  'error':type(exc).__name__ + ': ' + str(exc),
                  'phone_tested':False, 'boot_compatibility_claimed':False}
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        raise
    report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    if not report['stock_boot_dtbo_ready']:
        print('Stock ROM lacks standalone boot.img/dtbo.img; fastboot reference needed.')
        return 2
    return 0


if __name__=='__main__':
    sys.exit(main())
