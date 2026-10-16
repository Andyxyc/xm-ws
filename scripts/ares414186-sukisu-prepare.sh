#!/usr/bin/env bash
# Redmi K40 Gaming Enhanced (ares, MT6893) only.
# Rebuild 4.14.186 ares vendor tree with pinned official SukiSU.
# This script changes only a disposable CI source checkout, never a device.
set -euo pipefail
test "$#" -eq 1 || { echo "usage: $0 /path/to/ares/source" >&2; exit 2; }
SRC="$1"
WS="$(cd "$(dirname "$0")/.." && pwd)"
test -z "$GITHUB_WORKSPACE" || WS="$GITHUB_WORKSPACE"
VENDOR_SHA="72ae382f8be601f6e1b6606d9eba6084e7c54efa"
SUKI_SHA="c95d6e2c76adb11b0e438e518e32ac4e31f5b1d0"
die() { printf '::error::K40 Gaming (ares): %s\n' "$*" >&2; exit 1; }

test -f "$SRC/Makefile" || die "Missing ares kernel source"
test "$(git -C "$SRC" rev-parse HEAD)" = "$VENDOR_SHA" || die "Unexpected vendor tree commit"
for pair in 'VERSION = 4' 'PATCHLEVEL = 14' 'SUBLEVEL = 186'; do
    grep -qxF "$pair" "$SRC/Makefile" || die "Wrong kernel baseline: $pair"
done
# These two warning-demotion options were added for a newer Clang release.
# LLVM15/18 treats them as unknown -Werror flags, which makes Kbuild's
# cc-option test falsely report that -fstack-protector-strong is unsupported.
# Remove ONLY those unsupported optional warning controls, never the
# requested stack protector or the actual -Werror compile safety settings.
python3 - "$SRC/Makefile" <<'PY'
import pathlib,sys
p=pathlib.Path(sys.argv[1])
s=p.read_text()
flags=[
    'KBUILD_CFLAGS   += -Wno-error=default-const-init-var-unsafe\n',
    'KBUILD_CFLAGS   += -Wno-error=default-const-init-field-unsafe\n',
]
for line in flags:
    if s.count(line) != 1:
        raise SystemExit('Expected source warning option not found exactly once: '+line.strip())
    s=s.replace(line,'',1)
p.write_text(s)
print('PASS: removed only 2 unsupported new-Clang warning demotions, strong stack protector preserved')
PY
DEF="$SRC/arch/arm64/configs/ares_user_defconfig"
test -s "$DEF" || die "Missing ares device defconfig"
for key in \
    'CONFIG_ARCH_MTK_PROJECT="k6893v1_64"' \
    'CONFIG_MTK_COMBO_WIFI=y' \
    'CONFIG_MTK_COMBO_BT=y' \
    'CONFIG_MTK_COMBO_CHIP_CONSYS_6893=y'; do
    grep -qxF "$key" "$DEF" || die "Unexpected WiFi/Bluetooth vendor configuration: $key"
done

test -L "$SRC/drivers/kernelsu" || die "Vendor tree has no expected KernelSU symlink"
test "$(readlink "$SRC/drivers/kernelsu")" = "../KernelSU/kernel" || die "Different KernelSU integration; review required"
test -d "$SRC/KernelSU/kernel" || die "Expected original ReSukiSU source to remain as reference"
test ! -e "$SRC/SukiSUOfficial" || die "Duplicate SukiSUOfficial dir"
# Only unlink the symlink in a disposable checkout, NOT original ReSukiSU.
unlink "$SRC/drivers/kernelsu"
git clone --quiet --depth=1 --single-branch --branch builtin \
    https://github.com/SukiSU-Ultra/SukiSU-Ultra.git "$SRC/SukiSUOfficial"
test "$(git -C "$SRC/SukiSUOfficial" rev-parse HEAD)" = "$SUKI_SHA" || die "Official SukiSU source changed"
ln -s ../SukiSUOfficial/kernel "$SRC/drivers/kernelsu"
test -f "$SRC/drivers/kernelsu/Kconfig" || die "Official SukiSU wiring failed"

