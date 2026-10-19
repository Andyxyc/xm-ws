#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Package the separately verified experimental legacy-SUSFS image for audit only.

Uses upstream AnyKernel3 layout and real Image.gz. Both entry points terminate
before any writing. A successful host link is not a verified SUSFS runtime.
"""
from pathlib import Path
import gzip, hashlib, json, shutil, subprocess, sys, zipfile
LABEL="CMI-SukiSU41023-SUSFS155-MIUI12510-AK3-AUDIT-NOFLASH.zip"
GUARD='#'+'!/sbin/sh\n'+'echo "小米10Pro cmi SUSFS试验包：禁止写入设备分区"\n'+'exit 1\n'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def find_one(root,name):
    matches=list(root.rglob(name))
    if len(matches)!=1:raise RuntimeError(f"Expected one {name}, found {len(matches)}")
    return matches[0]
def verify_artifact(root):
    res=json.loads(find_one(root,"susfs-legacy-experiment.json").read_text())
    if res.get("build_result")!="linked" or res.get("flashable") is not False:
        raise RuntimeError("SUSFS experimental integration not successfully linked")
    if res.get("runtime_control_api")!="not_verified":
        raise RuntimeError("Unexpected experimental protocol status")
    needed=set(("susfs_init","susfs_spoof_uname","susfs_set_uname","susfs_spoof_cmdline_or_bootconfig"))
    if not needed.issubset(set(res.get("linked_functions",[]))):
        raise RuntimeError("SUSFS source symbols not all linked")
    config=find_one(root,"kernel.config").read_text()
    if "CONFIG_KSU_SUSFS=y" not in config or "CONFIG_KSU=y" not in config:
        raise RuntimeError("Experimental SUSFS configuration not selected")
    linked=json.loads(find_one(root,"kernel-link-verification.json").read_text())
    # This report covers the verified ARM64 image and standard driver baseline
    if linked.get("kernel_link")!="passed":raise RuntimeError("Kernel link report not passed")
    image=find_one(root,"Image")
    gz=find_one(root,"Image.gz")
    if gzip.decompress(gz.read_bytes())!=image.read_bytes():
        raise RuntimeError("Image gzip content differs from compiled raw ARM64 Image")
    if image.read_bytes()[56:60]!=b"ARM\x64":
        raise RuntimeError("Missing real ARM64 boot header magic")
    for name,p in (("Image",image),("Image.gz",gz)):
        if linked.get("sha256",{}).get(name)!=digest(p):
            raise RuntimeError("Image SHA mismatch vs build report "+name)
    return res,linked,gz
def package(evidence,anykernel,out):
    res,linked,image=verify_artifact(evidence)
    if not (anykernel/"tools/ak3-core.sh").is_file():
        raise RuntimeError("AK3 core absent")
    stage=out/"staging"
    if stage.exists():shutil.rmtree(stage)
    stage.mkdir(parents=True)
    for item in anykernel.iterdir():
        if item.name==".git":continue
        p=stage/item.name
        if item.is_dir():shutil.copytree(item,p,symlinks=True)
        elif item.is_file():shutil.copyfile(item,p)
    shutil.copyfile(image,stage/"Image.gz")
    for path in ("anykernel.sh","META-INF/com/google/android/update-binary"):
        fp=stage/path
        fp.write_text(GUARD,encoding="utf-8")
        check=subprocess.run(["/bin/sh",str(fp)],capture_output=True,text=True,timeout=10)
        if check.returncode!=1 or "禁止写入" not in check.stdout:
            raise RuntimeError("Safety guard not enforced for "+path)
    (stage/"README-CMI.txt").write_text(
        "小米10 Pro（cmi）SukiSU 41023 + SUSFS 1.5.5（NON-GKI）\n"
        "作者：闲鱼 心中都是莫（xiaomo）\n"
        "真实编译的实验内核，仅供源代码与结构审核，禁止刷写。\n"
        "SUSFS 旧版 userspace 控制接口、新版管理器兼容性、原厂驱动和实机启动未验证。\n"
        "安装入口拒绝写入；手动提取内核刷写同样不安全。\n",encoding="utf-8")
    (stage/"CMI-SUSFS-REPORT.json").write_text(json.dumps(res,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    zpath=out/LABEL
    if zpath.exists():zpath.unlink()
    with zipfile.ZipFile(zpath,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for path in sorted(stage.rglob("*")):
            if path.is_symlink():raise RuntimeError("Symlink in audited ZIP input")
            if path.is_file():z.write(path,path.relative_to(stage).as_posix())
    with zipfile.ZipFile(zpath) as z:
        if z.testzip():raise RuntimeError("ZIP CRC failed")
        for name in ("Image.gz","tools/ak3-core.sh","anykernel.sh",
                     "META-INF/com/google/android/update-binary"):
            if name not in z.namelist():raise RuntimeError("Missing AK3 member "+name)
        assert z.read("anykernel.sh")==GUARD.encode()
        assert z.read("META-INF/com/google/android/update-binary")==GUARD.encode()
    result={"file":LABEL,"sha256":digest(zpath),"bytes":zpath.stat().st_size,
            "variant":"SukiSU+SUSFS1.5.5","integration":"experimental linked",
            "AK3_guard_checks":2,"zip_integrity":"passed",
            "boot_test":"not_performed","flashable":False}
    (out/"AUDIT-RESULT.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print("SUSFS experimental candidate ZIP audited; hard-blocked from flashing.")
if __name__=="__main__":
    if len(sys.argv)!=4:raise SystemExit("usage: ak3-susfs-audit.py EVIDENCE_DIR ANYKERNEL_DIR OUT_DIR")
    e,ak3,out=map(lambda s:Path(s).resolve(),sys.argv[1:]);out.mkdir(parents=True,exist_ok=True)
    package(e,ak3,out)
