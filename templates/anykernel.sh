### AnyKernel3 Ramdisk Mod Script
## OnePlus device-specific package
## Based on Numbersf/AnyKernel3 and osm0sis AnyKernel3

properties() { '
kernel.string=xiaomo OnePlus Kernel
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

sync
sleep 0.5
chmod -R 755 "$AKHOME/tools"

ui_print "========================================"
ui_print " OnePlus 专用 SukiSU Ultra 内核"
ui_print " 目标配置：__TARGET__"
ui_print " 内核：__KERNEL__"
ui_print " SukiSU Ultra：40959"
ui_print " SUSFS：v2.3.0"
ui_print " KPM：已启用"
ui_print " 风驰：__HMBIRD__"
ui_print " 零宽修复：已启用"
ui_print " 作者：心中都是莫"
ui_print " Author: xiaomo"
ui_print "========================================"

BRAND="$(getprop ro.product.brand 2>/dev/null | tr '[:upper:]' '[:lower:]')"
if [ -n "$BRAND" ]; then
 case "$BRAND" in
    *oneplus*) ;;
    *)
 ui_print "❌ 当前设备品牌不是 OnePlus，已停止。"
      exit 1
      ;;
  esac
fi

CURRENT_KERNEL="$(uname -r 2>/dev/null)"
CURRENT_MM="$(printf '%s' "$CURRENT_KERNEL" | cut -d. -f1,2)"
EXPECTED_MM="__KERNEL_MM__"
if [ -n "$CURRENT_MM" ] && [ "$CURRENT_MM" != "$EXPECTED_MM" ]; then
 ui_print "❌ 内核大版本不匹配。"
 ui_print " 当前：$CURRENT_MM  需要：$EXPECTED_MM"
 ui_print " 已在写入 Boot 前停止。"
  exit 1
fi

if [ -d /data/adb/magisk ] || [ -f /sbin/.magisk ]; then
 ui_print "❌ 检测到 Magisk 或残留。"
 ui_print " 为避免混用 Root 方案，本包不会继续写入 Boot。"
  exit 1
fi

MODULE_PATH=""
for f in "$AKHOME"/ksu_module_susfs*.zip "$AKHOME"/susfs*.zip; do
  if [ -f "$f" ]; then
    MODULE_PATH="$f"
    break
  fi
done
if [ -z "$MODULE_PATH" ]; then
 ui_print "❌ AK3 内未找到 SUSFS 模块，已停止。"
  exit 1
fi

KSUD_PATH=""
for p in /data/adb/ksud /data/adb/ksu/bin/ksud /data/adb/sukisu/bin/ksud; do
  if [ -x "$p" ]; then
    KSUD_PATH="$p"
    break
  fi
done
if [ -z "$KSUD_PATH" ] && [ -d /data/adb ]; then
  KSUD_PATH="$(find /data/adb -type f -name ksud 2>/dev/null | head -n 1)"
fi
if [ -z "$KSUD_PATH" ] || [ ! -x "$KSUD_PATH" ]; then
 ui_print "❌ 未找到可执行 ksud。"
 ui_print " SUSFS 模块无法自动安装，因此在刷写前停止。"
  exit 1
fi

ui_print "正在刷写内核..."
split_boot

if [ -f "split_img/ramdisk.cpio" ]; then
  unpack_ramdisk
  write_boot
else
  flash_boot
fi

sync
ui_print "✅ 内核刷写完成。"
ui_print "正在自动安装 SUSFS 模块..."
if "$KSUD_PATH" module install "$MODULE_PATH"; then
  sync
 ui_print "✅ SUSFS 模块安装完成。"
else
 ui_print "❌ SUSFS 模块自动安装失败。"
 ui_print " 内核已经写入，请不要把本次结果视为完整安装成功。"
  exit 1
fi

ui_print "========================================"
ui_print " 安装完成，请重启设备。"
ui_print " 作者：心中都是莫"
ui_print " Author: xiaomo"
ui_print "========================================"
