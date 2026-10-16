### AnyKernel3 Ramdisk Mod Script
## Redmi K40 (alioth) — HyperOS 1 / Android 13 / Linux 4.19.325
## Linux 4.19 Non-GKI SukiSU builtin + native KPM + SUSFS
## Author: 闲心中都是莫
## Original AnyKernel3: osm0sis; source: zfdx123, LeviMarvin.

properties() { printf '%s\n' '
kernel.string=Redmi K40 alioth HyperOS1 SukiSU Ultra v4.2.1 SUSFS KPM
do.devicecheck=1
do.modules=0
do.systemless=0
do.cleanup=1
do.cleanuponabort=0
device.name1=alioth
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

ui_print "=============================================="
ui_print " 红米 K40 (alioth) | 澎湃 OS 1.0"
ui_print " 内核：Linux 4.19.325 / ARM64"
ui_print " SukiSU Ultra：v4.2.1 / builtin / UAPI5"
ui_print " SUSFS: Enabled"
ui_print " KPM: Enabled"
ui_print " 保留 Xiaomi WALT 调度"
ui_print " 作者：闲心中都是莫"
ui_print "=============================================="

MODEL="$(getprop ro.product.device 2>/dev/null | tr -d '\r\n ')"
VENDOR="$(getprop ro.product.vendor.device 2>/dev/null | tr -d '\r\n ')"
BOARD="$(getprop ro.build.product 2>/dev/null | tr -d '\r\n ')"
case " $MODEL $VENDOR $BOARD " in
  *" alioth "*) ;;
  *) abort "未确认设备为 Redmi K40 / alioth，已停止刷写" ;;
esac
for value in "$MODEL" "$VENDOR"; do
  case "$value" in ""|alioth) ;; *) abort "机型标识冲突：$value" ;; esac
done

ANDROID="$(getprop ro.build.version.release 2>/dev/null | tr -d '\r\n ')"
[ "$ANDROID" = 13 ] || abort "当前系统不是 Android 13：$ANDROID"
ARCH="$(uname -m 2>/dev/null || true)"
case "$ARCH" in aarch64|arm64) ;; *) abort "当前架构不匹配：$ARCH" ;; esac
KERNEL="$(uname -r 2>/dev/null || true)"
case "$KERNEL" in 4.19.325*) ;; *) abort "当前内核 $KERNEL 与编译基线 4.19.325 不匹配" ;; esac
test -s "$AKHOME/Image.gz-dtb" || abort "AK3 缺少编译镜像 Image.gz-dtb"

# Ensure an original boot backup is saved before any partition write.
SLOT="$(getprop ro.boot.slot_suffix 2>/dev/null | tr -d '\r\n ')"
case "$SLOT" in _a|_b) ;; *) abort "无法识别当前启动槽位：$SLOT" ;; esac
BOOT_DEV="/dev/block/by-name/boot$SLOT"
[ -b "$BOOT_DEV" ] || abort "无法访问 boot 分区：$BOOT_DEV"
[ -d /sdcard/Download ] || abort "Download 目录不可写，拒绝无备份刷写"
BACKUP="/sdcard/Download/K40_alioth_boot_before_SukiSU$SLOT.img"
[ ! -e "$BACKUP" ] || abort "已存在原 boot 备份，不允许覆盖：$BACKUP"
dd if="$BOOT_DEV" of="$BACKUP" bs=1048576 2>/dev/null || abort "备份原始 boot 失败"
SRC_BYTES="$(blockdev --getsize64 "$BOOT_DEV" 2>/dev/null || true)"
DST_BYTES="$(wc -c < "$BACKUP" 2>/dev/null | tr -d '[:space:]')"
case "$SRC_BYTES" in ''|*[!0-9]*) abort "无法核实 boot 分区大小" ;; esac
case "$DST_BYTES" in ''|*[!0-9]*) abort "无法核实备份文件大小" ;; esac
[ "$SRC_BYTES" = "$DST_BYTES" ] && [ "$DST_BYTES" -ge 4194304 ] || abort "boot 备份尺寸不匹配"
sync
ui_print " 已备份 boot$SLOT 到 Download：$DST_BYTES 字节"

# AnyKernel3 uses the current active boot slot. Do not touch
# init_boot, vendor_boot, dtbo, vbmeta, system, data or vendor modules.
split_boot
flash_boot
sync
ui_print " boot 分区刷入结束，不自动重启"
ui_print " 已保留原始 boot 备份；请核对恢复方式"
