#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Create an audited, deliberately non-flashable AnyKernel3 candidate.

Retain all original upstream AK3 files and the real CMI Image.gz, but replace
both installation entry points with unconditional guards. No phone access.
"""
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

AK3_COMMIT = "020dfeccf9d7e962a48400fc94d3e451df92eead"
ROOT_RUN = 39313741454
ROM = "V12.5.10.0.RJACNXM"
README = """小米 10 Pro（cmi）SukiSU 41023 / MIUI 12.5.10 构建审核包
作者：闲鱼 心中都是莫（xiaomo）

此文件保留真实编译出来的 Image.gz 和 AnyKernel3 目录布局，仅供审核。
该版本的 SUSFS 1.5.5 尚未完成运行时移植，实机启动和 42 个原厂模块的兼容性未通过。
安装入口、anykernel.sh 均会停止，禁止写入分区；不要从压缩包提取 Image 手动刷入。
只有完成 SUSFS 移植、原厂启动与驱动兼容核查、备份/恢复预检并经过实机测试，
才能另行生成刷写候选。当前包不能据此认定为可刷或稳定。
"""
# Review-only stubs stay valid for ordinary Android sh; no calls into any
# partition, mount, Magisk or recovery environment are permitted.
GUARD = '#!/sbin/sh\n' \
        'echo "小米10Pro / cmi：审核包禁止刷写；请勿手动刷入 Image.gz"\n' \
        'exit 1\n'
SOURCE = {"root_run": ROOT_RUN, "rom": ROM, "kernel_version_code": 41023,
          "sukisu_compiled": True, "susfs_compiled": False,
          "boot_partition_write": False, "device_boot_test": False,
          "AK3_commit": AK3_COMMIT}

def sha256(path):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        for block in iter(lambda:f.read(1<<20),b""):h.update(block)
    return h.hexdigest()

def take(base,name):
    hits=[p for p in base.rglob(name) if p.is_file()]
    if len(hits)!=1:raise RuntimeError(f"{name}: expected one file, got {len(hits)}")
    return hits[0]

def check_facts(evidence):
    report=json.loads(take(evidence,"kernel-link-verification.json").read_text())
    root=json.loads(take(evidence,"root-integration.json").read_text())
    hooks=json.loads(take(evidence,"manual-hooks-result.json").read_text())
    if report.get("kernel_link")!="passed" or root.get("sukisu_full_link")!="passed":
        raise RuntimeError("Missing confirmed ARM64 kernel link")
    if hooks.get("final_link")!="passed" or not hooks.get("real_arm64_object_relocations"):
        raise RuntimeError("Missing real manual-hook relocation checks")
    if report.get("susfs_included") is not False:
        raise RuntimeError("This audit candidate expects the non-SUSFS stage only")
    image=take(evidence,"Image")
    zipped=take(evidence,"Image.gz")
    if report.get("sha256",{}).get("Image")!=sha256(image):
        raise RuntimeError("Linked Image hash mismatch")
    if report.get("sha256",{}).get("Image.gz")!=sha256(zipped):
        raise RuntimeError("Compressed Image hash mismatch")
    data=image.read_bytes()
    if len(data)<64 or data[56:60]!=b"ARM\x64" or gzip.decompress(zipped.read_bytes())!=data:
        raise RuntimeError("ARM64 header or compressed image mismatch")
    return report,root,hooks,zipped

def assemble(evidence,ak3,out):
    report,root,hooks,image=check_facts(evidence)
    if not (ak3/"tools/ak3-core.sh").is_file() or not (ak3/"META-INF/com/google/android/update-binary").is_file():
        raise RuntimeError("Incomplete upstream AnyKernel3")
    staging=out/"staging"
    if staging.exists():shutil.rmtree(staging)
    staging.mkdir()
    for item in ak3.iterdir():
        if item.name==".git":continue
        destination=staging/item.name
        if item.is_dir():shutil.copytree(item,destination,symlinks=True)
        elif item.is_file():shutil.copyfile(item,destination)
    shutil.copyfile(image,staging/"Image.gz")
    (staging/"anykernel.sh").write_text(GUARD,encoding="utf-8")
    (staging/"META-INF/com/google/android/update-binary").write_text(GUARD,encoding="utf-8")
    (staging/"README-CMI.txt").write_text(README,encoding="utf-8")
    metadata={**SOURCE,"sha256_image_gz":sha256(image),
              "sha256_upstream_core":sha256(ak3/"tools/ak3-core.sh"),
              "hook_test":"passed", "real_susfs":False}
    (staging/"CMI-MANIFEST.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    for entry in ["anykernel.sh","META-INF/com/google/android/update-binary"]:
        result=subprocess.run(["/bin/sh",str(staging/entry)],text=True,capture_output=True,timeout=10)
        if result.returncode!=1 or "禁止刷写" not in result.stdout:
            raise RuntimeError("Write guard did not fail closed: "+entry)
    package=out/"CMI-SukiSU41023-NoSUSFS-MIUI12510-AK3-AUDIT-NOFLASH.zip"
    if package.exists():package.unlink()
    with zipfile.ZipFile(package,"w",zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in sorted(staging.rglob("*")):
            if p.is_symlink():
                raise RuntimeError("Unexpected symbolic link in candidate: "+str(p))
            if p.is_file():
                z.write(p,p.relative_to(staging).as_posix())
    with zipfile.ZipFile(package) as z:
        assert z.testzip() is None
        for x in ("Image.gz","anykernel.sh","META-INF/com/google/android/update-binary","tools/ak3-core.sh"):
            assert x in z.namelist()
        assert z.read("anykernel.sh")==GUARD.encode()
        assert z.read("META-INF/com/google/android/update-binary")==GUARD.encode()
    (out/"AUDIT-RESULT.json").write_text(json.dumps({**metadata,
        "zip_sha256":sha256(package), "zip_bytes":package.stat().st_size,
        "host_write_guard_checks":2,"zip_crc":"passed",
        "AK3_template_not_modified_in_repo":True},ensure_ascii=False,indent=2)+"\n")
    print("Verified archive structure, genuine ARM64 Image, two blocked installer entries.")
    print("Audit ZIP only. Never flash.")

if __name__=="__main__":
    if len(sys.argv)!=4:raise SystemExit("usage: ak3-audit.py EVIDENCE_DIR AK3_DIR OUT_DIR")
    inp,template,out=[Path(v).resolve() for v in sys.argv[1:]]
    out.mkdir(parents=True,exist_ok=True)
    assemble(inp,template,out)
