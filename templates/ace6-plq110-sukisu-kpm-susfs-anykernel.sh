### AnyKernel3 Ramdisk Mod Script
## OnePlus Ace 6 / PLQ110 / ktm / SM8750 Android 16
## SukiSU Ultra builtin + SUSFS + native KPM
## Author: 闲心中都是莫

properties() { printf '%s\n' '
kernel.string=OnePlus Ace 6 PLQ110 - SukiSU Ultra / SUSFS / KPM
do.devicecheck=1
do.modules=0
do.systemless=0
do.cleanup=1
do.cleanuponabort=0
device.name1=ktm
device.name2=OP6113L1
device.name3=PLQ110
device.name4=
device.name5=
supported.versions=
supported.patchlevels=
supported.vendorpatchlevels=
'; }

BLOCK=boot
IS_SLOT_DEVICE=auto
SLOT_SELECT=active
RAMDISK_COMPRESSION=auto
PATCH_VBMETA_FLAG=auto
NO_MAGISK_CHECK=1

# Legacy AK3 compatibility aliases used by some recovery/manager releases.
block=boot
is_slot_device=auto
slot_select=active
ramdisk_compression=auto
patch_vbmeta_flag=auto
no_magisk_check=1

. tools/ak3-core.sh

ui_print "============================================"
ui_print " 一加 Ace 6 / PLQ110"
ui_print " 内核：6.6.118 / Android 16"
ui_print " SukiSU Ultra：内置版本"
ui_print " SUSFS: Enabled"
ui_print " KPM: Enabled"
ui_print " 作者：闲心中都是莫"
ui_print "============================================"

DEVICE="$(getprop ro.product.device 2>/dev/null | tr -d '\r\n ')"
VENDOR="$(getprop ro.product.vendor.device 2>/dev/null | tr -d '\r\n ')"
case " $DEVICE $VENDOR " in
  *" ktm "*|*" OP6113L1 "*|*" PLQ110 "*) ;;
  *) abort "当前设备不是一加 Ace 6 (PLQ110)，停止刷入" ;;
esac

[ "$(getprop ro.build.version.release 2>/dev/null | tr -d '\r\n ')" = 16 ] ||
  abort "需要 Android 16，未修改任何分区"

FIRMWARE="$(getprop ro.build.version.ota 2>/dev/null) $(getprop ro.build.display.id 2>/dev/null) $(getprop ro.vendor.build.fingerprint 2>/dev/null)"
case "$FIRMWARE" in
  *PLQ110_16.0.10.500*) ;;
  *) abort "当前固件与 PLQ110_16.0.10.500 不一致，停止刷入" ;;
esac

KERNEL="$(uname -r 2>/dev/null || true)"
case "$KERNEL" in
  6.6.118-android15-8*) ;;
  *) abort "当前内核 $KERNEL 与目标 6.6.118-android15-8 不匹配" ;;
esac

test -s "$AKHOME/Image" || abort "内核镜像 Image 缺失"
# This signed-off gate is created ONLY by a separate, actual vendor-ABI
# verification on PLQ110 .500 firmware, never by a .401-only source build.
test -s "$AKHOME/ACE6_FW500_ABI_VERIFIED.txt" ||
  abort "尚未取得当前 ColorOS 版本的内核模块兼容性校验记录，停止刷入"
grep -qx 'TARGET=PLQ110_16.0.10.500(CN01B110P02)' \
  "$AKHOME/ACE6_FW500_ABI_VERIFIED.txt" ||
  abort "当前固件兼容性校验记录不匹配"
grep -qx 'REAL_VENDOR_MODULE_ABI=PASS' \
  "$AKHOME/ACE6_FW500_ABI_VERIFIED.txt" ||
  abort "无线和厂商内核模块兼容性尚未验证"

ui_print " 型号、固件、内核、兼容性检查通过"
ui_print " 正在写入活动槽 boot，保留原始 ramdisk"
split_boot
flash_boot
sync
ui_print " boot 写入完成，请自行决定何时重启"
