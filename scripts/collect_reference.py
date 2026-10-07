#!/usr/bin/env python3
"""Read only public share directory metadata. Never fetch package contents."""
from __future__ import annotations
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SHARE = 'kMhyVv-fWBHH'
ROOT = 38458788
ROOT_NAME = 'SukiSU Ultra OnePlus[更新日期8.17]'
API = 'https://yun.123pan.com/b/api/share/get'
PATTERN = re.compile(r'^AnyKernel3_SukiSUUltra_(?P<su>\d+)_(?P<model>.+?)_Android(?P<android>\d+(?:\.\d+)+)\((?P<kernel>\d+\.\d+\.\d+)\)(?P<features>.*?)\.zip$', re.I)
OUT = Path('reference-audit')

def get_json(url: str) -> tuple[dict, str]:
    if not url.startswith(API + '?'):
        raise ValueError('Only share directory listing URLs are permitted')
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Referer': 'https://yun.123pan.com/', 'Accept':'application/json'})
            with urllib.request.urlopen(req, timeout=25) as response:
                raw = response.read(4_000_001)
            if len(raw) > 4_000_000:
                raise ValueError('Listing response too large')
            obj = json.loads(raw)
            if obj.get('code') not in (0, 200) or not isinstance(obj.get('data'), dict):
                raise ValueError('Share listing unavailable: ' + str(obj.get('message')))
            return obj, hashlib.sha256(raw).hexdigest()
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
            pause = error.headers.get('Retry-After', '')
            if pause.isdigit() and int(pause) > 60:
                raise RuntimeError('Rate-limited; stopped without bypassing wait') from error
            time.sleep(max(2 * (attempt + 1), int(pause) if pause.isdigit() else 0))
        except (urllib.error.URLError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    raise RuntimeError('Unreachable')

def read_folder(folder: tuple[int,str]) -> dict:
    folder_id, path = folder
    items, receipts, cursors, ids = [], [], set(), set()
    cursor = '1'
    for page in range(1, 26):
        url = API + '?' + urllib.parse.urlencode(dict(limit=100, next=cursor, orderBy='file_name', orderDirection='asc', shareKey=SHARE, SharePwd='', ParentFileId=folder_id, Page=page))
        obj, digest = get_json(url)
        data = obj['data']
        if data.get('Expired'):
            raise ValueError('Expired share')
        info = data.get('InfoList')
        if not isinstance(info, list):
            raise ValueError('Missing InfoList')
        receipts.append(dict(url=url, sha256=digest, next=data.get('Next'), count=len(info)))
        for row in info:
            fid = row.get('FileId')
            if type(fid) is not int or fid in ids:
                raise ValueError('Invalid or duplicate file ID within folder pagination')
            ids.add(fid)
            if row.get('Type') not in (0,1):
                raise ValueError('Unknown entry type')
            items.append({key:row.get(key) for key in ('FileId','FileName','Type','Size','CreateAt','UpdateAt','Etag')})
        nxt = str(data.get('Next', ''))
        if nxt == '-1' or (not info and nxt in ('','0')):
            return dict(folder_id=folder_id, path=path, items=items, pages=receipts, complete=True)
        if not nxt or nxt in cursors:
            raise ValueError('Pagination has no usable next cursor')
        cursors.add(nxt)
        cursor = nxt
        time.sleep(0.2)
    raise ValueError('Pagination limit reached; listing not complete')

def parse_package(row: dict, folder: dict) -> dict | None:
    m = PATTERN.fullmatch(row['FileName'])
    if not m:
        return None
    d = m.groupdict()
    android = d['android'].split('.')
    d['android_normalized'] = '.'.join(android + ['0'] * max(0,3-len(android)))
    # Keep folder context: Pad2 in the 6.1 and 6.6 lines is not assumed to be one device.
    d.update(file_id=row['FileId'], filename=row['FileName'], path=folder['path'], size=row['Size'], folder_id=folder['folder_id'])
    return d

def collect() -> dict:
    queue = [(ROOT, ROOT_NAME)]
    visited, folders, failures = set(), [], []
    with cf.ThreadPoolExecutor(max_workers=3) as pool:
        while queue:
            wave, queue = queue, []
            futures = {pool.submit(read_folder, f):f for f in wave}
            for future in cf.as_completed(futures):
                fid, path = futures[future]
                if fid in visited:
                    failures.append(dict(folder_id=fid,path=path,error='Repeated directory ID'))
                    continue
                visited.add(fid)
                try:
                    folder = future.result()
                    folders.append(folder)
                    print(f"Listed {fid}: {len(folder['items'])} entries", flush=True)
                    for item in folder['items']:
                        if item['Type'] == 1:
                            queue.append((item['FileId'],path+'/'+item['FileName']))
                except Exception as error:
                    failures.append(dict(folder_id=fid,path=path,error=str(error)))
                if len(visited) + len(queue) > 250:
                    raise ValueError('Unexpected directory count; stopped at scope limit')
    packages, other = [], []
    for folder in sorted(folders,key=lambda x:x['path']):
        for item in folder['items']:
            if item['Type'] != 0:
                continue
            package = parse_package(item, folder)
            if package:
                packages.append(package)
            else:
                other.append(dict(path=folder['path'], **item))
    combinations = {}
    for package in packages:
        key = (package['model'].lower(), package['android_normalized'],package['kernel'])
        record = combinations.setdefault(key, dict(model=package['model'],android=package['android_normalized'],kernel=package['kernel'],evidence=[]))
        record['evidence'].append(dict(file_id=package['file_id'],filename=package['filename'],folder_id=package['folder_id'],path=package['path']))
    result = dict(source='https://1816791094.share.123pan.cn/123pan/'+SHARE, scope=ROOT_NAME, observed_at=dt.datetime.now(dt.timezone.utc).isoformat(), metadata_only=True, package_downloads=0, complete=not failures, folders=folders, packages=packages, combinations=sorted(combinations.values(),key=lambda x:(x['model'].lower(),x['android'],tuple(map(int,x['kernel'].split('.'))))),other_files=other, failures=failures)
    OUT.mkdir(exist_ok=True)
    (OUT/'listing.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    summary = {key:result[key] for key in ('source','scope','observed_at','complete','metadata_only','package_downloads','failures')}
    summary.update(folder_count=len(folders),package_count=len(packages),pair_count=len(combinations),kernel_versions=sorted({p['kernel'] for p in packages},key=lambda x:tuple(map(int,x.split('.')))),empty_folders=[f['path'] for f in folders if not f['items']])
    (OUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    if failures:
        raise SystemExit('Partial directory listing; inspect failures in listing.json')
    return result

if __name__ == '__main__':
    collect()
