#!/usr/bin/env python3
"""CMI driver-baseline source repair and post-link verification.

Integration: xiaomo. Target: the pinned MiCode cmi-r-oss source only.
Preserve the packed union definition, function body and module version checks.
This script does not package or flash a phone image.
"""
import argparse
import difflib
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import tempfile

SOURCE = "drivers/platform/msm/gsi/gsi.c"
SOURCE_BLOB = "367710892263a4c85ac3aa952b08d30d159ad6a5"
OLD = b"static union __packed gsi_channel_scratch __gsi_update_mhi_channel_scratch("
NEW = b"static union gsi_channel_scratch __gsi_update_mhi_channel_scratch("
SOURCE_URL = "https://github.com/MiCode/Xiaomi_Kernel_OpenSource/blob/64b40409431988d060f7484369c8c2d7deca1bb3/" + SOURCE
REQUIRED = ("hdd_sysfs_create_driver_root_obj", "hdd_sysfs_destroy_driver_root_obj", "gsi_write_channel_scratch")


def blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def transform(before):
    if blob(before) != SOURCE_BLOB or before.count(OLD) != 1 or NEW in before:
        raise RuntimeError("GSI source revision changed or repair already applied")
    after = before.replace(OLD, NEW, 1)
    if after.replace(NEW, OLD, 1) != before:
        raise RuntimeError("GSI source round-trip check failed")
    return after


def apply(kernel, results):
    target = kernel / SOURCE
    if not target.resolve(strict=True).is_relative_to(kernel):
        raise RuntimeError("GSI path escapes the selected source tree")
    before = target.read_bytes()
    after = transform(before)
    header = kernel / "include/linux/msm_gsi.h"
    header_before = header.read_bytes()
    if not re.search(rb"union\s+__packed\s+gsi_channel_scratch\s*\{", header_before):
        raise RuntimeError("Packed union declaration needs inspection before repair")
    for invalid in (after, before + b"\n"):
        try:
            transform(invalid)
        except RuntimeError:
            pass
        else:
            raise RuntimeError("Repeated/changed-source rejection test failed")
    patch = "".join(difflib.unified_diff(
        before.decode().splitlines(keepends=True), after.decode().splitlines(keepends=True),
        fromfile="a/" + SOURCE, tofile="b/" + SOURCE))
    (results / "cmi-gsi-version-parser.patch").write_text(patch, encoding="utf-8")
    (results / "gsi.c.before").write_bytes(before)
    (results / "gsi.c.after").write_bytes(after)
    with tempfile.NamedTemporaryFile(dir=target.parent, prefix=".gsi-repair-", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(after)
    try:
        temporary.chmod(target.stat().st_mode & 0o777)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    if header.read_bytes() != header_before or target.read_bytes() != after:
        raise RuntimeError("Source write/readback check failed")
    write_json(results / "gsi-source-repair.json", {
        "source_url": SOURCE_URL, "source_blob": SOURCE_BLOB,
        "before_sha256": hashlib.sha256(before).hexdigest(),
        "after_sha256": hashlib.sha256(after).hexdigest(),
        "packed_union_definition_unchanged": True,
        "edit": "Remove only the redundant packed attribute from the helper return-type use.",
        "source_checks": ["exact_revision", "unique_edit", "round_trip", "repeated_patch_rejected", "changed_source_rejected", "write_readback"],
        "kernel_link": "pending", "phone_runtime": "not_tested"})
    print("GSI 源码修补及回读检查通过；最终符号版本仍须由真实链接核验。")


def verify(out, results):
    config = (out / ".config").read_text()
    for value in ("CONFIG_QCA_CLD_WLAN=y", "CONFIG_MODVERSIONS=y"):
        if value not in config.splitlines():
            raise RuntimeError("Required kernel configuration missing: " + value)
    image = out / "arch/arm64/boot/Image"
    compressed = out / "arch/arm64/boot/Image.gz"
    with image.open("rb") as stream:
        header = stream.read(64)
    if len(header) != 64 or header[56:60] != b"ARM\x64":
        raise RuntimeError("Invalid ARM64 Image header")
    with (out / "vmlinux").open("rb") as stream:
        elf = stream.read(64)
    if len(elf) != 64 or elf[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", elf, 18)[0] != 183:
        raise RuntimeError("vmlinux is not a little-endian AArch64 ELF64")
    h = hashlib.sha256()
    with gzip.open(compressed, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    if h.hexdigest() != digest(image):
        raise RuntimeError("Image.gz does not contain the verified Image")
    selected = {}
    for line in (out / "System.map").read_text().splitlines():
        fields = line.split()
        if len(fields) == 3 and fields[2] in REQUIRED:
            if fields[1] not in ("T", "t") or int(fields[0], 16) == 0:
                raise RuntimeError("Invalid linked function symbol: " + line)
            selected[fields[2]] = line
    if set(selected) != set(REQUIRED):
        raise RuntimeError("Missing linked driver functions: " + repr(set(REQUIRED) - set(selected)))
    versions = []
    for line in (out / "Module.symvers").read_text().splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[1] == "gsi_write_channel_scratch":
            if not re.fullmatch(r"0x[0-9a-fA-F]{8}", fields[0]) or int(fields[0], 16) == 0:
                raise RuntimeError("GSI export has no generated nonzero CRC")
            versions.append(line)
    if len(versions) != 1:
        raise RuntimeError("Expected exactly one generated GSI export version")
    log = (results / "build.log").read_text(errors="replace")
    if "version generation failed" in log:
        raise RuntimeError("Unresolved export-version generation failure remains in build log")
    (results / "linked-driver-symbols.txt").write_text("\n".join(selected.values()) + "\n" + versions[0] + "\n")
    write_json(results / "kernel-link-verification.json", {
        "kernel_link": "passed", "aarch64_elf": True,
        "image_gzip_matches": True, "linked_functions": selected,
        "gsi_generated_symbol_version": versions[0],
        "sha256": {"Image": digest(image), "Image.gz": digest(compressed),
                   "vmlinux": digest(out / "vmlinux"), "Module.symvers": digest(out / "Module.symvers")},
        "sukisu_included": False, "susfs_included": False,
        "flashable_package": False, "phone_runtime": "not_tested"})
    print("整核链接、ARM64 格式、无线函数、GSI 符号版本及压缩一致性核验通过。")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("apply", "verify"))
    parser.add_argument("directory", type=Path)
    parser.add_argument("results", type=Path)
    args = parser.parse_args()
    directory = args.directory.resolve(strict=True)
    results = args.results.resolve(strict=True)
    if args.operation == "apply":
        apply(directory, results)
    else:
        verify(directory, results)


if __name__ == "__main__":
    main()
