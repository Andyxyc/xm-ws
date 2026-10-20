#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Independent ARM64 object verifier for cmi experimental SukiSU + legacy SUSFS.

Does not turn compilation success into an assertion of boot compatibility.
"""
from pathlib import Path
import hashlib,json,re,subprocess,sys
ROOT_CALLS={
    "fs/exec.o":["ksu_handle_execveat"],
    "fs/open.o":["ksu_handle_faccessat"],
    "fs/stat.o":["ksu_handle_stat","ksu_handle_vfs_fstat"],
    "fs/read_write.o":["ksu_handle_vfs_read"],
    "kernel/reboot.o":["ksu_handle_sys_reboot"],
}
SUSFS_SYMBOLS=("susfs_init","susfs_spoof_uname","susfs_set_uname","susfs_spoof_cmdline_or_bootconfig")
SUSFS_CALLS={
    "kernel/sys.o":["susfs_spoof_uname","cmi_susfs_legacy_prctl"],
    "fs/proc/cmdline.o":["susfs_spoof_cmdline_or_bootconfig"],
}
def run(args):
    return subprocess.run(args,check=True,capture_output=True,text=True,timeout=30).stdout
def verify(out,res):
    cfg=(out/".config").read_text()
    for required in ("CONFIG_KSU=y","CONFIG_KSU_SUSFS=y","CONFIG_MODVERSIONS=y","CONFIG_QCA_CLD_WLAN=y"):
        if required not in cfg.splitlines():raise RuntimeError("Missing configuration: "+required)
    for prefix in ("CONFIG_KPM=","CONFIG_KSU_DEBUG="):
        if any(line.startswith(prefix) for line in cfg.splitlines()):
            raise RuntimeError("Unexpected debug or KPM configuration: "+prefix)
    sysmap=(out/"System.map").read_text()
    for sym in (*SUSFS_SYMBOLS,"kernelsu_init"):
        if not re.search(r"\b[Tt]\s+"+sym+r"$",sysmap,re.M):
            raise RuntimeError("Symbol not present in real System.map: "+sym)
    paths={}
    for rel,names in ROOT_CALLS.items():
        obj=out/rel
        if "AArch64" not in run(["readelf","-h",str(obj)]):
            raise RuntimeError("Not ARM64: "+rel)
        undefined=run(["nm","-u",str(obj)])
        for name in names:
            if not re.search(r"\bU\s+"+name+r"$",undefined,re.M):
                raise RuntimeError("Missing actual SukiSU relocation "+rel+":"+name)
            if not re.search(r"\b[Tt]\s+"+name+r"$",sysmap,re.M):
                raise RuntimeError("Missing linked SukiSU implementation: "+name)
        paths[rel]={"sha256":hashlib.sha256(obj.read_bytes()).hexdigest(),
                    "actual_undefined_hooks":names}
    # Symbols merely present in System.map do not prove the hook callsites run.
    # Require actual ARM64 relocations from uname/cmdline/prctl implementations.
    susfs_callers={}
    for rel,names in SUSFS_CALLS.items():
        obj=out/rel
        if "AArch64" not in run(["readelf","-h",str(obj)]):
            raise RuntimeError("Not ARM64 SUSFS caller: "+rel)
        undefined=run(["nm","-u",str(obj)])
        for name in names:
            if not re.search(r"\bU\s+"+name+r"$",undefined,re.M):
                raise RuntimeError("Missing real SUSFS relocation: "+rel+":"+name)
            if not re.search(r"\b[Tt]\s+"+name+r"$",sysmap,re.M):
                raise RuntimeError("SUSFS call target missing in vmlinux: "+name)
        susfs_callers[rel]={"sha256":hashlib.sha256(obj.read_bytes()).hexdigest(),
                            "actual_undefined_hooks":names}
    susobj=out/"fs/susfs.o"
    if not susobj.is_file() or "AArch64" not in run(["readelf","-h",str(susobj)]):
        raise RuntimeError("Missing real SUSFS ARM64 object")
    evidence={
       "root_hook_objects":paths,"susfs_kernel_call_objects":susfs_callers,
       "susfs_arm64_object_sha256":hashlib.sha256(susobj.read_bytes()).hexdigest(),
       "linked_susfs_symbols":list(SUSFS_SYMBOLS),"root_and_susfs_link":"passed",
       "config_checked":True,"vendor_module_crc_compatible":"unknown",
       "sukisu_manager_runtime":"not_tested","SUSFS_control_api":"not_tested",
       "actual_cmi_boot":"not_tested","flashable":False
    }
    # Source-assembly stage creates a generic "driver only" link report with
    # pre-integration defaults. Replace those booleans only *after* verifying
    # the real AArch64 caller relocations and final linked implementations.
    link_report=res/"kernel-link-verification.json"
    if not link_report.is_file():
        raise RuntimeError("Missing original kernel-link verification report")
    prior=json.loads(link_report.read_text())
    if prior.get("kernel_link")!="passed" or prior.get("aarch64_elf") is not True:
        raise RuntimeError("Kernel link baseline not verified")
    prior.update({
       "sukisu_included":True,"susfs_included":True,
       "actual_ksu_arm64_hook_relocations":"passed",
       "actual_susfs_arm64_hook_relocations":"passed",
       "SUSFS_legacy_prctl":"subset_compiled_not_runtime_tested",
       "vendor_module_crc_compatible":"not_verified",
       "phone_runtime":"not_tested","flashable_package":False})
    link_report.write_text(json.dumps(prior,ensure_ascii=False,indent=2)+"\n")
    manual=res/"manual-hooks-result.json"
    if manual.is_file():
        payload=json.loads(manual.read_text())
        payload["real_arm64_object_relocations"]="passed"
        payload["SUSFS_runtime"]="not_tested"
        manual.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+"\n")
    (res/"cmi-dual-verify.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+"\n")
    print("SukiSU call relocations + real SUSFS ARM64 symbols passed. Not device-safe.")
if __name__=="__main__":
    if len(sys.argv)!=3:raise SystemExit("usage: verify-susfs-hooks.py OUT_DIR RESULTS_DIR")
    verify(Path(sys.argv[1]),Path(sys.argv[2]))
