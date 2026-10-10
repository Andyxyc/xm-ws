### AnyKernel3 Ramdisk Mod Script
## Ace 5 Pro / PKR110 ONLY -- Android 16 / kernel 6.6.89
## PKR110 A16 6.6.89 SukiSU Ultra 40959 UAPI5 SUSFS PORT - UNTESTED
## Based on osm0sis/cctv18 AnyKernel3; WildKernels PKR110 6.6.89 scheduler reference
## Author: 闲鱼 心中都是莫

properties() { printf '%s\n' '
kernel.string=Ace5Pro 6.6.89 SukiSU40959 SUSFS ONLY - TEST
do.devicecheck=0
do.modules=0
do.systemless=0
do.cleanup=1
do.cleanuponabort=0
device.name1=
device.name2=
device.name3=
device.name4=
device.name5=
supported.versions=
supported.patchlevels=
supported.vendorpatchlevels=
'; }

BLOCK=boot
IS_SLOT_DEVICE=auto
RAMDISK_COMPRESSION=auto
PATCH_VBMETA_FLAG=auto
NO_MAGISK_CHECK=1

. tools/ak3-core.sh

ui_print "================================================"
ui_print " OnePlus Ace 5 Pro / PKR110 - SUSFS Minimal Test"
ui_print " Kernel base: 6.6.89 / Android 16 / SukiSU 40959"
ui_print " Kept: core SukiSU + SUSFS"
ui_print " Removed: KPM, ADIOS, BBG, LZ4, extra patches"
ui_print " Original vendor scheduler remains in kernel tree"
ui_print " Author: 闲鱼 心中都是莫"
ui_print " WARNING: UNTESTED - keep stock boot.img backup"
ui_print "================================================"

# Strictly identify both hardware identity fields where available.
MODEL="$(getprop ro.product.model 2>/dev/null | tr -d '\r\n')"
DEVICE="$(getprop ro.product.device 2>/dev/null | tr -d '\r\n')"
BRAND="$(getprop ro.product.brand 2>/dev/null | tr '[:upper:]' '[:lower:]' | tr -d '\r\n')"
ANDROID="$(getprop ro.build.version.release 2>/dev/null | tr -d '\r\n')"
RUNNING_KERNEL="$(uname -r 2>/dev/null | tr -d '\r\n')"

case "$BRAND" in
  *oneplus*) ;;
  *) abort "Refusing flash: device brand is not OnePlus ($BRAND)" ;;
esac
[ "$MODEL" = "PKR110" ] || abort "Refusing flash: expected PKR110, got [$MODEL]"
[ "$DEVICE" = "OP60EBL1" ] || abort "Refusing flash: expected OP60EBL1, got [$DEVICE]"
[ "$ANDROID" = "16" ] || abort "Refusing flash: expected Android16, got [$ANDROID]"
# Fail closed if the target ROM build cannot be established from Android properties.
# A16.0.8.300-based vendor modules must not be assumed compatible with this ROM.
ROM_ID="$(getprop ro.build.version.ota 2>/dev/null | tr -d '\r\n')"
[ -n "$ROM_ID" ] || ROM_ID="$(getprop ro.build.version.incremental 2>/dev/null | tr -d '\r\n')"
[ -n "$ROM_ID" ] || ROM_ID="$(getprop ro.build.display.id 2>/dev/null | tr -d '\r\n')"
case "$ROM_ID" in
  *PKR110*16.0.5.700*|*16.0.5.700*PKR110*) ;;
  *) abort "Refusing flash: requires PKR110 ColorOS 16.0.5.700, got [$ROM_ID]" ;;
esac

case "$RUNNING_KERNEL" in
  6.6.89-android15-8-*) ;;
  *) abort "Refusing flash: stock kernel base mismatch ($RUNNING_KERNEL)" ;;
esac

test -s "$AKHOME/Image" || abort "Missing kernel Image"
ui_print " Device and kernel checks passed; flashing boot only."
ui_print " Other partitions and user data remain unchanged."

split_boot
if [ -f "split_img/ramdisk.cpio" ]; then
  unpack_ramdisk
  write_boot
else
  flash_boot
fi
sync
ui_print " Boot image updated. Reboot only after ensuring stock backup."