# Exact-source fixes from previously reviewed upstream 40996 interfaces.
python3 "$WS/scripts/pad2pro_sukisu40996_compat.py" apply "$SRC/SukiSUOfficial" || die "SukiSU manager/KPM protocol collision"
python3 "$WS/scripts/ares-sukisu414-compat.py" apply "$SRC/SukiSUOfficial" || die "4.14 source compatibility"
bash "$WS/scripts/ace5pro_fix_uapi5.sh" "$SRC/SukiSUOfficial" || die "UAPI5 userspace support mismatch"
if grep -qF '#include "arch.h"' "$SRC/SukiSUOfficial/kernel/kernel_includes.h" &&
   [ ! -e "$SRC/SukiSUOfficial/kernel/include/arch.h" ]; then
    test -s "$WS/scripts/sukisu_compat/arch.h" || die "Pinned arch.h missing"
    install -m 0644 "$WS/scripts/sukisu_compat/arch.h" "$SRC/SukiSUOfficial/kernel/include/arch.h"
fi

python3 - "$SRC/SukiSUOfficial/kernel/Makefile" <<'PY'
import pathlib, re, sys
path = pathlib.Path(sys.argv[1])
s = path.read_text()
actual = re.findall(r"^VERSION_BASE\s*:=\s*(\d+)$", s, re.M)
assert len(actual) == 1 and actual[0] == "40000", "Unexpected upstream version formula"
s, n = re.subn(r"^KSU_VERSION\s*:=.*$", "KSU_VERSION := 40996", s, count=1, flags=re.M)
assert n == 1, "KSU_VERSION moved upstream"
path.write_text(s)
PY

"$SRC/scripts/config" --file "$DEF" \
    --enable KSU \
    --enable KPM \
    --enable KSU_SUSFS \
    --enable KSU_SUSFS_SUS_PATH \
    --enable KSU_SUSFS_SUS_MOUNT \
    --enable KSU_SUSFS_SUS_KSTAT \
    --enable KALLSYMS \
    --enable KALLSYMS_ALL \
    --disable KSU_DEBUG \
    --disable KSU_SUSFS_SPOOF_UNAME \
    --disable KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG \
    --disable KSU_SUSFS_SUS_MAP \
    --disable KSU_SUSFS_OPEN_REDIRECT \
    --disable KSU_FEATURE_ADBROOT

for key in KSU KPM KSU_SUSFS KALLSYMS KALLSYMS_ALL; do
    grep -qx "CONFIG_$key=y" "$DEF" || die "Feature not requested: $key"
done
for key in MTK_COMBO_WIFI MTK_COMBO_BT MTK_AB_OTA_UPDATER; do
    grep -qx "CONFIG_$key=y" "$DEF" || die "Critical vendor driver changed: $key"
done
cat > "$SRC/ARES_SOURCE_RECORD.txt" <<EOF
MODEL=Redmi_K40_Gaming_Enhanced_ares
SOC=MT6893_Dimensity_1200
TARGET_ANDROID=13
TARGET_FIRMWARE=HyperOS1_fingerprint_unknown
KERNEL_VERSION=4.14.186
KERNEL_SOURCE=https://github.com/cooollawf/Redmi-ares-K40G-4.14.186-Stardust-Kernel-ReSukiSU
KERNEL_SOURCE_COMMIT=$VENDOR_SHA
ORIGINAL_KERNEL_ROOT=ReSukiSU_unmodified_reference
REPLACEMENT_KSU=https://github.com/SukiSU-Ultra/SukiSU-Ultra
SUKISU_COMMIT=$SUKI_SHA
SUKISU_KERNEL_VERSION_EXPECTED=40996
SUKISU_UAPI=5
KPM=source_enabled
SUSFS=source_enabled
WIRELESS_VENDOR_KCONFIG=preserved
REAL_HYPEROS1_VENDOR_ABI=not_checked
BOOT_BLUETOOTH_WIFI_TEST=not_performed
SECURITY_CHANGE_REVIEW_REQUIRED=yes
AK3_AUTO_REBOOT=no
AUTHOR=闲心中都是莫
EOF
printf 'PASS: ares 4.14.186 prepared; official SukiSU and OEM WLAN/BT config retained.\n'
