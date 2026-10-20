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
    # Preserve the vendor kernel's LSM prctl checks and legacy userspace ABI.
    # The bridge is part of this experimental 4.19 build, never the A build.
    sysc = k/"kernel/sys.c"
    text = sysc.read_text()
    signature=("SYSCALL_DEFINE5(prctl, int, option, unsigned long, arg2, unsigned long, arg3,\n"
               "\t\tunsigned long, arg4, unsigned long, arg5)\n")
    entry=("#if defined(CONFIG_KSU) && defined(CONFIG_KSU_SUSFS)\n"
           "extern long cmi_susfs_legacy_prctl(unsigned long, unsigned long,\n"
           "                                    unsigned long, unsigned long);\n"
           "#endif\n")
    lsm=("\terror = security_task_prctl(option, arg2, arg3, arg4, arg5);\n"
         "\tif (error != -ENOSYS)\n\t\treturn error;\n")
    invoke=("\n#if defined(CONFIG_KSU) && defined(CONFIG_KSU_SUSFS)\n"
            "\tif (option == 0xDEADBEEF)\n"
            "\t\treturn cmi_susfs_legacy_prctl(arg2, arg3, arg4, arg5);\n"
            "#endif\n")
    if text.count(signature)!=1 or text.count(lsm)!=1 or "cmi_susfs_legacy_prctl" in text:
        raise RuntimeError("Legacy prctl source anchors changed or patch already applied")
    sysc.write_text(text.replace(signature,entry+signature,1).replace(lsm,lsm+invoke,1))
    makefile=k/"fs/Makefile"
    replace(makefile,"obj-$(CONFIG_KSU_SUSFS) += susfs.o\n",
            "obj-$(CONFIG_KSU_SUSFS) += susfs.o cmi_susfs_legacy_prctl.o\n")
    bridge=r'''// SPDX-License-Identifier: GPL-2.0-only
// cmi 4.19 ONLY: opt-in, root-only SUSFS 1.5.5 prctl transport.
// This intentionally does not enable the unsupported SUSFS hiding features.
#include <linux/capability.h>
#include <linux/cred.h>
#include <linux/errno.h>
#include <linux/susfs.h>
#include <linux/susfs_def.h>
#include <linux/uaccess.h>
#include <linux/compiler.h>

#ifdef CONFIG_KSU_SUSFS_ENABLE_LOG
extern bool susfs_is_log_enabled;
#endif

long cmi_susfs_legacy_prctl(unsigned long command, unsigned long arg3,
                           unsigned long arg4, unsigned long arg5)
{
    int result = -1; /* Legacy CLI uses this output for unsupported commands. */

    if (current_uid().val != 0 || !capable(CAP_SYS_ADMIN))
        return -EPERM;
    if (!arg5 || arg4)
        return -EINVAL;

    switch (command) {
#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME
    case CMD_SUSFS_SET_UNAME:
        result = susfs_set_uname((struct st_susfs_uname __user *)arg3);
        break;
#endif
#ifdef CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
    case CMD_SUSFS_SET_CMDLINE_OR_BOOTCONFIG:
        result = susfs_set_cmdline_or_bootconfig((char __user *)arg3);
        break;
#endif
#ifdef CONFIG_KSU_SUSFS_ENABLE_LOG
    case CMD_SUSFS_ENABLE_LOG:
        if (arg3 > 1)
            result = -EINVAL;
        else {
            WRITE_ONCE(susfs_is_log_enabled, arg3 != 0);
            result = 0;
        }
        break;
#endif
    case CMD_SUSFS_SHOW_VERSION:
        result = copy_to_user((void __user *)arg3, SUSFS_VERSION,
                              sizeof(SUSFS_VERSION)) ? -EFAULT : 0;
        break;
    case CMD_SUSFS_SHOW_VARIANT:
        result = copy_to_user((void __user *)arg3, SUSFS_VARIANT,
                              sizeof(SUSFS_VARIANT)) ? -EFAULT : 0;
        break;
    default:
        break; /* Unknown or disabled operation: never silently succeed. */
    }
    return put_user(result, (int __user *)arg5) ? -EFAULT : 0;
}
'''
    (k/"fs/cmi_susfs_legacy_prctl.c").write_text(bridge)
    (r/"cmi-susfs-legacy-prctl.patch").write_text(
        "Reviewed, guarded source edits:\n"
        "kernel/sys.c: prctl after LSM check, root-only SUSFS 1.5.5 ABI\n"
        "fs/Makefile: build cmi_susfs_legacy_prctl.o with CONFIG_KSU_SUSFS\n"
        "fs/cmi_susfs_legacy_prctl.c: real uname/cmdline/log operations; no fake hiding\n")
    report={"rom":"V12.5.10.0.RJACNXM","device":"cmi","susfs":"1.5.5 NON-GKI",
      "rejected_original_hunks":sorted(observed),
      "unsafe_fdinfo_hunk_skipped":True,
      "actual_legacy_sources_sha256":{x:digest(k/x) for x in ("fs/susfs.c","include/linux/susfs.h","include/linux/susfs_def.h")},
      "sukisu_newer_only_code_gated":adjusted,
      "compile_features":["SPOOF_UNAME","SPOOF_CMDLINE_OR_BOOTCONFIG","ENABLE_LOG"],
      "disabled_features":["SUS_PATH","SUS_MOUNT","SUS_KSTAT","OPEN_REDIRECT","SUS_MAP"],
      "build_result":"pending","runtime_control_api":"not_verified",
      "stock_vendor_abi":"not_verified","flashable":False,"legacy_prctl_bridge":"pending"}
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
    # Both callers must have genuine ARM64 unresolved relocations, and final
    # vmlinux must define the bridge; source text matches alone are insufficient.
    import subprocess
    readnm=lambda path:subprocess.run(
        ["nm","-u",str(path)],capture_output=True,text=True,check=True,timeout=30).stdout
    if not re.search(r"\bU\s+cmi_susfs_legacy_prctl$",readnm(out/"kernel/sys.o"),re.M):
        raise RuntimeError("No kernel/sys.o legacy prctl relocation")
    bridgeobj=out/"fs/cmi_susfs_legacy_prctl.o"
    bridge_symbols=readnm(bridgeobj)
    for sym in ("susfs_set_uname","susfs_set_cmdline_or_bootconfig"):
        if not re.search(r"\bU\s+"+sym+r"$",bridge_symbols,re.M):
            raise RuntimeError("No real legacy bridge relocation to "+sym)
    if not re.search(r"\b[Tt]\s+cmi_susfs_legacy_prctl$",symbols,re.M):
        raise RuntimeError("Legacy prctl bridge missing from final vmlinux")
    p=r/"susfs-legacy-experiment.json";result=json.loads(p.read_text())
    result["build_result"]="linked";result["linked_functions"]=list(names);result["legacy_prctl_bridge"]="arm64_objects_and_final_link_passed_runtime_not_tested"
    p.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print("Experimental SUSFS core symbols linked, but userspace control and device boot unverified.")
if __name__=="__main__":
    if len(sys.argv)!=4 or sys.argv[1] not in ("apply","verify"):
        raise SystemExit("usage: susfs-port-compile.py apply|verify KERNEL_OR_OUT RESULTS")
    a,b=Path(sys.argv[2]).resolve(),Path(sys.argv[3]).resolve()
    b.mkdir(parents=True,exist_ok=True)
    (apply if sys.argv[1]=="apply" else verify)(a,b)
