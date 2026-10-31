from pathlib import Path
import sys,subprocess,hashlib,json,re,zipfile,struct,shutil
common,ak,image=map(Path,sys.argv[1:]);root=Path(__file__).resolve().parent
config=(common/'out/.config').read_text()
required=['CONFIG_KSU=y','CONFIG_KPM=y','CONFIG_KSU_SUSFS=y','CONFIG_HMBIRD_SCHED=y','CONFIG_KALLSYMS=y','CONFIG_KALLSYMS_ALL=y','CONFIG_ARM64_4K_PAGES=y','CONFIG_MODVERSIONS=y','CONFIG_CFI_CLANG=y','CONFIG_LTO_CLANG_THIN=y']
for item in required:assert item in config.splitlines(),item
for opt in re.findall(r'^config (KSU_SUSFS\w*)$',(common.parent/'KernelSU/kernel/Kconfig').read_text(),re.M):
    assert 'CONFIG_'+opt+'=y' in config.splitlines(),opt
raw=image.read_bytes()
assert raw[56:60]==b'ARMd' and len(raw)>10000000
assert ((struct.unpack_from('<Q',raw,24)[0]>>1)&3)==1,'ARM64 4K page header required'
banner=re.search(rb'Linux version ([^\0\n]+)',raw).group(0).decode(errors='replace')
assert banner.startswith('Linux version 6.6.66-android15-8-'),banner
source=Path('build-result/source-provenance.json')
manifest=json.loads(source.read_text());manifest.update(kernel_banner=banner,required_config=required,KPM=json.loads(Path('build-result/kpm-entry.json').read_text()),device_boot_verified=False,manager_ci=41120,manager_sha='0fe8d052ab7f9c314f01c9d3451812115e424b69')
core=ak/'tools/ak3-core.sh'
text=core.read_text()
before='''  blockdev --setrw $BLOCK 2>/dev/null;
  if [ -f "$BIN/flash_erase" -a -f "$BIN/nandwrite" ]; then
    flash_erase $BLOCK 0 0;
    nandwrite -p $BLOCK boot-new.img;
  elif [ "$CUSTOMDD" ]; then
    dd if=/dev/zero of=$BLOCK $CUSTOMDD 2>/dev/null;
    dd if=boot-new.img of=$BLOCK $CUSTOMDD;
  else
    cat boot-new.img /dev/zero > $BLOCK 2>/dev/null || true;
  fi;
  if [ $? != 0 ]; then
    abort "Flashing image failed. Aborting...";
  fi;'''
assert text.count(before)==1,'Pinned AK3 writer source changed'
text=text.replace(before,'  ace_flash_boot "$BLOCK" "$BOOTIMG" "$AKHOME/boot-new.img";',1)
core.write_text(text)
shutil.copyfile(root/'anykernel.sh',ak/'anykernel.sh')
shutil.copyfile(root/'ace-install.sh',ak/'tools/ace-install.sh')
shutil.copyfile(image,ak/'Image')
(ak/'kernel-image.sha256').write_text(hashlib.sha256(raw).hexdigest()+'  Image\n')
# The decorative banner comes from the installer, without an APK bundled in it.
if (ak/'banner').exists():(ak/'banner').unlink()
for f in [ak/'anykernel.sh',core,ak/'tools/ace-install.sh']:
    subprocess.run(['sh','-n',str(f)],check=True)
out=Path('deliverables');out.mkdir(exist_ok=True)
name='SukiSU-41120-OnePlus-Ace5-Pro-6.6.66-A16-KPM-SUSFS2.3.0-AnyKernel3.zip'
dest=out/name
with zipfile.ZipFile(dest,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
    for p in sorted(ak.rglob('*')):
        rel=p.relative_to(ak)
        if p.is_file() and '.git' not in rel.parts and rel.parts[0] not in ['.github'] and p.name not in ['README.md']:
            assert p.suffix.lower()!='.apk','No APK in AK3'
            info=zipfile.ZipInfo(str(rel).replace('\\','/'));info.create_system=3
            info.external_attr=(0o100755 if p.name not in ['Image','LICENSE','kernel-image.sha256'] else 0o100644)<<16
            info.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(info,p.read_bytes(),compresslevel=9)
with zipfile.ZipFile(dest) as z:
    assert z.testzip() is None
    assert z.read('Image')==raw
    assert 'META-INF/com/google/android/update-binary' in z.namelist()
    assert not any(n.endswith('.apk') for n in z.namelist())
manifest.update(ak3_file=name,ak3_sha256=hashlib.sha256(dest.read_bytes()).hexdigest(),ak3_bytes=dest.stat().st_size,installer='standard AK3 entry/repack; current boot only; verified persistent backup; single complete partition write; full readback',install_tested_on_phone=False)
(out/'build-evidence.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
(out/(name+'.sha256')).write_text(manifest['ak3_sha256']+'  '+name+'\n')
(out/'README.txt').write_text('OnePlus Ace 5 Pro / PKR110 / Android 16\nKernel 6.6.66 / android15-8 / 4K\nSukiSU + SUSFS 2.3.0 + paired KPM ABI2\n\nCandidate: physical boot and hardware acceptance are pending.\nKeep an independent stock boot.img before testing.\nInstall ZIP through an AK3-capable root flasher or compatible Recovery.\nSelecting this ZIP in the manager GKI boot-image patch screen is not AK3 installation.\nThe installer keeps your current boot ramdisk and writes the current boot slot only.\nNo APK is bundled.\n',encoding='utf-8')
print(json.dumps({'file':str(dest),'sha256':manifest['ak3_sha256'],'bytes':manifest['ak3_bytes'],'boot_verified':False}))
