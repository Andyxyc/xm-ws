#!/usr/bin/env bash
# Public MiCode sources; integration by xiaomo.
# Driver baseline only, not the SukiSU delivery or a flashable package.
set -euo pipefail
ROOT="${GITHUB_WORKSPACE:?}"
WORK="${RUNNER_TEMP:?}/cmi-driver-baseline"
mkdir "$WORK"
mkdir -p "$ROOT/driver-results"
exec > >(tee "$ROOT/driver-results/build.log") 2>&1
printf 'cmi / MIUI V12.5.10.0.RJACNXM driver baseline. Not flashable.\n'
mkdir "$WORK/deps"
curl --fail --location --retry 2 --connect-timeout 30 --max-time 600 \
  -H "Authorization: Bearer ${GH_TOKEN:?}" -H 'Accept: application/vnd.github+json' \
  https://api.github.com/repos/Andyxyc/xm-ws/actions/artifacts/12186620532/zip \
  -o "$WORK/deps.zip"
printf '4d972ff96e5b79922982da0234d583a2ed9aad9c95dfa3cc9ecd6543fe8307e0  %s\n' "$WORK/deps.zip" | sha256sum -c -
unzip -q "$WORK/deps.zip" -d "$WORK/deps"
(cd "$WORK/deps"; sha256sum -c SHA256SUMS)
fetch_source() {
  local dest="$1" url="$2" commit="$3"
  git init -q "$dest"
  git -C "$dest" fetch -q --depth=1 "$url" "$commit"
  git -C "$dest" checkout -q --detach FETCH_HEAD
  test "$(git -C "$dest" rev-parse HEAD)" = "$commit"
  printf '%s %s\n' "$commit" "$url" >> "$ROOT/driver-results/SOURCES.txt"
}
fetch_source "$WORK/kernel" https://github.com/MiCode/Xiaomi_Kernel_OpenSource.git 64b40409431988d060f7484369c8c2d7deca1bb3
fetch_source "$WORK/kernel/arch/arm64/boot/dts/vendor" https://github.com/MiCode/kernel_devicetree.git 2a5e1922a42960f72104cf0b256112d6dbd4a6ff
fetch_source "$WORK/kernel/techpack/audio" https://github.com/MiCode/vendor_qcom_opensource_audio-kernel.git b85ef7488ff5a99105a67714d4406f690c62c34e
cp "$WORK/deps/SOURCES.txt" "$ROOT/driver-results/DEPENDENCIES.txt"
for n in clang-r377782c gcc64 gcc32; do
  mkdir "$WORK/$n"
  tar -xzf "$WORK/deps/$n.tar.gz" -C "$WORK/$n"
done
export PATH="$WORK/clang-r377782c/bin:$WORK/gcc64/bin:$WORK/gcc32/bin:$PATH"
clang --version | tee "$ROOT/driver-results/clang.txt"
aarch64-linux-androidkernel-ld --version | tee "$ROOT/driver-results/linker.txt"
grep -F r377782c "$ROOT/driver-results/clang.txt"
grep -F '2.27.0.20170315' "$ROOT/driver-results/linker.txt"
export CMI_DRIVER_WORK="$WORK"
python3 - <<'PY'
import os, tarfile, pathlib, json, re, shutil
w=pathlib.Path(os.environ['CMI_DRIVER_WORK']); k=w/'kernel'; repairs=[]
destination=w/'wlan-source';destination.mkdir();destination=destination.resolve()
with tarfile.open(w/'deps/wlan.tar.gz') as t:
    members=t.getmembers();byname={m.name.rstrip('/'):m for m in members}
    if len(byname)!=len(members):raise ValueError('duplicate archive member')
    for m in members:
        if not (m.isfile() or m.isdir() or m.issym()):raise ValueError('unsupported archive member')
    t.extractall(destination,members=[m for m in members if not m.issym()],filter='data')
    for m in members:
        if not m.issym():continue
        marker='/vendor/qcom/opensource/wlan/'
        if marker not in m.linkname:raise ValueError('unexpected link prefix')
        target=m.linkname.split(marker,1)[1]
        if target not in byname or byname[target].issym():raise ValueError('unverified link target')
        src=destination/m.name;dst=destination/target
        if not src.parent.resolve().is_relative_to(destination) or not dst.resolve().is_relative_to(destination):raise ValueError('link escapes archive')
        if src.exists() or src.is_symlink():raise ValueError('existing link destination')
        if not dst.exists():raise ValueError('missing link target')
        rel=os.path.relpath(dst,src.parent);src.symlink_to(rel)
        if src.resolve()!=dst.resolve():raise ValueError('mismatched restored link')
        repairs.append({'path':m.name,'relative_target':rel})
assert len(repairs)==22
for name in ['qcacld-3.0','qca-wifi-host-cmn','fw-api']:
    dest=k/'drivers/staging'/name
    assert not dest.exists() and not dest.is_symlink(),str(dest)
    shutil.copytree(destination/name,dest,symlinks=True)
p=k/'techpack/audio/config/konaauto.conf'; s=p.read_text()
assert len(re.findall(r'=m$',s,re.M))==41
p.write_text(re.sub(r'=m$', '=y',s,flags=re.M))
p=k/'techpack/audio/config/konaautoconf.h'
s=p.read_text();p.write_text(re.sub(r'(#define\s+CONFIG_\w+)_MODULE(\s+1)',r'\1\2',s))
for p in (k/'techpack/audio').rglob('Kbuild'):
    s=p.read_text()
    s=s.replace('$(shell pwd)/kernel/msm-4.19','$(srctree)').replace('$(ANDROID_BUILD_TOP)/kernel/msm-4.19','$(srctree)')
    s=s.replace('AUDIO_ROOT := $(KDIR)/techpack/audio','AUDIO_ROOT := $(srctree)/techpack/audio')
    p.write_text(s)
