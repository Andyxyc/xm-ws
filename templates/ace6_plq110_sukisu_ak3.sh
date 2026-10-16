### AnyKernel3 Ramdisk Mod Script
## OnePlus Ace 6 (PLQ110 / ktm), ColorOS 16 Android 16 Linux 6.6.118
## Original installer based on osm0sis/AnyKernel3.
## Author: 闲心中都是莫

properties() { printf '%s\n' '
kernel.string=OnePlus Ace 6 PLQ110 SukiSU Ultra SUSFS KPM
do.devicecheck=0
do.modules=0
do.systemless=0
do.cleanup=1
do.cleanuponabort=0
device.name1=
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
ui_print " 一加 Ace 6 / PLQ110"
ui_print " Android 16 / 6.6.118"
ui_print " SukiSU Ultra: builtin (UAPI5)"
ui_print " SUSFS: Enabled"
ui_print " KPM: Enabled"
ui_print " 原厂调度：未添加自定义调度"
ui_print " 作者：闲心中都是莫"
ui_print "================================================"

# Only the active boot partition is modified. No vendor_boot/dtbo/other writes.
BRAND="$(getprop ro.product.brand 2>/dev/null | tr '[:upper:]' '[:lower:]' | tr -d '\r\n ')"
case "$BRAND" in *oneplus*) ;; *) abort "当前设备品牌不是 OnePlus：$BRAND" ;; esac

MODEL=""
for key in ro.product.device ro.product.vendor.device ro.product.model ro.build.product; do
  value="$(getprop "$key" 2>/dev/null | tr -d '\r\n ')"
  case "$value" in PLQ110|plq110|ktm) MODEL=PLQ110;; esac
done
[ "$MODEL" = PLQ110 ] || abort "设备型号与一加 Ace 6 (PLQ110) 不匹配，已停止"

ANDROID="$(getprop ro.build.version.release 2>/dev/null | tr -d '\r\n ')"
[ "$ANDROID" = 16 ] || abort "仅适配 Android 16，当前版本：$ANDROID"

FW_OK=0
FW_SHOW=""
for key in ro.build.version.ota ro.build.version.incremental ro.build.display.id; do
  value="$(getprop "$key" 2>/dev/null | tr -d '\r\n ')"
  case "$value" in
    *PLQ110_16.0.10.500*) FW_OK=1; FW_SHOW="$value"; break ;;
  esac
done
[ "$FW_OK" = 1 ] || abort "当前固件不是 PLQ110_16.0.10.500，无法确定适配版本"
ui_print " 当前固件：$FW_SHOW"

ORIG_KERNEL="$(uname -r 2>/dev/null || true)"
case "$ORIG_KERNEL" in
  6.6.118-android15-8-*) ;;
  *) abort "当前内核与目标 6.6.118/android15-8 不匹配：$ORIG_KERNEL" ;;
esac
test -s "$AKHOME/Image" || abort "缺少 AK3 内核 Image"

# Preserve original active boot byte-for-byte before writing.
SLOT="$(getprop ro.boot.slot_suffix 2>/dev/null | tr -d '\r\n ')"
case "$SLOT" in
  _a|_b) ;;
  *) abort "无法确认当前活动槽位：$SLOT" ;;
esac
BOOT_DEV=""
for parent in /dev/block/by-name /dev/block/bootdevice/by-name; do
  test -b "$parent/boot$SLOT" && { BOOT_DEV="$parent/boot$SLOT"; break; }
done
[ -n "$BOOT_DEV" ] || abort "无法定位当前活动槽的 boot$SLOT"
[ -d /sdcard/Download ] && [ -w /sdcard/Download ] || abort "无法写入 Download 备份目录"

NOW="$(date +%Y%m%d_%H%M%S 2>/dev/null || true)"
case "$NOW" in ""|*[!0-9_]*) abort "时间异常，无法生成安全备份文件名" ;; esac
BACKUP="/sdcard/Download/Ace6_PLQ110_boot$SLOT-before_$NOW.img"
[ ! -e "$BACKUP" ] || abort "备份路径已存在，防止覆盖，已停止"
ui_print " 正在备份当前 boot$SLOT..."
dd if="$BOOT_DEV" of="$BACKUP" bs=1048576 2>/dev/null || abort "读取原 boot 失败，不刷写"
sync
SRC_SHA="$(sha256sum "$BOOT_DEV" 2>/dev/null | cut -d' ' -f1)"
BAK_SHA="$(sha256sum "$BACKUP" 2>/dev/null | cut -d' ' -f1)"
LEN="$(printf '%s' "$SRC_SHA" | wc -c | tr -d '[:space:]')"
case "$LEN" in 64) ;; *) abort "原始 boot SHA-256 校验值异常" ;; esac
[ "$SRC_SHA" = "$BAK_SHA" ] || abort "boot 备份校验失败，停止刷写"
ui_print " 原 boot 已备份：$BACKUP"
ui_print " SHA-256 校验通过"

ui_print " 正在替换活动 boot 中的内核..."
split_boot
flash_boot
sync

ui_print "================================================"
ui_print " boot 内核已写入；没有执行自动重启"
ui_print " 恢复原 boot 时请使用上述备份"
ui_print "================================================"
