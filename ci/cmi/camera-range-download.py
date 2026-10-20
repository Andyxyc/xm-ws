#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Bounded parallel read of the exact public OEM camera reference, no device I/O."""
from pathlib import Path
import binascii,concurrent.futures,hashlib,importlib.util,json,os,re,struct,time,urllib.request,zipfile,zlib
MAX_BYTES=2*1024**3
CHUNK=8*1024**2
WORKERS=12
HOSTS=('https://hugeota.d.miui.com/','https://bigota.d.miui.com/')

def decode_parts(parts,info,dest):
    if info.compress_type not in (0,8):raise RuntimeError('Unsupported ZIP compression')
    decoder=zlib.decompressobj(-15) if info.compress_type==8 else None
    size=0;crc=0;read=0
    partial=dest.with_suffix(dest.suffix+'.partial')
    with partial.open('xb') as out:
        for part in parts:
            with part.open('rb') as source:
                while chunk:=source.read(1024**2):
                    read+=len(chunk)
                    data=decoder.decompress(chunk,info.file_size-size+1) if decoder else chunk
                    size+=len(data)
                    if size>info.file_size:raise RuntimeError('Excess decoded bytes')
                    if decoder and decoder.unconsumed_tail:raise RuntimeError('Decode size overflow')
                    crc=binascii.crc32(data,crc);out.write(data)
        if decoder:
            data=decoder.flush();size+=len(data);crc=binascii.crc32(data,crc);out.write(data)
            if not decoder.eof or decoder.unused_data:raise RuntimeError('Truncated/extra deflate stream')
    if read!=info.compress_size or size!=info.file_size or crc&0xffffffff!=info.CRC:
        raise RuntimeError('ZIP length or CRC mismatch')
    if dest.exists():raise RuntimeError('Destination exists')
    partial.rename(dest)
    h=hashlib.sha256()
    with dest.open('rb') as f:
        for b in iter(lambda:f.read(1024**2),b''):h.update(b)
    return {'member':info.filename,'bytes':size,'crc32':f'{crc&0xffffffff:08x}','sha256':h.hexdigest()}