p=k/'techpack/audio/asoc/codecs/Kbuild';s=p.read_text()
assert 'obj-y\t+= wcd938x/' in s
s=s.replace('obj-y\t+= wcd938x/','obj-y\t+= wcd938x/\n\tobj-y\t+= tfa98xx/')
p.write_text(s)
p=k/'techpack/audio/Makefile';s=p.read_text();assert s.count('obj-y += dsp/elliptic\n')==1
p.write_text(s.replace('obj-y += dsp/elliptic\n',''))
p=k/'drivers/staging/qcacld-3.0/Kbuild';s=p.read_text()
assert 'WLAN_ROOT := drivers/staging/qcacld-3.0' in s
s=s.replace('WLAN_ROOT := drivers/staging/qcacld-3.0','WLAN_ROOT := $(srctree)/drivers/staging/qcacld-3.0')
s=s.replace('WLAN_PROFILE := default','WLAN_PROFILE := qca6390')
p.write_text(s)
p=k/'drivers/staging/Makefile';s=p.read_text();assert 'qcacld-3.0/' not in s;p.write_text(s+'\nobj-$(CONFIG_QCA_CLD_WLAN) += qcacld-3.0/\n')
p=k/'drivers/staging/Kconfig';s=p.read_text();assert 'qcacld-3.0/Kconfig' not in s;assert s.count('endif # STAGING')==1
# MiCode leaves references to two unprovided optional vendor components.
# The cmi_user_defconfig selects neither. Do not create fake implementations.
defcfg=(k/'arch/arm64/configs/cmi_user_defconfig').read_text()
for name,symbol in [('misysinfofreader','MISYSINFOFREADER'),('kperfevents','KPERFEVENTS')]:
    assert not re.search(r'^CONFIG_'+symbol+r'=[ym]$',defcfg,re.M)
    reference='source "drivers/staging/'+name+'/Kconfig"'
    assert s.count(reference)==1
    assert not (k/'drivers/staging'/name/'Kconfig').exists()
    s=s.replace(reference,'# Optional '+symbol+' source is not supplied and is not selected for cmi.')
p.write_text(s.replace('endif # STAGING','source "drivers/staging/qcacld-3.0/Kconfig"\n\nendif # STAGING'))
p=k/'techpack/camera';assert not p.exists() and not p.is_symlink();p.symlink_to('camera-dxo')
for name in ['kperfevents.h','misysinfofreader.h']:
    p=k/'include/linux'/name
    if p.is_symlink():p.unlink()
    if not p.exists():p.symlink_to('../dum/'+name)
    assert p.is_file(),str(p)
(pathlib.Path(os.environ['GITHUB_WORKSPACE'])/'driver-results/source-assembly.json').write_text(json.dumps({'audio_config_m_to_y':41,'wlan_profile':'qca6390','absolute_links_repaired':repairs,'unavailable_unselected_components':['MISYSINFOFREADER','KPERFEVENTS'],'sukisu_included':False,'phone_write':False},indent=2))
PY
export ARCH=arm64 TARGET_PRODUCT=cmi TARGET_BUILD_VARIANT=user
export KBUILD_BUILD_USER=xiaomo KBUILD_BUILD_HOST=cmi-github
MAKE=(make -C "$WORK/kernel" O="$WORK/out" ARCH=arm64 TARGET_PRODUCT=cmi TARGET_BUILD_VARIANT=user CC=clang HOSTCC=clang HOSTCXX=clang++ CLANG_TRIPLE=aarch64-linux-gnu- CROSS_COMPILE=aarch64-linux-androidkernel- CROSS_COMPILE_ARM32=arm-linux-androideabi- LD=aarch64-linux-androidkernel-ld NM=llvm-nm OBJCOPY=llvm-objcopy OBJDUMP=llvm-objdump -j4)
"${MAKE[@]}" cmi_user_defconfig
"$WORK/kernel/scripts/config" --file "$WORK/out/.config" -e QCA_CLD_WLAN
"${MAKE[@]}" olddefconfig
cp "$WORK/out/.config" "$ROOT/driver-results/kernel.config"
grep -x CONFIG_QCA_CLD_WLAN=y "$WORK/out/.config"
grep -x CONFIG_MODVERSIONS=y "$WORK/out/.config"
if grep -Eq '^CONFIG_(MISYSINFOFREADER|KPERFEVENTS)=[ym]$' "$WORK/out/.config"; then exit 2; fi
"${MAKE[@]}" Image.gz
for n in Image Image.gz; do
  test -s "$WORK/out/arch/arm64/boot/$n"
  cp "$WORK/out/arch/arm64/boot/$n" "$ROOT/driver-results/$n"
done
cp "$WORK/out/System.map" "$WORK/out/Module.symvers" "$ROOT/driver-results/"
gzip -dc "$ROOT/driver-results/Image.gz" | cmp - "$ROOT/driver-results/Image"
printf 'Untested driver baseline, without SukiSU. NOT FLASHABLE.\n' > "$ROOT/driver-results/NOT_FLASHABLE.txt"
(cd "$ROOT/driver-results"; sha256sum Image Image.gz kernel.config System.map Module.symvers > SHA256SUMS)
