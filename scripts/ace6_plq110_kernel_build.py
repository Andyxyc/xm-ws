#!/usr/bin/env python3
"""Source-pinned OnePlus Ace 6 PLQ110 GKI 6.6.118 baseline/custom kernel compiler.

OnePlusOSS common 65b954a...; ShirkNeko SUSFS2.3.0 2d11d711...;
SukiSU Ultra builtin c95d6e2... with native KPM and validated UAPI5.
Compilation/source ABI checks do NOT establish ColorOS .500 live vendor ABI.
Never touches a physical Android device. Preserve OEM scheduler and config.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ.get("GITHUB_WORKSPACE", Path.cwd())).resolve()
WORK = ROOT / "ace6_source"
DIAG = ROOT / "ace6_diagnostics"
OUT = ROOT / "ace6_dist"
PINS = {
    "common": ("https://github.com/OnePlusOSS/android_kernel_common_oneplus_sm8750.git", "65b954a773b183a9999b06bb1b2f921f12eaaf11"),
    "KernelSU": ("https://github.com/SukiSU-Ultra/SukiSU-Ultra.git", "c95d6e2c76adb11b0e438e518e32ac4e31f5b1d0"),
    "susfs": ("https://github.com/ShirkNeko/susfs4ksu.git", "2d11d711de80f0f749b3055f8da8f7b9682454e4"),
}
SCREENSHOT_RELEASE = "6.6.118-android15-8-g93e223c276e7-abogki500782043-4k"
FIRMWARE = "PLQ110_16.0.10.500(CN01B110P02)"
BASE = "6.6.118"
WORKERS = 4

def run(*args: str, cwd: Path | None = None, capture: bool = False,
        timeout: int = 2100, env: dict | None = None, input: str | None = None) -> str:
    args = tuple(str(x) for x in args)
    print("$", " ".join(args), flush=True)
    r = subprocess.run(args, cwd=cwd, check=True, text=True, input=input,
                       stdout=subprocess.PIPE if capture else None,
                       timeout=timeout, env=env)
    return r.stdout.strip() if capture else ""

def assert_true(ok: bool, message: str) -> None:
    if not ok:
        raise RuntimeError(message)

def save(name: str, data: object) -> None:
    DIAG.mkdir(parents=True, exist_ok=True)
    (DIAG / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            hasher.update(part)
    return hasher.hexdigest()

def clone(name: str) -> Path:
    url, pin = PINS[name]
    dest = WORK / name
    assert_true(not dest.exists(), "Source destination already exists: " + str(dest))
    dest.mkdir(parents=True)
    run("git", "init", "-q", str(dest))
    run("git", "remote", "add", "origin", url, cwd=dest)
    run("git", "fetch", "-q", "--depth=1", "origin", pin, cwd=dest, timeout=1800)
    run("git", "checkout", "-q", "--detach", "FETCH_HEAD", cwd=dest)
    got = run("git", "rev-parse", "HEAD", cwd=dest, capture=True)
    assert_true(got == pin, "Pinned Git commit mismatch in " + name + ": " + got)
    return dest

def cfg(path: Path) -> dict[str,str]:
    result = {}
    for line in path.read_text().splitlines():
        if line.startswith("CONFIG_") and "=" in line:
            k, v = line.split("=", 1)
            result[k] = v
        else:
            m = re.fullmatch(r"# (CONFIG_\w+) is not set", line)
            if m:
                result[m.group(1)] = "n"
    return result

def symvers(path: Path) -> dict[str, tuple[str, str, tuple[str, ...]]]:
    ret = {}
    for line in path.read_text().splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[2] == "vmlinux":
            ret[parts[1]] = (parts[0], parts[3], tuple(parts[4:]))
    assert_true(len(ret) > 100, "Truncated Module.symvers")
    return ret

def check_image(path: Path) -> str:
    assert_true(path.is_file() and path.stat().st_size > 6000000, "Compiled Image missing or small")
    with path.open("rb") as f:
        f.seek(56)
        assert_true(f.read(4) == b"ARM\x64", "Compiled Image is not an ARM64 kernel")
    return sha256(path)

def prepare() -> None:
    assert_true(not WORK.exists(), "Workspace exists, refusing reuse or overwrite")
    WORK.mkdir()
    DIAG.mkdir(exist_ok=True)
    save("sources.json", {
        "device": "OnePlus Ace 6 PLQ110, ktm", "firmware_from_screenshot": FIRMWARE,
        "active_release_from_screenshot": SCREENSHOT_RELEASE,
        "upstream_source_only": PINS,
        "official_OEM_common_base": BASE,
        "available_official_ace6_vendor_module_branch": "oneplus/sm8750_b_16.0.0_ace_6",
        "vendor_module_commit": "b8d60e4ca773ae7ffcfa62fe9611f2454561b556",
        "module_ABI_for_current_OTA": "NOT_VERIFIED",
        "kernel_boot_test": "NOT_PERFORMED", "flash_executed": False,
    })
    common = clone("common")
    s = (common / "Makefile").read_text()
    for key, value in (("VERSION",6), ("PATCHLEVEL",6), ("SUBLEVEL",118)):
        assert_true(bool(re.search(r"^" + key + r"\s*=\s*" + str(value) + r"$",s,re.M)),
                    "Wrong Ace6 kernel version: " + key)
    assert_true("CLANG_VERSION=r510928" in (common/"build.config.constants").read_text(),
                "Pinned official toolchain mismatch")
    run("git", "worktree", "add", "--detach", str(WORK/"stock"), PINS["common"][1],
        cwd=common, timeout=240)
    ksu = clone("KernelSU")
    # C95 builtin has mismatched KPM/manager constants and manager tracker.
    run(sys.executable, str(ROOT/"scripts/pad2pro_sukisu40996_compat.py"), "apply", str(ksu))
    # Synchronize UAPI2->5 only where real fd/dispatch implementation exists.
    run("bash", str(ROOT/"scripts/ace5pro_fix_uapi5.sh"), str(ksu))
    assert_true((ksu/"kernel/include/uapi/supercall.h").read_text().count("KERNEL_SU_UAPI_VERSION, 5") == 1,
                "SukiSU UAPI5 did not install")
    # Keep builtin KPM unchanged; do not inject patch_linux and do not delete manager.
    assert_true("config KPM" in (ksu/"kernel/Kconfig").read_text(), "Native KPM missing")
    drivers = common/"drivers"
    assert_true(not (drivers/"kernelsu").exists(), "Existing KernelSU symlink or dir found")
    (drivers/"kernelsu").symlink_to(Path("../../KernelSU/kernel"))
    with (drivers/"Makefile").open("a") as f: f.write("\nobj-$(CONFIG_KSU) += kernelsu/\n")
    with (drivers/"Kconfig").open("a") as f: f.write('\nsource "drivers/kernelsu/Kconfig"\n')
    susfs = clone("susfs")
    patch = susfs/"kernel_patches/50_add_susfs_in_gki-android15-6.6.patch"
    adapted = DIAG/"susfs-2.3.0-sukisu-builtin.patch"
    run(sys.executable, str(ROOT/"scripts/ace6_susfs_builtin_hook_adapter.py"),
        "adapt",str(patch),str(adapted))
    for rel in ("fs/susfs.c", "include/linux/susfs.h", "include/linux/susfs_def.h"):
        src = susfs/"kernel_patches"/rel
        target = common/rel
        assert_true(src.is_file() and not target.exists(), "SUSFS source overwrite blocked: "+rel)
        shutil.copy2(src, target)
    ptext = adapted.read_text(encoding="utf-8")
    assert_true("obj-$(CONFIG_KSU_SUSFS)" in ptext, "SUSFS make support missing")
    # Fail completely if the patch does not apply cleanly.
    run("patch", "--batch", "--forward", "-p1", "--fuzz=0", "--dry-run", cwd=common,
        input=ptext, timeout=120)
    run("patch", "--batch", "--forward", "-p1", "--fuzz=0", cwd=common,
        input=ptext, timeout=120)
    assert_true(not list(common.rglob("*.rej")), "SUSFS patch rejects remain")
    # Persist source diff. Never change OEM scheduler, ABI guards or CFI settings.
    (DIAG/"custom-source.patch").write_text(run("git","diff","--binary", cwd=common,capture=True) + "\n")
    save("prepared.json", {
        "source_pin_pass": True, "susfs": "2.3.0", "sukisu_builtin_pin": PINS["KernelSU"][1],
        "native_kpm_available": True, "source_susfs_patch": "zero-fuzz",
        "boot_OTA_compatibility": "NOT_VERIFIED",
    })
    print("PASS: official Ace6 6.6.118, pinned SukiSU UAPI5, KPM and SUSFS source integrated")

def build(kind: str) -> None:
    assert_true(kind in ("stock","custom"), "Invalid build kind")
    assert_true((DIAG/"prepared.json").exists(), "Source prepare stage did not pass")
    tree = WORK/("stock" if kind == "stock" else "common")
    env = dict(os.environ, LOCALVERSION="")
    args = ("make","ARCH=arm64","LLVM=1","LLVM_IAS=1","O=out","LOCALVERSION=")
    run(*args,"gki_defconfig",cwd=tree,env=env,timeout=1200)
    if kind == "custom":
        sc = ("scripts/config","--file","out/.config")
        for option in ("KSU","KSU_SUSFS","KSU_SUSFS_SUS_PATH",
                       "KSU_SUSFS_SUS_MOUNT","KSU_SUSFS_SUS_KSTAT",
                       "KPM","KALLSYMS","KALLSYMS_ALL"):
            run(*sc,"-e",option,cwd=tree)
        for option in ("KSU_SUSFS_SUS_MAP","KSU_SUSFS_OPEN_REDIRECT",
                       "KSU_SUSFS_SPOOF_UNAME","KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG",
                       "KSU_FEATURE_ADBROOT"):
            run(*sc,"-d",option,cwd=tree)
    run(*args,"olddefconfig",cwd=tree,env=env,timeout=1200)
    release = run(*args,"-s","kernelrelease",cwd=tree,env=env,capture=True,timeout=180).splitlines()[-1]
    assert_true(release.startswith(BASE), "Unexpected built kernel release: "+release)
    config = cfg(tree/"out/.config")
    for opt in ("CONFIG_CFI_CLANG","CONFIG_MODVERSIONS","CONFIG_MODULE_SIG"):
        assert_true(config.get(opt) == "y", "Source ABI/safety config missing: "+opt)
    if kind == "custom":
        stock_cfg = cfg(DIAG/"stock.config")
        for opt in ("CONFIG_KSU","CONFIG_KSU_SUSFS","CONFIG_KPM",
                    "CONFIG_KALLSYMS","CONFIG_KALLSYMS_ALL"):
            assert_true(config.get(opt) == "y", "Selected root feature is NOT enabled: "+opt)
        for opt in ("CONFIG_SCHED_HMBIRD", "CONFIG_SCHED_CLASS_EXT", "CONFIG_ARM64_4K_PAGES",
                    "CONFIG_CFI_CLANG","CONFIG_MODVERSIONS","CONFIG_MODULE_SIG"):
            assert_true(config.get(opt,"n") == stock_cfg.get(opt,"n"),
                        "OEM scheduler/KMI option changed: "+opt)
        assert_true(config.get("CONFIG_KSU_SUSFS_SPOOF_UNAME","n") != "y",
                    "Do not activate kernel version spoofing")
    shutil.copy2(tree/"out/.config",DIAG/(kind+".config"))
    save(kind+"-release.json",{
        "compiled_release":release,"screenshot_release":SCREENSHOT_RELEASE,
        "exact_kernelrelease_matches_screenshot":release==SCREENSHOT_RELEASE,
        "target_firmware":FIRMWARE,
    })
    run(*args,"-j"+str(WORKERS),"all",cwd=tree,env=env,timeout=8000)
    image=tree/"out/arch/arm64/boot/Image"
    digest=check_image(image)
    symbols=tree/"out/Module.symvers"
    assert_true(symbols.is_file(), "Missing Module.symvers")
    shutil.copy2(symbols,DIAG/(kind+".symvers"))
    if kind=="stock":
        save("stock-build.json", {"image_sha256":digest,"exported_symbol_count":len(symvers(symbols))})
    else:
        before,after=symvers(DIAG/"stock.symvers"),symvers(symbols)
        missing=sorted(set(before)-set(after))
        changed=sorted(k for k in before.keys()&after.keys() if before[k]!=after[k])
        save("abi-check.json",{
            "reference":"official Ace6 common 6.6.118 with unmodified gki_defconfig",
            "stock_export_count":len(before),"custom_export_count":len(after),
            "missing":missing,"changed":changed,
            "stock_source_only_not_live_vendor_modules":True,
        })
        assert_true(not missing and not changed,
                    f"Kernel source ABI delta (missing {len(missing)}, changed {len(changed)}): refuse package")
        OUT.mkdir(exist_ok=True)
        shutil.copy2(image,OUT/"Image")
        save("custom-build.json", {
            "image_sha256":digest,"KSU_UAPI5":True,"KPM":"Enabled","SUSFS":"Enabled",
            "OEM_scheduler_config_preserved":True,
            "compiled_release":release,"firmware":FIRMWARE,
            "ota_live_module_abi": "UNVERIFIED", "real_device_boot": "NOT_TESTED",
            "flash_executed":False,
        })
    print("PASS:",kind,"Image",digest,"release",release,"symbols",len(symvers(symbols)))

def selftest():
    import tempfile
    with tempfile.TemporaryDirectory(prefix="Ace6_源码测试_") as d:
        p=Path(d)/"config"
        p.write_text("CONFIG_KSU=y\n# CONFIG_KPM is not set\n")
        assert_true(cfg(p)=={"CONFIG_KSU":"y","CONFIG_KPM":"n"},"Config parser regression")
        p.write_text("\n".join(f"0x12345678 name{i} vmlinux EXPORT_SYMBOL" for i in range(150)))
        assert_true(len(symvers(p))==150,"Module.symvers parser regression")
        p.write_bytes(b"junk")
        try:
            check_image(p)
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Invalid Image accepted")
    run(sys.executable, str(ROOT/"scripts/ace6_susfs_builtin_hook_adapter.py"),"selftest")
    run(sys.executable, str(ROOT/"scripts/pad2pro_sukisu40996_compat.py"),"selftest")
    print("PASS: preflight self-tests; no flash or real boot tests")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("stage",choices=["selftest","prepare","stock","custom"])
    op=parser.parse_args().stage
    try:
        if op=="selftest":
            selftest()
        elif op=="prepare":
            prepare()
        else:
            build(op)
    except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as e:
        save("failure-"+op+".json",{"stage":op,"status":"failed","reason":str(e)})
        print("::error::Ace6 kernel "+op+" failed: "+str(e),file=sys.stderr)
        sys.exit(1)
