#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Read-only inspection of camera ABI from the exact public cmi ROM.
The OEM executable is never run or published. No phone is accessed.
"""
from pathlib import Path
import binascii,hashlib,importlib.util,json,os,struct,subprocess,urllib.request,zipfile,zlib
MAX_VENDOR=2*1024**3

def get_member(remote,info,dest):
    remote.seek(info.header_offset)
    fields=struct.unpack('<4s5H3I2H',remote.read(30))
    if fields[0]!=b'PK\x03\x04' or info.flag_bits&1:
        raise RuntimeError('Unsupported ZIP header')
    start=info.header_offset+30+fields[-2]+fields[-1]
    end=start+info.compress_size-1
    if not 0<info.file_size<=MAX_VENDOR or not 0<info.compress_size<=MAX_VENDOR:
        raise RuntimeError('ZIP member exceeds bound')
    decoder=zlib.decompressobj(-15) if info.compress_type==8 else None
    if info.compress_type not in (0,8):raise RuntimeError('Unsupported compression')
    req=urllib.request.Request(remote.url,headers={'Range':f'bytes={start}-{end}','Accept-Encoding':'identity'})
    crc=0;size=0;read=0
    with urllib.request.urlopen(req,timeout=60) as resp,dest.open('wb') as out:
        if resp.status!=206 or resp.headers.get('Content-Range')!=f'bytes {start}-{end}/{remote.size}':
            raise RuntimeError('Range response mismatch')
        if not resp.url.startswith(('https://hugeota.d.miui.com/','https://bigota.d.miui.com/')):
            raise RuntimeError('Unexpected redirect')
        while True:
            chunk=resp.read(min(1024**2,info.compress_size-read+1))
            if not chunk:break
            read+=len(chunk)
            if read>info.compress_size:raise RuntimeError('Excess range bytes')
            data=decoder.decompress(chunk) if decoder else chunk
            size+=len(data)
            if size>info.file_size:raise RuntimeError('Excess decoded bytes')
            crc=binascii.crc32(data,crc);out.write(data)
        if decoder:
            data=decoder.flush();size+=len(data);crc=binascii.crc32(data,crc);out.write(data)
            if not decoder.eof or decoder.unused_data:raise RuntimeError('Truncated deflate')
    if read!=info.compress_size or size!=info.file_size or crc&0xffffffff!=info.CRC:
        raise RuntimeError('ZIP length or CRC mismatch')
    return {'member':info.filename,'bytes':size,'crc32':f'{crc&0xffffffff:08x}','sha256':hashlib.sha256(dest.read_bytes()).hexdigest()}

def ranges(text):
    p=list(map(int,text.split(',')))
    if not p or p[0]!=len(p)-1 or p[0]%2:raise RuntimeError('Invalid range list')
    r=list(zip(p[1::2],p[2::2]))
    if any(a<0 or a>=b or b*4096>MAX_VENDOR for a,b in r):raise RuntimeError('Invalid extents')
    return r

def convert(transfer,dat,image):
    lines=transfer.read_text().splitlines()
    if int(lines[0]) not in (3,4) or int(lines[2]) or int(lines[3]):raise RuntimeError('Not full stateless OTA')
    ops=[]
    for line in lines[4:]:
        op,extent=line.split()
        if op not in ('new','erase','zero'):raise RuntimeError('Incremental command rejected')
        ops.append((op,ranges(extent)))
    end=max(b for _,rr in ops for a,b in rr)
    needed=sum((b-a)*4096 for op,rr in ops if op=='new' for a,b in rr)
    if dat.stat().st_size!=needed:raise RuntimeError('Dat extent size mismatch')
    with image.open('wb') as out,dat.open('rb') as src:
        out.truncate(end*4096)
        for op,rr in ops:
            if op!='new':continue
            for a,b in rr:
                out.seek(a*4096);left=(b-a)*4096
                while left:
                    chunk=src.read(min(left,1024**2))
                    if not chunk:raise RuntimeError('Truncated dat')
                    out.write(chunk);left-=len(chunk)
        if src.read(1):raise RuntimeError('Unconsumed dat bytes')
    return {'image_bytes':end*4096,'new_bytes':needed,'transfers':len(ops)}

def inspect_binary(dest,output):
    from elftools.elf.elffile import ELFFile
    from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
    raw=dest.read_bytes()
    if len(raw)<64 or raw[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<H',raw,18)[0]!=183:
        raise RuntimeError('Stock camera HAL not ARM64 ELF')
    with dest.open('rb') as source:
        elf=ELFFile(source);table=elf.get_section_by_name('.dynsym')
        if table is None:raise RuntimeError('No dynamic symbol table')
        selected=[];names=[]
        for symbol in table.iter_symbols():
            name=symbol.name
            if symbol['st_info']['type']!='STT_FUNC' or not symbol['st_size']:continue
            if any(t in name for t in ('CSLAcquireDevice','IPENode','BPSNode','OIS','Ois')):
                names.append({'name':name,'address':symbol['st_value'],'size':symbol['st_size']})
                if any(t in name for t in ('SetupDeviceResource','AcquireDevice','CreateCmdList','LoadFirmware','ConfigureOIS')):selected.append(symbol)
        (output/'camera-abi-symbols.json').write_text(json.dumps(names,indent=2)+'\n')
        md=Cs(CS_ARCH_ARM64,CS_MODE_ARM);total=0
        for symbol in selected:
            start=symbol['st_value'];length=symbol['st_size']
            if length>131072 or total+length>1024**2:continue
            seg=next((g for g in elf.iter_segments() if g['p_type']=='PT_LOAD' and g['p_vaddr']<=start and start+length<=g['p_vaddr']+g['p_filesz']),None)
            if seg is None:raise RuntimeError('Symbol outside ELF segments')
            offset=seg['p_offset']+start-seg['p_vaddr']
            lines=[f'{i.address:016x} {i.bytes.hex()} {i.mnemonic} {i.op_str}' for i in md.disasm(raw[offset:offset+length],start)]
            (output/f'abi-{start:016x}.asm').write_text(symbol.name+'\n'+'\n'.join(lines)+'\n')
            total+=length
    return {'path':'/vendor/lib64/hw/camera.qcom.so','bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'inspected_machine_code_bytes':total,'oem_binary_published':False}

def main():
    spec=importlib.util.spec_from_file_location('stock','ci/cmi/stock-rom-probe.py')
    stock=importlib.util.module_from_spec(spec);spec.loader.exec_module(stock)
    work=Path(os.environ['RUNNER_TEMP'])/'cmi-camera-stock-ref';work.mkdir(exist_ok=False)
    output=Path('camera-reference');output.mkdir(exist_ok=False)
    remote=stock.RemoteRange(stock.OFFICIAL_ZIP)
    with zipfile.ZipFile(remote) as archive:
        meta=archive.read('META-INF/com/android/metadata').decode().splitlines()
        if 'pre-device=cmi' not in meta or 'post-build-incremental=V12.5.10.0.RJACNXM' not in meta:raise RuntimeError('ROM identity mismatch')
        hits={}
        for name in ('vendor.new.dat.br','vendor.transfer.list'):
            match=[i for i in archive.infolist() if Path(i.filename).name==name]
            if len(match)!=1:raise RuntimeError('Missing/ambiguous '+name)
            hits[name]=match[0]
        print('Verified official ROM; vendor compressed bytes:',hits['vendor.new.dat.br'].file_size,flush=True)
        transfer=work/'vendor.transfer.list'
        if hits['vendor.transfer.list'].file_size>4*1024**2:raise RuntimeError('Excess transfer metadata')
        transfer.write_bytes(archive.read(hits['vendor.transfer.list']))
        member=get_member(remote,hits['vendor.new.dat.br'],work/'vendor.new.dat.br')
    subprocess.run(['brotli','--decompress',str(work/'vendor.new.dat.br'),'-o',str(work/'vendor.new.dat')],check=True,timeout=180)
    structure=convert(transfer,work/'vendor.new.dat',work/'vendor.img')
    dest=work/'camera.qcom.so'
    subprocess.run(['debugfs','-R','dump /lib64/hw/camera.qcom.so '+str(dest),str(work/'vendor.img')],check=True,capture_output=True,text=True,timeout=60)
    if not dest.is_file():raise RuntimeError('Stock camera HAL not extracted')
    report={'device':'cmi','rom':'V12.5.10.0.RJACNXM','official_rom_url':stock.OFFICIAL_ZIP,'vendor_member':member,'conversion':structure,'camera_hal':inspect_binary(dest,output),'purpose':'read-only ABI comparison','whole_rom_digest_verified':False,'device_access':False}
    (output/'source-verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
