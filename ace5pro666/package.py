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
# The official manager reads update-binary output lines starting with ui_print.
# For its FD 1, reuse stdout instead of reopening a possible socket via procfs.
# Recovery's non-1 descriptor continues to use the upstream protocol path.
ui_before='''    echo "ui_print $1
      ui_print" >> /proc/self/fd/$OUTFD;'''
ui_after='''    if [ "$OUTFD" = 1 ]; then
      printf 'ui_print %s\\nui_print\\n' "$1";
    else
      echo "ui_print $1
      ui_print" >> /proc/self/fd/$OUTFD;
    fi;'''
for target in [core,ak/'META-INF/com/google/android/update-binary']:
    body=target.read_text()
    assert body.count(ui_before)==1,'Pinned AK3 ui_print implementation changed'
    target.write_text(body.replace(ui_before,ui_after,1))
progress_before='show_progress() { echo "progress $1 $2" >> /proc/self/fd/$OUTFD; }'
progress_after='show_progress() { if [ "$OUTFD" = 1 ]; then printf "progress %s %s\\n" "$1" "$2"; else echo "progress $1 $2" >> /proc/self/fd/$OUTFD; fi; }'
backend=ak/'META-INF/com/google/android/update-binary'
body=backend.read_text();assert body.count(progress_before)==1
backend.write_text(body.replace(progress_before,progress_after,1))
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
(out/'README.txt').write_text('OnePlus Ace 5 Pro / PKR110 / Android 16\nKernel 6.6.66 / android15-8 / 4K\nSukiSU + SUSFS 2.3.0 + paired KPM ABI2\n\nCandidate: physical boot and hardware acceptance are pending.\nKeep an independent stock boot.img before testing.\nUse the official SukiSU manager Flash AK3 entry, with KPM set to Follow Kernel.\nCompatible Recovery uses the standard AK3 update-binary entry.\nThis is a standard AK3 ZIP, not a module package or a GKI boot-image patch input.\nThe installer keeps the selected boot ramdisk.\nNo APK is bundled.\n',encoding='utf-8')
print(json.dumps({'file':str(dest),'sha256':manifest['ak3_sha256'],'bytes':manifest['ak3_bytes'],'boot_verified':False}))
