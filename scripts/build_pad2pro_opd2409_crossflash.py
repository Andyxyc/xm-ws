#!/usr/bin/env python3
"""OPD2413 hardware running cross-flashed OPD2409_15.0.1.501 firmware.
Source-only 6.6.57 ABI checks. Does NOT prove compatibility with live OPPO vendor modules.
No automatic flashing. Reuses and pins known OPD2413 6.6.57 common tree.
Kernel: OnePlusOSS (GPL-2.0); SukiSU kernel: GPL-2.0-only.
SUSFS: simonpunk/cctv18; AK3: osm0sis/cctv18; KPM: SukiSU-Ultra.
The published .701 source is NOT represented as exact .801 firmware source.
"""
from __future__ import annotations
import argparse, hashlib, json, os, re, shutil, subprocess, sys
from pathlib import Path
from pad2pro_susfs_rebase import rebase as rebase_susfs

PINS = {
    'common': ('https://github.com/OnePlusOSS/android_kernel_common_oneplus_sm8750.git', '039d4b06c8751a2feaddbb8423304b0f2452520a'),
    'KernelSU': ('https://github.com/SukiSU-Ultra/SukiSU-Ultra.git', 'c95d6e2c76adb11b0e438e518e32ac4e31f5b1d0'),
    'susfs': ('https://github.com/cctv18/susfs4oki.git', '2919a9ad01205c21b1ce346f6fda08a979c58003'),
    'kpm': ('https://github.com/SukiSU-Ultra/SukiSU_patch.git', '547ae94bcaec53d030398f857950c64662043a5d'),
    'ak3': ('https://github.com/cctv18/AnyKernel3.git', '091ee586e1a5d5c1c1c957d48fe7c61638d04dc4'),
    'clang': ('https://git.codelinaro.org/clo/la/kernelplatform/prebuilts-master/clang/host/linux-x86', 'b099698c583b8361ca771f3cc8d6af6f729f39b3'),
}
MAIN_PIN = '1324dd358468801868339d3b963b639b64947c1d'
# Release string from user-supplied screenshot, NOT the version or ABI of pinned common source.
# Matching vermagic text alone never proves cross-ROM vendor ABI compatibility.
RELEASE = '6.6.57-android15-8-g443be96c6b96d-4k'
ROOT = Path(os.environ.get('GITHUB_WORKSPACE', Path.cwd())).resolve()
WORK = ROOT / 'pad2pro_work'
DIAG = ROOT / 'pad2pro_diagnostics'
DIST = ROOT / 'pad2pro_dist'

def run(args, cwd=None, *, capture=False, timeout=1800, env=None, data=None):
    print('+', ' '.join(map(str, args)), flush=True)
    r = subprocess.run(list(map(str, args)), cwd=cwd, check=True, text=True,
                       stdout=subprocess.PIPE if capture else None,
                       timeout=timeout, env=env, input=data)
    return r.stdout.strip() if capture else ''

def require(ok, message):
    if not ok:
        raise RuntimeError(message)

def save(name, value):
    DIAG.mkdir(exist_ok=True)
    (DIAG / name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''):
            h.update(block)
    return h.hexdigest()

def clone(name, *, full=False):
    url, pin = PINS[name]
    target = WORK / name
    require(not target.exists(), f'Refusing to reuse existing source: {target}')
    target.mkdir()
    run(['git', 'init', '-q', target])
    run(['git', 'remote', 'add', 'origin', url], target)
    args = ['git', 'fetch', '--no-tags'] + ([] if full else ['--depth=1'])
    run(args + ['origin', pin], target)
    run(['git', 'checkout', '--detach', 'FETCH_HEAD'], target)
    require(run(['git', 'rev-parse', 'HEAD'], target, capture=True) == pin, f'{name} source pin mismatch')
    return target

def config(path):
    out = {}
    for line in Path(path).read_text().splitlines():
        if line.startswith('CONFIG_') and '=' in line:
            k, v = line.split('=', 1); out[k] = v
        else:
            m = re.fullmatch(r'# (CONFIG_\w+) is not set', line)
            if m: out[m[1]] = 'n'
    return out

def symvers(path):
    out = {}
    for line in Path(path).read_text().splitlines():
        p = line.split()
        if len(p) >= 4 and p[2] == 'vmlinux': out[p[1]] = (p[0], p[3], tuple(p[4:]))
    require(len(out) > 100, 'Missing or truncated vmlinux symbol versions')
    return out

def check_image(path):
    b = Path(path).read_bytes()
    require(len(b) > 6_000_000 and b[56:60] == b'ARM\x64', 'Invalid ARM64 Image header')
    banners = re.findall(rb'Linux version ([^\x00\n]+)', b)
    require(any(x.startswith((RELEASE+' ').encode()) for x in banners), 'Actual compiled kernel release mismatch')
    return sha(path)

def patch_file(tree, patch):
    text = Path(patch).read_text()
    run(['patch', '--batch', '-p1', '--fuzz=0', '--forward', '--dry-run'], tree, data=text)
    run(['patch', '--batch', '-p1', '--fuzz=0', '--forward'], tree, data=text)

