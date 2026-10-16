### AnyKernel3 Ramdisk Mod Script
## OnePlus Ace 6 / PLQ110 / ktm / ColorOS 16 Android 16 only
## Kernel: OnePlusOSS 6.6.118 + SukiSU Ultra + SUSFS 2.3.0 + native KPM
## Author: 闲心中都是莫
## Original AnyKernel3: osm0sis. Source acknowledgements: OnePlusOSS, SukiSU-Ultra, cctv18.
## Firmware-specific kernel-to-vendor ABI must be independently verified.

properties() { printf '%s\n' '
kernel.string=OnePlus Ace 6 | SukiSU Ultra | SUSFS 2.3.0 | KPM
do.devicecheck=1
do.modules=0
do.systemless=0
do.cleanup=1
do.cleanuponabort=0
device.name1=ktm
device.name2=PLQ110
device.name3=
device.name4=
device.name5=
supported.versions=
supported.patchlevels=
supported.vendorpatchlevels=
'; }

# Compatible with current and legacy pinned AnyKernel3 variable naming.
BLOCK=boot
IS_SLOT_DEVICE=auto
SLOT_SELECT=active
RAMDISK_COMPRESSION=auto
PATCH_VBMETA_FLAG=auto
NO_MAGISK_CHECK=1
block=boot
is_slot_device=auto
slot_select=active
ramdisk_compression=auto
patch_vbmeta_flag=auto
no_magisk_check=1

. tools/ak3-core.sh

ui_print "=============================================="
ui_print " 一加 Ace 6 · PLQ110 · ColorOS 16"
ui_print " 内核：Linux 6.6.118 · Android 16"
ui_print " SukiSU Ultra：__REAL_KSU_VERSION__"
ui_print " SUSFS: Enabled"
ui_print " KPM: Enabled"
ui_print " 调度与原厂驱动：不额外修改"
ui_print " 作者：闲心中都是莫"
ui_print "=============================================="

BRAND="$(getprop ro.product.brand 2>/dev/null | tr '[:upper:]' '[:lower:]' | tr -d '\r\n ')"
case "$BRAND" in *oneplus*) ;; *) abort "非一加设备，停止刷写" ;; esac

DEVICE="$(getprop ro.product.device 2>/dev/null | tr -d '\r\n ')"
VENDOR="$(getprop ro.product.vendor.device 2>/dev/null | tr -d '\r\n ')"
PRODUCT="$(getprop ro.build.product 2>/dev/null | tr -d '\r\n ')"
MODEL="$(getprop ro.product.model 2>/dev/null | tr -d '\r\n ')"
case " $DEVICE $VENDOR $PRODUCT $MODEL " in
  *" ktm "*|*" PLQ110 "*) ;;
  *) abort "检测不到 Ace 6 / ktm / PLQ110，拒绝刷写" ;;
esac

ANDROID="$(getprop ro.build.version.release 2>/dev/null | tr -d '\r\n ')"
[ "$ANDROID" = "16" ] || abort "Android 系统版本不匹配：$ANDROID"

RUNNING="$(uname -r 2>/dev/null || true)"
case "$RUNNING" in
  6.6.118-android15-8-*) ;;
  *) abort "当前内核不属于 Ace 6 Android15-8 6.6.118 基线：$RUNNING" ;;
esac

# Replaced only after verifying EXACT target firmware's vendor module ABI.
FIRMWARE_GUARD="__VERIFIED_FIRMWARE__"
case "$FIRMWARE_GUARD" in
  ""|*__VERIFIED*__)
     abort "此版本尚未完成与当前固件的驱动兼容性验证，禁止刷入"
     ;;
esac
FIRMWARE="$(getprop ro.build.version.ota 2>/dev/null || true) $(getprop ro.build.display.id 2>/dev/null || true) $(getprop ro.vendor.build.fingerprint 2>/dev/null || true)"
case "$FIRMWARE" in
  *"$FIRMWARE_GUARD"*) ;;
  *) abort "当前固件与经过验证的目标版本不同，停止刷写" ;;
esac

test -s "$AKHOME/Image" || abort "编译后的 Image 不存在"
ui_print " 机型、内核与固件兼容性检查通过"
ui_print " 即将只修改当前活动槽 boot，保留 ramdisk"

# The installer never writes vendor_boot, dtbo, persist, data or vendor_dlkm
# and never starts an automatic reboot.
split_boot
flash_boot
sync
ui_print " 已完成 boot 内核写入"
ui_print " 未自动重启，原厂 boot 恢复镜像请妥善保留"
