from pathlib import Path
import sys,hashlib,json,re,subprocess
root=Path(__file__).resolve().parent
common,ksu=map(lambda s:Path(s).resolve(),sys.argv[1:])
manifest=json.loads((root/'susfs230/manifest.json').read_text())
patch=root/'susfs230/50_add_susfs_230_cctv18_9a56.patch'
assert hashlib.sha256(patch.read_bytes()).hexdigest()=='046be63fccae5e154672071d00482afe0e784d8aa71085607c408883ba094a59'
subprocess.run([sys.executable,str(root/'susfs230/install_core.py'),str(common)],check=True)
link=common/'drivers/kernelsu'
assert not link.exists()
link.symlink_to('../../KernelSU/kernel',target_is_directory=True)
with (common/'drivers/Makefile').open('a') as f:f.write('\nobj-$(CONFIG_KSU) += kernelsu/\n')
with (common/'drivers/Kconfig').open('a') as f:f.write('\nsource "drivers/kernelsu/Kconfig"\n')
suffix='-android15-8-g29d86c5fc9dd-abogki428889875-4k'
# The target release string is kept for vendor module version matching; source pin remains explicit.
p=common/'scripts/setlocalversion';s=p.read_text()
old='echo "${KERNELVERSION}${file_localversion}${config_localversion}${LOCALVERSION}${scm_version}"'
assert s.count(old)==1
p.write_text(s.replace(old,f'echo "6.6.66{suffix}"',1))
cfg=common/'arch/arm64/configs/gki_defconfig'
s=cfg.read_text();assert 'CONFIG_HMBIRD_SCHED=y' in s
settings={'CONFIG_KSU':'y','CONFIG_KPM':'y','CONFIG_KSU_FEATURE_ADBROOT':'y','CONFIG_KSU_SUSFS':'y','CONFIG_KALLSYMS':'y','CONFIG_KALLSYMS_ALL':'y','CONFIG_IKCONFIG':'y','CONFIG_IKCONFIG_PROC':'y','CONFIG_LOCALVERSION':'""','CONFIG_LOCALVERSION_AUTO':'n','CONFIG_LTO_CLANG':'y','CONFIG_LTO_CLANG_THIN':'y','CONFIG_LTO_CLANG_FULL':'n','CONFIG_ARM64_4K_PAGES':'y','CONFIG_ARM64_16K_PAGES':'n','CONFIG_ARM64_64K_PAGES':'n'}
kconfig=(ksu/'kernel/Kconfig').read_text()
for opt in re.findall(r'^config (KSU_SUSFS\w*)$',kconfig,re.M):settings['CONFIG_'+opt]='y'
for key,val in settings.items():
    s=re.sub(r'(?m)^(?:'+key+r'=.*|# '+key+r' is not set)\n?','',s)
    s+=f'{key}={val}\n' if val!='n' else f'# {key} is not set\n'
cfg.write_text(s)
out=Path('build-result')
out.mkdir(exist_ok=True)
provenance={'kernel_source':'cctv18/android_kernel_common_oneplus_sm8750','kernel_pin':'9a56e8288fc62e2047a142114faeb9467447311d','sukisu_pin':'b16e899a555e9b96aa1225f049cd7274820ca5b8','susfs_upstream':'93114563fd6b08092b9ce8c0309738c921ac8bd1','susfs_patch_sha256':hashlib.sha256(patch.read_bytes()).hexdigest(),'target_kernel':'6.6.66'+suffix,'version_string_is_not_stock_source_claim':True,'optional_scheduler_compression_network_patches_added':False,'stock_hmbird_preserved':True,'device_boot_verified':False,'susfs_adaptation':manifest}
provenance['official_version_inputs']={'main_sha':'0fe8d052ab7f9c314f01c9d3451812115e424b69','commit_count':3935,'formula':'40000 + 3935 - 2815','version_code':41120,'version_tag':'4.3.0','builtin_source_identity_is_separate':True}
(out/'source-provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
print('Pinned 6.6.66 source + complete SUSFS2.3.0 + official SukiSU prepared')