def prepare():
    require(not WORK.exists(), 'Build workspace already exists; preserving it instead of overwriting')
    WORK.mkdir(); DIAG.mkdir(exist_ok=True)
    save('sources.json', {'pins': PINS, 'manager_main_pin': MAIN_PIN,
         'target': 'OPD2409_15.0.1.501(CN01) (crossflashed on OPD2413 hardware)',
         'source_rom': 'OPD2413_15.0.1.701(CN01) ONLY; not a firmware-matched OPPO source',
         'release': RELEASE, 'real_device_test': 'not_performed', 'oppo_firmware_501_vendor_abi': 'not_performed',
         'running_release_taken_from': 'user_photo_not_boot_img',
         'requires_actual_boot_and_vendor_dlkm_for_flash': True})
    common = clone('common')
    mk = (common/'Makefile').read_text()
    require(all(re.search(r'^'+k+r'\s*=\s*'+str(v)+r'$', mk, re.M) for k,v in [('VERSION',6),('PATCHLEVEL',6),('SUBLEVEL',57)]), 'Not actual kernel 6.6.57')
    require('CLANG_VERSION=r510928' in (common/'build.config.constants').read_text(), 'Unexpected official compiler requirement')
    run(['git','worktree','add','--detach', WORK/'stock',PINS['common'][1]], common)
    ksu = clone('KernelSU', full=True)
    run(['git','fetch','--no-tags','origin',MAIN_PIN], ksu)
    count = int(run(['git','rev-list','--count',MAIN_PIN], ksu, capture=True))
    version = 40000 + count - 2815
    require(version == 40996, f'Expected official SukiSU 40996 main revision count, got {version}')
    makefile = ksu/'kernel/Makefile'; s = makefile.read_text()
    s, n = re.subn(r'^KSU_VERSION\s*:=.*$', f'KSU_VERSION     := {version}', s, count=1, flags=re.M)
    require(n == 1, 'SukiSU Makefile version interface changed')
    makefile.write_text(s)
    save('sukisu-version.json', {'version':version,'main_commit_count':count,'version_formula':'40000 + main_count - 2815','builtin_sha':PINS['KernelSU'][1],'manager_sha':MAIN_PIN})
    # Fix the verified pinned builtin ABI mismatch without disabling dynamic manager or KPM.
    # Do this before the UAPI5 backport; unknown code layouts fail the build.
    run([sys.executable, ROOT/'scripts/pad2pro_sukisu40996_compat.py', 'apply', ksu])
    run(['bash',ROOT/'scripts/ace5pro_fix_uapi5.sh',ksu])
    # Reproduce upstream setup integration, without stash/pull or fallback checkout.
    (common/'drivers/kernelsu').symlink_to(Path('../../KernelSU/kernel'))
    with (common/'drivers/Makefile').open('a') as f: f.write('\nobj-$(CONFIG_KSU) += kernelsu/\n')
    with (common/'drivers/Kconfig').open('a') as f: f.write('\nsource "drivers/kernelsu/Kconfig"\n')
    susfs = clone('susfs')
    for rel in ['fs','include/linux']:
        for src in (susfs/'kernel_patches'/rel).iterdir():
            if src.is_file(): shutil.copy2(src,common/rel/src.name)
    # Adapt only the fingerprinted OEM task_mmu.c section; retain SUSFS features.
    rebased = DIAG/'susfs-opd2413-rebased.patch'
    rebase_susfs(susfs/'kernel_patches/50_add_susfs_in_gki-android15-6.6.patch',
                 common/'fs/proc/task_mmu.c', rebased)
    patch_file(common, rebased)
    patch_file(common, ROOT/'patches/unicode_bypass_fix_6.1+.patch')
    require(not list(common.rglob('*.rej')), 'Patch rejects remain')
    # Optional scheduling/compression/network add-ons are not substituted for stock.
    # Keep original OEM scheduler selections, CFI, module signatures and MODVERSIONS.
    clone('kpm'); clone('ak3')
    clang = clone('clang') / 'clang-r510928/bin/clang'
    require(clang.is_file(), 'Pinned official toolchain lacks clang-r510928; refusing generic compiler substitution')
    compiler = run([clang,'--version'], capture=True)
    require('18.' in compiler, 'Unexpected clang version')
    (DIAG/'compiler.txt').write_text(compiler+'\n')
    (DIAG/'source-changes.patch').write_text(run(['git','diff','--binary'], common, capture=True)+'\n')
    save('prepared.json', {'status':'passed','version':version,
         'firmware_501_compatibility':'unverified; source from OnePlus not OPPO',
         'release_string_derived_from_live_photo_not_build_source': True})

