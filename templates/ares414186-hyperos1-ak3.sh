### AnyKernel3 Ramdisk Mod Script
## Redmi K40 Gaming Enhanced / ares / MediaTek MT6893 ONLY
## HyperOS 1 / Android 13 / Kernel 4.14.186 experimental source compatibility
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
ui_print " Linux 4.14.186 / MT6893 / Android 13"
ui_print " SukiSU Ultra：v4.2.1"
ui_print " SUSFS: Enabled"
ui_print " KPM: Enabled"
ui_print " 作者：闲心中都是莫"
ui_print "============================================"
ui_print " 未验证澎湃 OS 原厂内核 ABI；此包只适配"
ui_print " 已运行 4.14.186 同系内核的设备。"
ui_print " 固件/无线驱动匹配必须核实，不能只看版本号。"

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
  4.14.186*) ;;
  *) abort "当前内核 $ACTIVE_KERNEL 不匹配候选 4.14.186；拒绝危险跨版本刷写" ;;
esac
test -s "$AKHOME/Image.gz-dtb" || abort "缺少编译后的 Image.gz-dtb"
ui_print " 当前内核版本及机型检查通过"
ui_print " 仅替换活动槽 boot 内核，保留原有 ramdisk"
ui_print " 当前 boot 将先行备份；不会覆盖已有备份。"
[ -b "$BLOCK" ] || abort "AK3 无法确定当前 boot 分区"
BACKUP="/sdcard/Download/K40Gaming_ares_boot_before_SukiSU.img"
test -d /sdcard/Download || abort "Download 路径未挂载，无法安全备份"
test ! -e "$BACKUP" || abort "已存在原 boot 备份，请保留，拒绝覆盖"
dd if="$BLOCK" of="$BACKUP" bs=1048576 2>/dev/null || abort "boot 备份失败，已停止安装"
SOURCE_BYTES="$(blockdev --getsize64 "$BLOCK" 2>/dev/null || true)"
TARGET_BYTES="$(wc -c < "$BACKUP" 2>/dev/null | tr -d '[:space:]')"
case "$SOURCE_BYTES:$TARGET_BYTES" in *[!0-9:]*|:*|*:) abort "无法验证原始 boot 备份大小" ;; esac
[ "$SOURCE_BYTES" = "$TARGET_BYTES" ] || abort "原始 boot 备份长度不匹配，拒绝刷入"
sync
ui_print " 原始 boot 已备份到 Download，请勿删除"

split_boot
flash_boot
sync
ui_print " 内核写入结束，未自动重启"
