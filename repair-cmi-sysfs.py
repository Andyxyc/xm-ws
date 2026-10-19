#!/usr/bin/env python3
"""Repair the pinned MiCode WLAN sysfs preprocessor boundary.

Integration: xiaomo. Keep both original root-object function bodies intact.
The power statistics functions remain gated by WLAN_POWER_DEBUG.
Host tests use instrumented kobjects; they are not phone runtime tests.
"""
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

EXPECTED = {
    "src/wlan_hdd_sysfs.c": "25d6d6a3fec8a0943f074501a0f6f88d255a3da2",
    "inc/wlan_hdd_sysfs.h": "253344f6c8f04ab703c6eeec1eac8045e0dffccd",
    "src/wlan_hdd_main.c": "95cadf6475af7f7a13895cc79eaa8d757a36b8c9",
}
BEGIN = "#ifdef WLAN_POWER_DEBUG\nvoid hdd_sysfs_create_powerstats_interface(void)"
ROOT_BEGIN = "void hdd_sysfs_create_driver_root_obj(void)"
END = "\n#endif\n\n#ifdef WLAN_FEATURE_BEACON_RECEPTION_STATS"
ROOT_NAMES = ("hdd_sysfs_create_driver_root_obj", "hdd_sysfs_destroy_driver_root_obj")
POWER_NAMES = ("hdd_sysfs_create_powerstats_interface", "hdd_sysfs_destroy_powerstats_interface")
PREFIX = r"""
#include <assert.h>
#include <stddef.h>
#include <string.h>
struct kobject { int live; };
struct attribute { int unused; };
static struct { struct attribute attr; } power_stats_attribute;
static struct kobject parent, objects[2];
static struct kobject *kernel_kobj = &parent, *driver_kobject, *wlan_kobject;
static unsigned attempts, releases, failures, files_added, files_removed;
static unsigned fail_at;
#define DRIVER_NAME "wifi"
#define hdd_err(...) ((void)0)
static struct kobject *kobject_create_and_add(const char *name, struct kobject *p)
{
    ++attempts;
    assert(attempts <= 2);
    assert((attempts == 1 && p == kernel_kobj && strcmp(name, DRIVER_NAME) == 0) ||
           (attempts == 2 && p == driver_kobject && strcmp(name, "wlan") == 0));
    if (attempts == fail_at) { ++failures; return NULL; }
    assert(!objects[attempts - 1].live);
    objects[attempts - 1].live = 1;
    return &objects[attempts - 1];
}
static void kobject_put(struct kobject *p)
{
    assert(p && p->live);
    if (p == driver_kobject) assert(!objects[1].live);
    p->live = 0; ++releases;
}
static int sysfs_create_file(struct kobject *p, struct attribute *a)
{
    assert(p == driver_kobject && p && p->live);
    assert(a == &power_stats_attribute.attr);
    ++files_added; return 0;
}
static void sysfs_remove_file(struct kobject *p, struct attribute *a)
{
    assert(p == driver_kobject && p && p->live);
    assert(a == &power_stats_attribute.attr);
    ++files_removed;
}
static void reset(unsigned fail)
{
    assert(!driver_kobject && !wlan_kobject);
    assert(!objects[0].live && !objects[1].live);
    attempts = releases = failures = files_added = files_removed = 0;
    fail_at = fail;
}
"""
TEST = r"""
int main(void)
{
    reset(0);
    hdd_sysfs_create_driver_root_obj();
    assert(attempts == 2 && driver_kobject && wlan_kobject && failures == 0);
#ifdef WLAN_POWER_DEBUG
    hdd_sysfs_create_powerstats_interface();
    hdd_sysfs_destroy_powerstats_interface();
    assert(files_added == 1 && files_removed == 1);
#endif
    hdd_sysfs_destroy_driver_root_obj();
    assert(releases == 2 && !driver_kobject && !wlan_kobject);
    hdd_sysfs_destroy_driver_root_obj();
    assert(releases == 2);

    reset(1);
    hdd_sysfs_create_driver_root_obj();
    assert(attempts == 1 && failures == 1 && releases == 0);
    assert(!driver_kobject && !wlan_kobject);
    hdd_sysfs_destroy_driver_root_obj();
    assert(releases == 0);

    reset(2);
    hdd_sysfs_create_driver_root_obj();
    assert(attempts == 2 && failures == 1 && releases == 1);
    assert(!driver_kobject && !wlan_kobject);
    hdd_sysfs_destroy_driver_root_obj();
    assert(releases == 1);

    reset(0);
    hdd_sysfs_create_driver_root_obj();
    assert(driver_kobject && wlan_kobject && attempts == 2);
    hdd_sysfs_destroy_driver_root_obj();
    assert(releases == 2);

    reset(0);
    hdd_sysfs_create_driver_root_obj();
    hdd_sysfs_destroy_driver_root_obj();
    assert(releases == 2 && failures == 0);
    assert(!objects[0].live && !objects[1].live);
#ifdef WLAN_POWER_DEBUG
    hdd_sysfs_create_powerstats_interface();
    hdd_sysfs_destroy_powerstats_interface();
    assert(files_added == 0 && files_removed == 0);
#endif
    return 0;
}
"""


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def function(text, name):
    match = re.search(r"\bvoid\s+" + name + r"\(void\)\s*\{", text)
    if not match:
        raise RuntimeError("Missing function: " + name)
    pos, depth = match.end(), 1
    while depth and pos < len(text):
        depth += (text[pos] == "{") - (text[pos] == "}")
        pos += 1
    if depth:
        raise RuntimeError("Unbalanced function")
    return text[match.start():pos]