def build(kind):
    tree = WORK/('stock' if kind == 'stock' else 'common')
    require((DIAG/'prepared.json').is_file(), 'Preparation did not pass')
    clang = WORK/'clang/clang-r510928/bin'
    env = dict(os.environ, PATH=str(clang)+':'+os.environ['PATH'], LOCALVERSION='')
    args = ['make','ARCH=arm64','LLVM=1','LLVM_IAS=1','O=out','LOCALVERSION=']
    run(args+['gki_defconfig'],tree,env=env)
    sc = ['scripts/config','--file','out/.config']
    run(sc+['--set-str','LOCALVERSION',RELEASE[len('6.6.57'):],'-d','LOCALVERSION_AUTO'],tree)
    if kind != 'stock':
        run(sc+['-e','KSU','-e','KPM','-e','KSU_SUSFS'],tree)
    run(args+['olddefconfig'],tree,env=env)
    cfg = config(tree/'out/.config')
    for key in ['CONFIG_CFI_CLANG','CONFIG_MODVERSIONS','CONFIG_MODULE_SIG','CONFIG_MODULE_SIG_PROTECT']:
        require(cfg.get(key)=='y', f'Original safety/ABI option lost: {key}')
    if kind != 'stock':
        for key in ['CONFIG_KSU','CONFIG_KPM','CONFIG_KSU_SUSFS']:
            require(cfg.get(key)=='y',f'Required feature not enabled: {key}')
        old = config(DIAG/'stock.config')
        for key in ['CONFIG_HMBIRD_SCHED','CONFIG_SLIM_SCHED','CONFIG_SCHED_CLASS_EXT','CONFIG_CFI_CLANG','CONFIG_MODVERSIONS','CONFIG_ARM64_4K_PAGES']:
            require(cfg.get(key,'n') == old.get(key,'n'),f'Unexpected stock ABI/scheduler change: {key}')
    shutil.copy2(tree/'out/.config', DIAG/(kind+'.config'))
    run(args+[f'-j{os.cpu_count() or 2}','all'],tree,env=env,timeout=5400)
    image = tree/'out/arch/arm64/boot/Image'
    digest = check_image(image)
    symbols = tree/'out/Module.symvers'
    require(symbols.is_file(),'No complete Module.symvers produced')
    shutil.copy2(symbols,DIAG/(kind+'.symvers'))
    if kind == 'stock':
        save('stock-build.json',{'sha256':digest,'symbol_count':len(symvers(symbols))})
        # Delete only this job's regenerable stock object directory, not its source or diagnostics.
        out = tree/'out'
        require(out.resolve() == (WORK/'stock/out').resolve() and out.is_dir(), 'Invalid cleanup target')
        shutil.rmtree(out)
    else:
        before, after = symvers(DIAG/'stock.symvers'), symvers(symbols)
        missing = sorted(set(before)-set(after))
        changed = sorted(k for k in before.keys() & after.keys() if before[k] != after[k])
        save('abi-comparison.json',{'stock_export_count':len(before),'missing':missing,'changed':changed,
             'scope':'OnePlus OPD2413 .701 common source only; NOT OPD2409 .501 running vendor modules'})
        require(not missing and not changed, 'Exported kernel ABI changed; refusing to package an installable ZIP')
        staging = WORK/'kpm-image'; staging.mkdir()
        shutil.copy2(image,staging/'Image')
        tool = WORK/'kpm/kpm/patch_linux'
        require(run(['git','hash-object',tool],capture=True)=='c1bc90ea061fa9596c219bb0c8d483429ddb7331','KPM tool blob mismatch')
        tool.chmod(0o755)
        run([tool],staging,timeout=180)
        result = staging/'oImage'
        kpmhash = check_image(result)
        require(kpmhash != digest,'KPM patch produced unchanged image')
        shutil.copy2(result, WORK/'ak3/Image')
        save('custom-build.json',{'pre_kpm_sha256':digest,'image_sha256':kpmhash,'kpm':'patched',
            'abi_gate':'passed_source_only','opd2409_live_vendor_abi':'UNVERIFIED',
            'real_device_test':'not_performed','flash_permission':'BLOCKED'})

def selftest():
    import tempfile
    with tempfile.TemporaryDirectory(prefix='平板2 Pro & 测试 ') as d:
        p=Path(d)/'测试.config'; p.write_text('CONFIG_KSU=y\n# CONFIG_KPM is not set\n')
        require(config(p)=={'CONFIG_KSU':'y','CONFIG_KPM':'n'},'Config parser regression')
        p.write_bytes(b'bad')
        try: check_image(p)
        except RuntimeError: pass
        else: raise RuntimeError('Invalid image accepted')
        p.write_text('\n'.join(f'0x00000001 sym{i} vmlinux EXPORT_SYMBOL' for i in range(101)))
        require(len(symvers(p))==101,'Symbol version parser regression')
    run([sys.executable, ROOT/'scripts/test_pad2pro_susfs_rebase.py'])
    run([sys.executable, ROOT/'scripts/pad2pro_sukisu40996_compat.py', 'selftest'])
    print('PASS: local unit tests; no kernel build or device flashing in selftest')

if __name__ == '__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('stage', choices=['selftest','prepare','stock','custom'])
    stage=ap.parse_args().stage
    try:
        if stage=='selftest': selftest()
        elif stage=='prepare': prepare()
        else: build(stage)
    except (RuntimeError,ValueError,OSError,subprocess.SubprocessError) as exc:
        save('failure-'+stage+'.json',{'stage':stage,'error':str(exc),'status':'failed'})
        print('::error::'+str(exc),file=sys.stderr); sys.exit(1)
