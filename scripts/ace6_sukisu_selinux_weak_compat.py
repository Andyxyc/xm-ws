#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""OnePlus Ace6 PLQ110 Android16 6.6.118 / pinned SukiSU builtin C95:
make two OPTIONAL SELinux symbol references genuinely weak.

SukiSU selinux_hide.c has a complete internal context_struct_compute_av
implementation and a null-guard for the optional OEM external helper.
The stock OnePlus 6.6.118 SELinux services.c only contains a STATIC
context_struct_compute_av and does not provide the helper names.

This source-pinned edit preserves normal kernel SELinux policy enforcement.
It does not stub out the helper, suppress linker failures or force permissive
mode. The pre-existing null test chooses the internal implementation when
the optional weak reference is unresolved.
"""
from __future__ import annotations
import argparse
import pathlib
import subprocess
import sys
import tempfile

PIN = "c95d6e2c76adb11b0e438e518e32ac4e31f5b1d0"
SELINUX_HIDE_BLOB = "31b2de8fa27c50d7e77677a1ba00c03e525366e9"
REPLACEMENTS = (
    ("extern void security_dump_masked_av_fn(",
     "extern void __weak security_dump_masked_av_fn("),
    ("extern void context_struct_compute_av_fn(",
     "extern void __weak context_struct_compute_av_fn("),
)

def mutate(source: str) -> str:
    for old, new in REPLACEMENTS:
        count=source.count(old)
        if count != 1:
            raise ValueError(f"Pinned optional SELinux helper changed: {old}, found {count}")
        source=source.replace(old,new,1)
    # Require both original fallbacks and the actual algorithm,
    # otherwise refuse to create a candidate kernel.
    assert "static void context_struct_compute_av(" in source, "Internal SELinux policy evaluator absent"
    assert "context_struct_compute_av(policydb, scontext, tcontext, tclass, avd, NULL);" in source
    assert "if ((void *)context_struct_compute_av_fn != NULL)" in source
    assert "if ((void *)security_dump_masked_av_fn != NULL)" in source
    if "selinux_enforcing = 0" in source or "setenforce(0)" in source:
        raise ValueError("Potential SELinux bypass unexpectedly introduced")
    return source

def git(tree: pathlib.Path,*args: str) -> str:
    return subprocess.check_output(["git",*args],cwd=tree,text=True).strip()

def apply(ksu: pathlib.Path) -> None:
    ksu=ksu.resolve()
    if git(ksu,"rev-parse","HEAD") != PIN:
        raise ValueError("Unexpected upstream SukiSU commit")
    rel="kernel/feature/selinux_hide.c"
    if git(ksu,"hash-object",rel) != SELINUX_HIDE_BLOB:
        raise ValueError("Unverified SELinux helper source: refuse ABI modification")
    p=ksu/rel
    text=p.read_text(encoding="utf-8")
    updated=mutate(text)
    if updated.count("extern void __weak") < 2:
        raise ValueError("Weak SELinux symbols not correctly declared")
    p.write_text(updated,encoding="utf-8")
    print("PASS: optional SELinux helper symbols are weak; policy evaluator and guards remain")

def selftest() -> None:
    sample="\n".join((
      "extern void security_dump_masked_av_fn(",
      "extern void context_struct_compute_av_fn(",
      "static void context_struct_compute_av(",
      "if ((void *)context_struct_compute_av_fn != NULL)",
      "context_struct_compute_av(policydb, scontext, tcontext, tclass, avd, NULL);",
      "if ((void *)security_dump_masked_av_fn != NULL)",
    ))
    output=mutate(sample)
    for _,new in REPLACEMENTS:
        assert output.count(new)==1
    for damaged in (
      sample.replace("extern void context_struct_compute_av_fn(",""),
      sample.replace("static void context_struct_compute_av(",""),
      sample.replace("if ((void *)security_dump_masked_av_fn != NULL)",""),
    ):
        try: mutate(damaged)
        except (ValueError,AssertionError): pass
        else: raise AssertionError("Unsafe source layout silently accepted")
    # A missing optional weak symbol must not cause a hard link failure.
    example="""#include <stddef.h>
    extern void __attribute__((weak)) missing_kernel_helper(void);
    static int policy_compute(void) { return 0; }
    int main(void) {
        if ((void*)missing_kernel_helper != NULL) missing_kernel_helper();
        return policy_compute();
    }
    """
    with tempfile.TemporaryDirectory(prefix="ace6_selinux_") as d:
        src=pathlib.Path(d)/"weak_test.c"
        exe=pathlib.Path(d)/"weak_test"
        src.write_text(example)
        cc="cc"
        subprocess.run([cc,"-Werror","-O2",str(src),"-o",str(exe)],check=True)
        subprocess.run([str(exe)],check=True)
    print("PASS: SELinux optional helper source guards, negative tests and weak-link smoke test")

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=["selftest","apply"])
    p.add_argument("sukisu_tree",type=pathlib.Path,nargs="?")
    o=p.parse_args()
    try:
        if o.action=="selftest":
            selftest()
        elif o.sukisu_tree is None:
            p.error("apply requires pinned SukiSU source tree")
        else:
            apply(o.sukisu_tree)
    except (OSError,ValueError,AssertionError,subprocess.CalledProcessError) as ex:
        sys.exit("::error::SukiSU SELinux optional helper compatibility: "+str(ex))