def visible(section, debug):
    args = ["cc", "-E", "-P", "-x", "c"]
    if debug:
        args.append("-DWLAN_POWER_DEBUG=1")
    return subprocess.run(args + ["-"], input=section, text=True,
                          capture_output=True, check=True).stdout


def definitions(text, name):
    return len(re.findall(r"\bvoid\s+" + name + r"\(void\)\s*\{", text))


def main():
    if len(sys.argv) != 3:
        raise SystemExit("usage: repair-cmi-sysfs.py KERNEL_DIRECTORY RESULTS_DIRECTORY")
    kernel = Path(sys.argv[1]).resolve(strict=True)
    results = Path(sys.argv[2]).resolve(strict=True)
    base = kernel / "drivers/staging/qcacld-3.0/core/hdd"
    data = {}
    for name, expected in EXPECTED.items():
        p = base / name
        if not p.resolve(strict=True).is_relative_to(kernel):
            raise RuntimeError("Source path escapes kernel tree")
        data[name] = p.read_bytes()
        if blob(data[name]) != expected:
            raise RuntimeError("Source revision changed or patch already applied: " + name)
    target = base / "src/wlan_hdd_sysfs.c"
    before = data["src/wlan_hdd_sysfs.c"]
    text = before.decode("utf-8")
    if text.count(BEGIN) != 1:
        raise RuntimeError("Unrecognized power-debug conditional start")
    start = text.index(BEGIN)
    if text[start:].count(END) != 1:
        raise RuntimeError("Unrecognized power-debug conditional end")
    end = text.index(END, start) + len("\n#endif")
    section = text[start:end]
    split = section.index(ROOT_BEGIN)
    powers = section[:split].rstrip()
    roots = section[split:-len("\n#endif")].rstrip()
    replacement = powers + "\n#endif /* WLAN_POWER_DEBUG */\n\n" + roots
    for name in ROOT_NAMES + POWER_NAMES:
        if function(section, name) != function(replacement, name):
            raise RuntimeError("Original function body changed: " + name)
    for debug in (False, True):
        old = visible(section, debug)
        new = visible(replacement, debug)
        for name in ROOT_NAMES:
            if definitions(old, name) != int(debug) or definitions(new, name) != 1:
                raise RuntimeError("Root-function visibility regression")
        for name in POWER_NAMES:
            if definitions(old, name) != int(debug) or definitions(new, name) != int(debug):
                raise RuntimeError("Power-statistics guard changed")

    sanitizers = os.environ.get("CMI_HOST_SANITIZERS", "address,undefined")
    if sanitizers not in ("address,undefined", "undefined"):
        raise RuntimeError("Unsupported host sanitizer selection")
    checks = []
    for debug in (False, True):
        label = "debug" if debug else "nondebug"
        # Keep the exact conditional section and original function bodies.
        prefix = PREFIX
        if not debug:
            begin = prefix.index("static int sysfs_create_file")
            finish = prefix.index("static void reset", begin)
            prefix = prefix[:begin] + prefix[finish:]
            prefix = prefix.replace("static struct { struct attribute attr; } power_stats_attribute;\n", "")
        unit = results / ("sysfs-root-test-" + label + ".c")
        binary = results / ("sysfs-root-test-" + label)
        unit.write_text(prefix + replacement + TEST, encoding="utf-8")
        command = ["cc", "-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror",
                   "-fsanitize=" + sanitizers, "-fno-omit-frame-pointer"]
        if debug:
            command.append("-DWLAN_POWER_DEBUG=1")
        subprocess.run(command + [str(unit), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
        checks.append({"configuration": label, "result": "passed",
                       "sanitizers": sanitizers.split(","),
                       "scenarios": ["create_destroy", "repeated_destroy",
                                     "parent_allocation_failure", "child_allocation_failure",
                                     "retry_after_failure", "second_create_destroy_cycle"]})
    after = (text[:start] + replacement + text[end:]).encode("utf-8")
    (results / "wlan_hdd_sysfs.c.before").write_bytes(before)
    (results / "wlan_hdd_sysfs.c.after").write_bytes(after)
    patch = "".join(difflib.unified_diff(
        text.splitlines(keepends=True), after.decode().splitlines(keepends=True),
        fromfile="a/drivers/staging/qcacld-3.0/core/hdd/src/wlan_hdd_sysfs.c",
        tofile="b/drivers/staging/qcacld-3.0/core/hdd/src/wlan_hdd_sysfs.c"))
    (results / "cmi-sysfs-root-guard.patch").write_text(patch, encoding="utf-8")
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".sysfs-", delete=False) as tmp:
        temp = Path(tmp.name)
        tmp.write(after)
    try:
        temp.chmod(target.stat().st_mode & 0o777)
        os.replace(temp, target)
    finally:
        if temp.exists():
            temp.unlink()
    report = {"source_blobs": EXPECTED, "after_sha256": hashlib.sha256(after).hexdigest(),
              "original_missing_symbols_reproduced": True, "function_bodies_preserved": True,
              "preprocessor_configurations": ["WLAN_POWER_DEBUG=off", "WLAN_POWER_DEBUG=on"],
              "host_tests": checks, "kernel_link": "pending", "phone_runtime": "not_tested",
              "MODVERSIONS_changed": False, "Werror_disabled": False,
              "source_url": "https://github.com/MiCode/vendor_qcom_opensource_wlan/tree/89be27c877aa52bf2fb53ca1ced645d7779bd51a"}
    (results / "sysfs-root-check-result.json").write_text(json.dumps(report, indent=2) + "\n")
    print("WLAN sysfs root functions restored; debug/nondebug visibility and host tests passed.")


if __name__ == "__main__":
    main()
