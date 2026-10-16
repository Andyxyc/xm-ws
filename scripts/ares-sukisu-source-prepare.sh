#!/usr/bin/env bash
# Redmi K40 Gaming Enhanced (ares, MediaTek MT6893) only.
# Experimental SukiSU Ultra source integration into ares Linux 4.14.336.
# Original kernel: khanra17/kernel_xiaomi_mt6893, GPL-2.0.
# No flashing, rebooting, data writes, or device access.
set -euo pipefail
SRC="$1"
test -n "$SRC" || { echo "Usage: $0 /path/to/ares/source"; exit 2; }
WS="$(cd "$(dirname "$0")/.." && pwd)"
KERNEL_PIN="51493fdd25984d3c2f7c6bd1bcaec9775430f4c0"
SUKISU_PIN="c95d6e2c76adb11b0e438e518e32ac4e31f5b1d0"
fail() { echo "::error::ARES: $*" >&2; exit 1; }
note() { echo "[ares/MT6893] $*"; }
test -f "$SRC/Makefile" || fail "Kernel source missing"
test "$(git -C "$SRC" rev-parse HEAD)" = "$KERNEL_PIN" || fail "Wrong source revision"
grep -qxF 'VERSION = 4' "$SRC/Makefile" || fail "Not Linux4.14"
grep -qxF 'PATCHLEVEL = 14' "$SRC/Makefile" || fail "Not Linux4.14"
grep -qxF 'SUBLEVEL = 336' "$SRC/Makefile" || fail "Not expected 4.14.336 source"
test -s "$SRC/arch/arm64/configs/ares_defconfig" || fail "ares defconfig missing"
grep -qF 'CONFIG_ARCH_MTK_PROJECT="k6893v1_64"' "$SRC/arch/arm64/configs/ares_defconfig" || fail "MT6893 board config mismatch"
grep -qxF 'CONFIG_KSU_SUSFS=y' "$SRC/arch/arm64/configs/ares_defconfig" || fail "SUSFS vendor hooks not integrated"
grep -qF 'obj-$(CONFIG_KSU_SUSFS) += susfs.o' "$SRC/fs/Makefile" || fail "SUSFS filesystem integration missing"
test -L "$SRC/drivers/kernelsu" || fail "Expected community KernelSU symlink"
test "$(readlink "$SRC/drivers/kernelsu")" = "../KernelSU/kernel" || fail "Unexpected KernelSU symlink"
test ! -e "$SRC/KernelSU/kernel" || fail "KernelSU already populated; refusing overwrite"
if [ -d "$SRC/KernelSU" ]; then
  test -z "$(find "$SRC/KernelSU" -mindepth 1 -maxdepth 1 -print -quit)" || fail "Unexpected submodule contents"
  rmdir "$SRC/KernelSU" || fail "Could not remove empty submodule directory"
fi
note "Installing pinned official SukiSU builtin"
git clone --quiet --single-branch --branch builtin --depth=1 \
  https://github.com/SukiSU-Ultra/SukiSU-Ultra.git "$SRC/KernelSU"
test "$(git -C "$SRC/KernelSU" rev-parse HEAD)" = "$SUKISU_PIN" || fail "SukiSU source commit changed"
python3 "$WS/scripts/pad2pro_sukisu40996_compat.py" apply "$SRC/KernelSU" || fail "SukiSU manager/KPM protocol mismatch"
python3 "$WS/scripts/ares-sukisu414-compat.py" apply "$SRC/KernelSU" || fail "Linux4.14 compatibility patch mismatch"
bash "$WS/scripts/ace5pro_fix_uapi5.sh" "$SRC/KernelSU" || fail "SukiSU UAPI5 backport failed"
if grep -qF '#include "arch.h"' "$SRC/KernelSU/kernel/kernel_includes.h" &&
   [ ! -f "$SRC/KernelSU/kernel/include/arch.h" ]; then
  test -s "$WS/scripts/sukisu_compat/arch.h" || fail "Missing pinned arch.h"
  install -m 0644 "$WS/scripts/sukisu_compat/arch.h" "$SRC/KernelSU/kernel/include/arch.h"
fi
python3 - "$SRC/KernelSU/kernel/Makefile" <<'PY'
import pathlib,re,sys
p=pathlib.Path(sys.argv[1]); s=p.read_text()
for key,new in (("KSU_VERSION","40996"),("VERSION_TAG","4.2.1")):
    pat=rf'^{key}\s*:=.*$'
    s,n=re.subn(pat,f'{key} := {new}',s,count=1,flags=re.M)
    if n!=1: raise SystemExit(f"Unexpected source {key} version declaration")
p.write_text(s)
PY
grep -q 'KERNEL_SU_UAPI_VERSION, 5' "$SRC/KernelSU/kernel/include/uapi/supercall.h" || fail "UAPI5 missing"
grep -q 'config KPM' "$SRC/KernelSU/kernel/Kconfig" || fail "KPM not supported"
grep -q 'config KSU_SUSFS' "$SRC/KernelSU/kernel/Kconfig" || fail "SUSFS Kconfig absent"
DEFCONFIG="$SRC/arch/arm64/configs/ares_defconfig"
"$SRC/scripts/config" --file "$DEFCONFIG" \
  --enable KSU \
  --enable KSU_SUSFS \
  --enable KSU_SUSFS_SUS_PATH \
  --enable KSU_SUSFS_SUS_MOUNT \
  --enable KSU_SUSFS_SUS_KSTAT \
  --enable KPM \
  --enable KALLSYMS \
  --enable KALLSYMS_ALL \
  --disable KSU_SUSFS_SPOOF_UNAME \
  --disable KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG \
  --disable KSU_SUSFS_OPEN_REDIRECT \
  --disable KSU_SUSFS_SUS_MAP \
  --disable KSU_SUSFS_ENABLE_LOG \
  --disable KSU_FEATURE_ADBROOT
test -s "$DEFCONFIG" || fail "No ares config"
for key in CONFIG_KSU CONFIG_KSU_SUSFS CONFIG_KPM CONFIG_KALLSYMS CONFIG_KALLSYMS_ALL; do
  grep -qxF "$key=y" "$DEFCONFIG" || fail "Required feature not requested: $key"
done
cat > "$SRC/ARES_SOURCE_PROVENANCE.txt" <<EOF
HARDWARE=Redmi_K40_Gaming_Enhanced_ares
SOC=MediaTek_Dimensity_1200_MT6893
OS_TARGET=HyperOS1_Android13
KERNEL_SOURCE=https://github.com/khanra17/kernel_xiaomi_mt6893
KERNEL_SOURCE_PIN=$KERNEL_PIN
KERNEL_VERSION=4.14.336
XIAOMI_OFFICIAL_ARES_BASE=4.14.186
SUKISU=https://github.com/SukiSU-Ultra/SukiSU-Ultra
SUKISU_BUILTIN_PIN=$SUKISU_PIN
SUKISU_EXPECTED_DRIVER_VERSION=40996
SUKISU_UAPI=5
KPM=enabled_in_config
SUSFS=enabled_in_kernel_source
ACTUAL_HYPEROS1_BOOT_ABI=UNVERIFIED
DEVICE_BOOT_WIFI_BT=NOT_TESTED
AUTOMATIC_REBOOT=NO
AUTHOR=闲心中都是莫
EOF
note "Source configured. Boot/ROM compatibility is not yet verified. No device touched."