def get_member(remote,info,dest):
    remote.seek(info.header_offset)
    fields=struct.unpack('<4s5H3I2H',remote.read(30))
    if fields[0]!=b'PK\x03\x04' or info.flag_bits&1:raise RuntimeError('Unsupported ZIP header')
    if fields[2]!=info.flag_bits or fields[3]!=info.compress_type:raise RuntimeError('ZIP local/central header mismatch')
    if not 0<info.file_size<=MAX_BYTES or not 0<info.compress_size<=MAX_BYTES:raise RuntimeError('Member too large')
    start=info.header_offset+30+fields[-2]+fields[-1]
    if start+info.compress_size>remote.size:raise RuntimeError('Member outside archive')
    parts_dir=dest.parent/(dest.name+'.parts');parts_dir.mkdir(exist_ok=False)
    bounds=[(n,start+i,min(start+info.compress_size,start+i+CHUNK)-1) for n,i in enumerate(range(0,info.compress_size,CHUNK))]
    if len(bounds)>256:raise RuntimeError('Too many ranges')
    deadline=time.monotonic()+1200
    def fetch(item):
        n,a,b=item;p=parts_dir/f'{n:04d}.part'
        for attempt in range(3):
            if time.monotonic()>deadline:raise TimeoutError('Overall transfer deadline')
            try:
                req=urllib.request.Request(remote.url,headers={'Range':f'bytes={a}-{b}','Accept-Encoding':'identity'})
                with urllib.request.urlopen(req,timeout=35) as resp:
                    if resp.status!=206 or resp.headers.get('Content-Range')!=f'bytes {a}-{b}/{remote.size}':
                        raise RuntimeError('Unexpected HTTP Range response')
                    if not resp.url.startswith(HOSTS):raise RuntimeError('Unexpected redirect')
                    length=b-a+1;read=0
                    with p.open('wb') as f:
                        while read<length:
                            data=resp.read(min(256*1024,length-read))
                            if not data:raise IOError('Short range read')
                            f.write(data);read+=len(data)
                            if time.monotonic()>deadline:raise TimeoutError('Overall transfer deadline')
                        if resp.read(1):raise RuntimeError('Excess range response')
                return n,p
            except (TimeoutError,ConnectionError,IOError) as exc:
                # Never retry HTTP permission, quota, rate-limit or format errors.
                if hasattr(exc,'code') or attempt==2:raise
                time.sleep(2**attempt)
        raise RuntimeError('Unreachable')
    paths={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for f in concurrent.futures.as_completed([pool.submit(fetch,x) for x in bounds]):
            n,p=f.result();paths[n]=p
            if len(paths)%8==0:print(f'Verified byte ranges {len(paths)}/{len(bounds)}',flush=True)
    report=decode_parts([paths[n] for n,_,_ in bounds],info,dest)
    # Keep partial input evidence on failure; remove only this completed download's chunks.
    for p in paths.values():p.unlink()
    parts_dir.rmdir()
    return report

def main():
    from importlib.util import module_from_spec,spec_from_file_location
    vp=Path('ci/cmi/camera-vendor-reference.py');raw=vp.read_bytes()
    if hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()!='7a7a54d4aacab8a92b62379753845310356c115f':
        raise RuntimeError('Camera ABI inspector changed; review before reuse')
    spec=spec_from_file_location('vendor',vp);v=module_from_spec(spec);spec.loader.exec_module(v)
    spec=spec_from_file_location('stock','ci/cmi/stock-rom-probe.py');stock=module_from_spec(spec);spec.loader.exec_module(stock)
    stock.CHUNK=64*1024
    output=Path('camera-reference');output.mkdir(exist_ok=False)
    work=Path(os.environ['RUNNER_TEMP'])/'cmi-camera-ranges';work.mkdir(exist_ok=False)
    try:
        remote=stock.RemoteRange(stock.OFFICIAL_ZIP)
        with zipfile.ZipFile(remote) as archive:
            meta=archive.read('META-INF/com/android/metadata').decode().splitlines()
            if 'pre-device=cmi' not in meta or 'post-build-incremental=V12.5.10.0.RJACNXM' not in meta:raise RuntimeError('ROM identity mismatch')
            hits={}
            for name in ('vendor.new.dat.br','vendor.transfer.list'):
                items=[i for i in archive.infolist() if Path(i.filename).name==name]
                if len(items)!=1:raise RuntimeError('Missing or ambiguous '+name)
                hits[name]=items[0]
            if hits['vendor.transfer.list'].file_size>4*1024**2:raise RuntimeError('Transfer list too large')
            transfer=work/'vendor.transfer.list';transfer.write_bytes(archive.read(hits['vendor.transfer.list']))
            print('Verified exact OEM metadata; reading vendor ranges',flush=True)
            member=get_member(remote,hits['vendor.new.dat.br'],work/'vendor.new.dat.br')
        v.subprocess.run(['brotli','--decompress',str(work/'vendor.new.dat.br'),'-o',str(work/'vendor.new.dat')],check=True,timeout=180)
        structure=v.convert(transfer,work/'vendor.new.dat',work/'vendor.img')
        dest=work/'camera.qcom.so'
        v.subprocess.run(['debugfs','-R','dump /lib64/hw/camera.qcom.so '+str(dest),str(work/'vendor.img')],check=True,capture_output=True,text=True,timeout=60)
        if not dest.is_file():raise RuntimeError('HAL not extracted')
        report={'device':'cmi','rom':'V12.5.10.0.RJACNXM','official_rom_url':stock.OFFICIAL_ZIP,'vendor_member':member,'conversion':structure,'camera_hal':v.inspect_binary(dest,output),'device_access':False,'whole_rom_digest_verified':False}
        (output/'source-verification.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report,indent=2))
    except Exception as exc:
        (output/'failure.json').write_text(json.dumps({'error':type(exc).__name__+': '+str(exc),'device_access':False,'completed':False},indent=2)+'\n')
        raise
if __name__=='__main__':main()
