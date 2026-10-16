### AnyKernel3 Ramdisk Mod Script
## Redmi K40 Gaming Enhanced / ares / MediaTek MT6893 ONLY
## HyperOS 1 / Android 13 / Experimental community kernel 4.14.336
## Author: 闲心中都是莫
## Based on osm0sis AnyKernel3 and khanra17 ares integration.

properties() { printf '%s\n' '
kernel.string=Redmi K40 Gaming ares | SukiSU Ultra 4.2.1 | KPM SUSFS
do.devicecheck=1
do.modules=0
do.systemless=0
do.cleanup=1
do.cleanuponabort=0
device.name1=ares
device.name2=aresin
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

ui_print "============================================"
ui_print " 红米 K40 游戏增强版 / ares"
ui_print " Linux 4.14.336 / MT6893 / Android 13"
ui_print " SukiSU Ultra：v4.2.1"
ui_print " SUSFS: Enabled"
ui_print " KPM: Enabled"
ui_print " 作者：闲心中都是莫"
ui_print "============================================"
ui_print " 未验证澎湃 OS 原厂内核 ABI；此包只适配"
ui_print " 已运行 4.14.336 同系内核的设备。"
ui_print " 原厂 4.14.186 不可直接替换为此候选内核。"

DEV="$(getprop ro.product.device 2>/dev/null | tr -d '\r\n ')"
VENDOR="$(getprop ro.product.vendor.device 2>/dev/null | tr -d '\r\n ')"
PRODUCT="$(getprop ro.build.product 2>/dev/null | tr -d '\r\n ')"
case " $DEV $VENDOR $PRODUCT " in
  *" ares "*|*" aresin "*) ;;
  *) abort "当前设备不是 Redmi K40 游戏增强版（ares），拒绝刷入" ;;
esac
for DEVICE in "$DEV" "$VENDOR"; do
  case "$DEVICE" in ""|ares|aresin) ;; *) abort "设备标识冲突：$DEVICE" ;; esac
done
ANDROID="$(getprop ro.build.version.release 2>/dev/null | tr -d '\r\n ')"
[ "$ANDROID" = 13 ] || abort "要求 Android 13，当前为：$ANDROID"
ACTIVE_KERNEL="$(uname -r 2>/dev/null || true)"
case "$ACTIVE_KERNEL" in
  4.14.336*) ;;
  *) abort "当前内核 $ACTIVE_KERNEL 不匹配候选 4.14.336；拒绝危险跨版本刷写" ;;
esac
test -s "$AKHOME/Image.gz" || abort "缺少编译后的 Image.gz"
ui_print " 当前内核版本及机型检查通过"
ui_print " 仅替换活动槽 boot 内核，保留原有 ramdisk"
ui_print " 请预先保存当前原厂 boot.img 以便失败时恢复"

split_boot
flash_boot
sync
ui_print " 内核写入结束，未自动重启"
