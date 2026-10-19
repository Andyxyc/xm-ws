#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Apply pinned SUSFS 1.5.5 against the reviewed MiCode cmi tree in a disposable checkout.

This first pass does not enable a partly applied security feature. Every
rejected hunk is retained verbatim for porting against the real source.
"""
from pathlib import Path
import hashlib, json, subprocess, shutil, sys

SUSFS_SHA="001e69919c6271f690fd00b17e4c721c9e599152"
SUSFS_PATCH_SHA1="a374b74e3535daa08b331851b6c8d9a27d8edb9e"
EXPECTED_KERNEL="64b40409431988d060f7484369c8c2d7deca1bb3"
FEATURES={"path":False,"mount":False,"kstat":False,"uname":False,"cmdline":False}
def git_blob(data):
    return hashlib.sha1(b"blob "+str(len(data)).encode()+b"\0"+data).hexdigest()

def run(argv, **kwargs):
    return subprocess.run(argv,text=True,capture_output=True,timeout=90,**kwargs)

def inspect(kernel, results):
    target=kernel.parent/"susfs-pinned"
    assert target.is_dir(), "SUSFS source is not present"
    base=run(["git","-C",str(kernel),"rev-parse","HEAD"])
    if base.returncode or base.stdout.strip()!=EXPECTED_KERNEL:
        raise RuntimeError("Kernel baseline not pinned")
    up=run(["git","-C",str(target),"rev-parse","HEAD"])
    if up.returncode or up.stdout.strip()!=SUSFS_SHA:
        raise RuntimeError("SUSFS checkout not pinned")
    patch=target/"kernel_patches/50_add_susfs_in_kernel-4.19.patch"
    if git_blob(patch.read_bytes())!=SUSFS_PATCH_SHA1:
        raise RuntimeError("SUSFS patch hash mismatch")
    original=run(["git","-C",str(kernel),"apply","--check","--verbose",str(patch)])
    (results/"susfs-compat-original-check.log").write_text(original.stdout+original.stderr)
    # Preserve full versioned patch and the original implementation.
    inputs=results/"upstream-susfs"
    inputs.mkdir()
    shutil.copyfile(patch,inputs/"50_add_susfs_in_kernel-4.19.patch")
    for p in ("include/linux/susfs.h","include/linux/susfs_def.h","fs/susfs.c"):
        source=target/"kernel_patches"/p
        shutil.copyfile(source,inputs/source.name)
    # The base may contain unrelated edits from driver/KernelSU preparation.
    # --reject applies unambiguous hunks only, never --3way or fuzzy skips.
    process=run(["git","-C",str(kernel),"apply","--reject","--verbose",str(patch)])
    (results/"susfs-compat-apply-reject.log").write_text(process.stdout+process.stderr)
    rejects=sorted(kernel.rglob("*.rej"))
    rejected_files=[]
    for item in rejects:
        rel=item.relative_to(kernel)
        if not str(item.resolve()).startswith(str(kernel.resolve())+"/"):
            raise RuntimeError("reject outside target")
        dest=results/"rejected-hunks"/rel
        dest.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(item,dest)
        rejected_files.append({"path":str(rel),"sha256":hashlib.sha256(item.read_bytes()).hexdigest(),
                               "hunks":item.read_text(errors="replace").count("@@ ")//2})
    changes=run(["git","-C",str(kernel),"diff","--stat"])
    (results/"susfs-compat-diffstat.txt").write_text(changes.stdout)
    result={"device":"cmi","target_rom":"V12.5.10.0.RJACNXM",
            "susfs_version":"1.5.5","source_commit":SUSFS_SHA,
            "stock_patch_check_exit":original.returncode,
            "partial_apply_exit":process.returncode,
            "rejected_files":rejected_files,"enabled_features":FEATURES,
            "fully_applied":process.returncode==0 and not rejects,
            "runtime_integrated":False,
            "flashable":False,
            "manual_reconcile_needed":bool(rejects)}
    (results/"susfs-port-progress.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    if result["fully_applied"]:
        print("SUSFS 4.19 patch applies to this tree; enablement and kernel link still pending.")
    else:
        print(f"SUSFS requires source reconciliation: {len(rejects)} rejected files.")
        for item in rejected_files:print("REJECT",item["path"])
    # DO NOT turn partial patch into running code.
    return result

if __name__=="__main__":
    if len(sys.argv)!=3:raise SystemExit("usage: susfs-port.py PINNED_KERNEL RESULTS")
    kernel,results=map(lambda s:Path(s).resolve(),sys.argv[1:])
    results.mkdir(parents=True,exist_ok=True)
    inspect(kernel,results)
