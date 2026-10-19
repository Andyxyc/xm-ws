#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Controlled legacy SUSFS 1.5.5 compile experiment for MiCode cmi.
No unreviewed v2 function aliases, no device writes, no claim of runtime success.
"""
from pathlib import Path
import hashlib, json, re, shutil, sys
REJECTS={"fs/namei.c.rej","fs/notify/fdinfo.c.rej","fs/proc/task_mmu.c.rej",
         "fs/readdir.c.rej","include/linux/mount.h.rej","include/linux/sched.h.rej"}
def replace(path,old,new):
    s=path.read_text()
    if s.count(old)!=1:raise RuntimeError(f"{path}: expected one anchor, got {s.count(old)}")
    path.write_text(s.replace(old,new,1))
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def apply(k,r):
    from importlib.machinery import SourceFileLoader
    legacy=SourceFileLoader("susfsbase",str(Path(__file__).with_name("susfs-port.py"))).load_module()
    state=legacy.inspect(k,r)
    observed={x["path"] for x in state["rejected_files"]}
    if observed!=REJECTS:raise RuntimeError("Unreviewed patch reject set "+repr(observed))
    p=k/"fs/namei.c"
    old=("static inline int may_create(struct vfsmount *mnt, struct inode *dir, struct dentry *child)\n"
         "{\n\tstruct user_namespace *s_user_ns;\n\taudit_inode_child(dir, child, AUDIT_TYPE_CHILD_CREATE);\n")
    addition=("#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n"
       "\tif (child->d_inode && unlikely(child->d_inode->i_state & INODE_STATE_SUS_PATH) &&\n"
       "\t    likely(current->susfs_task_state & TASK_STRUCT_NON_ROOT_USER_APP_PROC)) {\n"
       "\t\tint error = inode_permission2(mnt, dir, MAY_WRITE | MAY_EXEC);\n"
       "\t\tif (error) return error;\n\t\treturn -ENOENT;\n\t}\n#endif\n")
    replace(p,old,old+addition)
    p=k/"fs/proc/task_mmu.c"
    replace(p,"#include <linux/mm_inline.h>\n#include <linux/ctype.h>\n",
            "#include <linux/mm_inline.h>\n#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT\n"
            "#include <linux/susfs_def.h>\n#endif\n#include <linux/ctype.h>\n")
    p=k/"fs/readdir.c"
    replace(p,"\tcompat_ulong_t d_ino;\n\n\tif (buf->result)\n\t\treturn -EINVAL;\n\td_ino = ino;\n",
            "\tcompat_ulong_t d_ino;\n\n\tif (buf->result)\n\t\treturn -EINVAL;\n"
            "#ifdef CONFIG_KSU_SUSFS_SUS_PATH\n"
            "\tif (likely(current->susfs_task_state & TASK_STRUCT_NON_ROOT_USER_APP_PROC) &&\n"
            "\t    susfs_sus_ino_for_filldir64(ino)) return 0;\n#endif\n\td_ino = ino;\n")
    p=k/"include/linux/mount.h"
    replace(p,"\tint mnt_flags;\n\tvoid *data;\n} __randomize_layout;\n",
            "\tint mnt_flags;\n#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n"
            "\tu64 susfs_mnt_id_backup;\n#endif\n\tvoid *data;\n} __randomize_layout;\n")
    p=k/"include/linux/sched.h"
    old=("\t * New fields for task_struct should be added above here, so that\n"
         "\t * they are included in the randomized portion of task_struct.\n"
         "\t */\n\trandomized_struct_fields_end\n")
    new=old.replace("\trandomized_struct_fields_end\n",
        "#if defined(CONFIG_KSU_SUSFS_SUS_PATH) || defined(CONFIG_KSU_SUSFS_SUS_MOUNT)\n"
        "\tu64 susfs_task_state;\n#endif\n"
        "#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT\n\tu64 susfs_last_fake_mnt_id;\n#endif\n"
        "\trandomized_struct_fields_end\n")
    replace(p,old,new)
    # Skip upstream fdinfo fragment: references an unavailable local and changes inotify semantics.
    # Disable mount hiding; do not silently bypass a real security requirement.
    up=k.parent/"susfs-pinned/kernel_patches"
    for rel in ("fs/susfs.c","include/linux/susfs.h","include/linux/susfs_def.h"):
        dest=k/rel
        if dest.exists():raise RuntimeError("Existing SUSFS target "+rel)
        shutil.copyfile(up/rel,dest)
    su=k/"drivers/kernelsu"
    adjusted=[]
    for p in su.rglob("*"):
        if not p.is_file() or p.suffix not in (".h",".c"):continue
        before=p.read_text(errors="replace")
        after=re.sub(r"\bCONFIG_KSU_SUSFS\b","CONFIG_CMI_SUSFS_V2",before)
        if after!=before:
            p.write_text(after)
            adjusted.append(str(p.relative_to(su)))
    p=su/"ksu.c"
    replace(p,"    ksu_feature_init();\n",
      "#if defined(CONFIG_KSU_SUSFS) && !defined(CONFIG_CMI_SUSFS_V2)\n"
      "    susfs_init();\n#endif\n    ksu_feature_init();\n")
    p=su/"ksu.c"
    replace(p,'#include "kernel_includes.h"\n',
            '#include "kernel_includes.h"\n#ifdef CONFIG_KSU_SUSFS\n#include <linux/susfs.h>\n#endif\n')
    report={"rom":"V12.5.10.0.RJACNXM","device":"cmi","susfs":"1.5.5 NON-GKI",
      "rejected_original_hunks":sorted(observed),
      "unsafe_fdinfo_hunk_skipped":True,
      "actual_legacy_sources_sha256":{x:digest(k/x) for x in ("fs/susfs.c","include/linux/susfs.h","include/linux/susfs_def.h")},
      "sukisu_newer_only_code_gated":adjusted,
      "compile_features":["SPOOF_UNAME","SPOOF_CMDLINE_OR_BOOTCONFIG","ENABLE_LOG"],
      "disabled_features":["SUS_PATH","SUS_MOUNT","SUS_KSTAT","OPEN_REDIRECT","SUS_MAP"],
      "build_result":"pending","runtime_control_api":"not_verified",
      "stock_vendor_abi":"not_verified","flashable":False}
    (r/"susfs-legacy-experiment.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print("CMI 4.19 legacy SUSFS code installed for compiler test. No writable image.")
def verify(out,r):
    cfg=(out/".config").read_text()
    for flag in ("CONFIG_KSU=y","CONFIG_KSU_SUSFS=y","CONFIG_KSU_SUSFS_SPOOF_UNAME=y",
                 "CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG=y"):
        if flag not in cfg.splitlines():raise RuntimeError("Missing required config "+flag)
    for name in ("SUS_PATH","SUS_MOUNT","SUS_KSTAT","OPEN_REDIRECT","SUS_MAP"):
        if re.search(r"^CONFIG_KSU_SUSFS_"+name+r"=[ym]$",cfg,re.M):
            raise RuntimeError("Unreviewed SUSFS feature active "+name)
    symbols=(out/"System.map").read_text()
    names=("susfs_init","susfs_spoof_uname","susfs_set_uname","susfs_spoof_cmdline_or_bootconfig")
    for name in names:
        if not re.search(r"\b[Tt]\s+"+name+r"$",symbols,re.M):
            raise RuntimeError("Unlinked SUSFS function "+name)
    p=r/"susfs-legacy-experiment.json";result=json.loads(p.read_text())
    result["build_result"]="linked";result["linked_functions"]=list(names)
    p.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print("Experimental SUSFS core symbols linked, but userspace control and device boot unverified.")
if __name__=="__main__":
    if len(sys.argv)!=4 or sys.argv[1] not in ("apply","verify"):
        raise SystemExit("usage: susfs-port-compile.py apply|verify KERNEL_OR_OUT RESULTS")
    a,b=Path(sys.argv[2]).resolve(),Path(sys.argv[3]).resolve()
    b.mkdir(parents=True,exist_ok=True)
    (apply if sys.argv[1]=="apply" else verify)(a,b)
