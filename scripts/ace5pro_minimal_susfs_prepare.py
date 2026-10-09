#!/usr/bin/env python3
"""Conservatively adapt the pinned cctv18 6.6.66 builder for PKR110 testing.

This deliberately remains a **test build**, not proof of runtime stability.
The existing published 6.6.66 source branch retains HMBIRD code expected by
the stock 6.6.66 vendor stack. Optional scheduler patches and other add-ons
are not applied.
"""
from __future__ import annotations

import argparse
import pathlib

BUILDER_COMMIT = "0d90ea459dd5013ba5b1cb2e1ebc8c6d1544d746"
KERNEL_COMMIT = "9a56e8288fc62e2047a142114faeb9467447311d"
SUSFS_COMMIT = "0730de4f5d46ee2997f953101b0f608c0b400b38"
KSU_COMMIT = "70fa0e092a2c81060823f8ae526eac14fdda2930"


def prepare(source: str) -> str:
    s = source

    def one(before: str, after: str, label: str) -> None:
        nonlocal s
        count = s.count(before)
        if count != 1:
            raise RuntimeError(f"Builder drift at {label}: expected one occurrence, got {count}")
        s = s.replace(before, after, 1)

    # Preserve the known bootable version family; pin the source tree to avoid
    # a future force-push changing it mid-build.
    old_clone = (
        "git clone --depth=1 https://github.com/cctv18/"
        "android_kernel_common_oneplus_sm8750 "
        "-b oneplus/sm8750_v_15.0.2_oneplus_13_6.6.66 common"
    )
    new_clone = old_clone + (
        "\n"
        f"test \"$(git -C common rev-parse HEAD)\" = \"{KERNEL_COMMIT}\" || "
        "{ echo 'Kernel source pin changed; refusing build'; exit 40; }"
    )
    one(old_clone, new_clone, "kernel source pin")

    # No unrelated runner environment mutations.
    one("SU apt-mark hold firefox && apt-mark hold libc-bin && apt-mark hold man-db",
        "echo 'Using runner-provided package management without apt holds'",
        "runner package holds")
    one("SU rm -rf /var/lib/man-db/auto-update",
        "echo 'Preserving runner man-db state'", "runner man-db removal")

    # Use a single pinned SukiSU Ultra commit, not the unmaintained BakaSU
    # fallback silently selected by the upstream builder.
    begin = s.index("if [[ $KSU_BRANCH == [yYrR] ]]; then")
    end_mark = 'elif [[ "$KSU_BRANCH" == "n" || "$KSU_BRANCH" == "N" ]]; then'
    end = s.index(end_mark, begin)
    old = s[begin:end]
    replacement = f'''if [[ "$KSU_BRANCH" == "y" || "$KSU_BRANCH" == "Y" ]]; then
  echo ">>> Pinned SukiSU Ultra 40959, minimal SUSFS profile"
  curl -fLSs --retry 3 "https://raw.githubusercontent.com/SukiSU-Ultra/SukiSU-Ultra/{KSU_COMMIT}/kernel/setup.sh" -o /tmp/ace5pro-sukisu-setup.sh
  bash /tmp/ace5pro-sukisu-setup.sh builtin
  git -C KernelSU fetch origin "{KSU_COMMIT}" --depth=1
  git -C KernelSU checkout --detach "{KSU_COMMIT}"
  test "$(git -C KernelSU rev-parse HEAD)" = "{KSU_COMMIT}"

  sed -i 's|^KSU_VERSION     := .*|KSU_VERSION     := 40959|' KernelSU/kernel/Makefile
  sed -i 's|^VERSION_TAG     := .*|VERSION_TAG     := 4.2.0|' KernelSU/kernel/Makefile
  if grep -q '^KSU_VERSION_FULL := ' KernelSU/kernel/Makefile; then
    sed -i 's|^KSU_VERSION_FULL := .*|KSU_VERSION_FULL := v4.2.0-xiaomo@builtin[70fa0e09]|' KernelSU/kernel/Makefile
  fi
  UAPI_FILE=""
  for path in KernelSU/kernel/include/uapi/supercall.h KernelSU/uapi/supercall.h; do
    [ -f "$path" ] && {{ UAPI_FILE="$path"; break; }}
  done
  if [ -n "$UAPI_FILE" ]; then
    CURRENT_UAPI="$(grep -ohE 'KERNEL_SU_UAPI_VERSION[^0-9]*[0-9]+' "$UAPI_FILE" | grep -oE '[0-9]+' | tail -n1 || true)"
    if [ "[object Object]" -lt 5 ]; then
      patch -p1 --forward -d KernelSU < "$GITHUB_WORKSPACE/scripts/ksu_uapi_sync/builtin-uapi5.patch"
    fi
  fi
  bash "$GITHUB_WORKSPACE/scripts/sukisu_compat/apply.sh" KernelSU
  echo 'CONFIG_KSU_FULL_NAME_FORMAT="%TAG_NAME%-%COMMIT_SHA%@xiaomo"' >> ./common/arch/arm64/configs/gki_defconfig
'''
    one(old, replacement, "pin SukiSU branch")

    susfs_clone = (
        "git clone --depth=1 https://github.com/cctv18/susfs4oki.git "
        "susfs4ksu -b oki-android15-6.6"
    )
    one(susfs_clone, susfs_clone + (
        f"\n  test \"$(git -C susfs4ksu rev-parse HEAD)\" = \"{SUSFS_COMMIT}\" "
        "|| { echo 'SUSFS source pin changed; refusing build'; exit 41; }"
    ), "pin SUSFS source")

    # Drop additional unrelated / detection-evasion patch. Keep the SUSFS
    # kernel hook patch itself and require it to apply cleanly.
    one(
        "  wget https://github.com/cctv18/oppo_oplus_realme_sm8650/raw/refs/heads/main/other_patch/69_hide_stuff.patch -O ./common/69_hide_stuff.patch\n",
        "", "remove hide_stuff download",
    )
    one("  patch -p1 -F 3 < 50_add_susfs_in_gki-android15-6.6.patch || true",
        "  patch -p1 -F 0 --forward < 50_add_susfs_in_gki-android15-6.6.patch",
        "require SUSFS hooks to apply")
    one("  patch -p1 -F 3 < 69_hide_stuff.patch || true",
        "  echo 'Extra hide_stuff patch is intentionally disabled'",
        "remove hide_stuff apply")

    # Limit SUSFS to mount/path/kstat/umount support, with no extra spoofing,
    # map rewriting, redirect, or persistent log instrumentation.
    for opt in (
        "CONFIG_KSU_SUSFS_SPOOF_UNAME",
        "CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG",
        "CONFIG_KSU_SUSFS_OPEN_REDIRECT",
        "CONFIG_KSU_SUSFS_SUS_MAP",
        "CONFIG_KSU_SUSFS_ENABLE_LOG",
        "CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS",
    ):
        one(f'  echo "{opt}=y" >> "$DEFCONFIG_FILE"',
            f'  echo "# {opt} is not set" >> "$DEFCONFIG_FILE"',
            f"disable optional {opt}")

    # Preserve vendor/default configs where practical. No custom networking,
    # IO schedulers, compression algorithms, ZRAM or extra security patches.
    for line in (
        'echo "CONFIG_TMPFS_XATTR=y" >> "$DEFCONFIG_FILE"\n',
        'echo "CONFIG_TMPFS_POSIX_ACL=y" >> "$DEFCONFIG_FILE"\n',
        'echo "CONFIG_CC_OPTIMIZE_FOR_PERFORMANCE=y" >> "$DEFCONFIG_FILE"\n',
        'echo "CONFIG_HEADERS_INSTALL=n" >> "$DEFCONFIG_FILE"\n',
    ):
        one(line, "", "remove custom defconfig "+line.split("CONFIG_")[-1][:22])

    start_label = "# 应用 CVE_2026_43499 修复补丁"
    finish_label = "# 仅在启用了 LZ4KD 补丁时添加相关算法支持"
    start = s.index(start_label)
    finish = s.index(finish_label, start)
    one(s[start:finish], "# No additional rtmutex or subsystem modifications.\n\n",
        "remove rtmutex patch")

    # Pin the AnyKernel3 packaging tools too. Only the guarded installer
    # template replaces its shell entrypoint in our packaging step.
    one(
        "git clone https://github.com/cctv18/AnyKernel3 --depth=1",
        "git clone https://github.com/cctv18/AnyKernel3 --depth=1\\n"
        "test \\\"$(git -C AnyKernel3 rev-parse HEAD)\\\" = "
        "\\\"091ee586e1a5d5c1c1c957d48fe7c61638d04dc4\\\" "
        "|| { echo 'AK3 core source changed; aborting'; exit 42; }",
        "pin AnyKernel3 core",
    )

    # Do not bypass errors of source-controlled optional patches, since none
    # are enabled in the preset. Force the clang compile to fail on missing
    # symbols, rather than produce an incomplete KSU/SUSFS Image.
    if "CONFIG_KSU_SUSFS=y" not in s or "CONFIG_HMBIRD_SCHED" in s:
        raise RuntimeError("Unexpected minimal source structure")
    return s


def main() -> None:
    args = argparse.ArgumentParser()
    args.add_argument("builder", type=pathlib.Path)
    p = args.parse_args()
    original = p.builder.read_text(encoding="utf-8")
    updated = prepare(original)
    p.builder.write_text(updated, encoding="utf-8")
    print("Minimal SukiSU40959+SUSFS-only builder prepared. KPM/LZ4/ADIOS/BBG/Net off.")


if __name__ == "__main__":
    main()
