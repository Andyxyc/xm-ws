### AnyKernel3 Ramdisk Mod Script
## OnePlus device-specific package
## Based on Numbersf/AnyKernel3 and osm0sis AnyKernel3

properties() { printf '%s\n' '
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
ui_print " SUSFS：2.3.0"
ui_print " KPM：已启用"
ui_print " 风驰/HMBIRD：__HMBIRD__"
ui_print " 零宽修复：已启用"
ui_print " 作者：心中都是莫"
ui_print " Author: xiaomo"
ui_print "========================================"

# 只允许 OnePlus。
BRAND="$(getprop ro.product.brand 2>/dev/null | tr '[:upper:]' '[:lower:]')"
if [ -n "$BRAND" ]; then
  case "$BRAND" in
    *oneplus*) ;;
    *)
      ui_print "❌ 当前设备不是 OnePlus，已停止。"
      exit 1
      ;;
  esac
fi

# 对已配置的机型做专用校验。Pad Pro 使用 OPD2404。
EXPECTED_DEVICE="__DEVICE_ID__"
if [ -n "$EXPECTED_DEVICE" ]; then
  DEVICE_INFO="$(getprop ro.product.device 2>/dev/null) $(getprop ro.build.product 2>/dev/null) $(getprop ro.product.vendor.device 2>/dev/null) $(getprop ro.vendor.product.device 2>/dev/null) $(getprop ro.product.model 2>/dev/null) $(getprop ro.product.marketname 2>/dev/null)"
  if ! printf '%s' "$DEVICE_INFO" | grep -qi "$EXPECTED_DEVICE"; then
    ui_print "❌ 机型不匹配，已停止。"
    ui_print " 需要：$EXPECTED_DEVICE"
    ui_print " 当前：$DEVICE_INFO"
    exit 1
  fi
fi

CURRENT_KERNEL="$(uname -r 2>/dev/null)"
CURRENT_MM="$(printf '%s' "$CURRENT_KERNEL" | cut -d. -f1,2)"
EXPECTED_MM="__KERNEL_MM__"
if [ -n "$CURRENT_MM" ] && [ "$CURRENT_MM" != "$EXPECTED_MM" ]; then
  ui_print "❌ 内核大版本不匹配。"
  ui_print " 当前：$CURRENT_MM  需要：$EXPECTED_MM"
  exit 1
fi

if [ -d /data/adb/magisk ] || [ -f /sbin/.magisk ]; then
  ui_print "❌ 检测到 Magisk 或残留，已停止。"
  exit 1
fi

# ------------------------------------------------------------
# 自动读取另一槽的 stock-looking uname/build，供 SUSFS 运行时伪造。
# B 槽运行时读 A；A 槽运行时读 B；无法判断时优先读 A。
# 这里只读取参考槽，不修改参考槽，也不直接改 Image 字符串。
# ------------------------------------------------------------
REF_UNAME=""
REF_BUILD=""
REF_SLOT=""
REF_BLOCK=""
FORCED_UNAME="__FORCED_UNAME__"

ACTIVE_SLOT="$(getprop ro.boot.slot_suffix 2>/dev/null)"
[ -n "$ACTIVE_SLOT" ] || {
  ACTIVE_SLOT="$(getprop ro.boot.slot 2>/dev/null)"
  [ -n "$ACTIVE_SLOT" ] && ACTIVE_SLOT="_$ACTIVE_SLOT"
}
case "$ACTIVE_SLOT" in
  _a|a) REF_SLOT="_b" ;;
  _b|b) REF_SLOT="_a" ;;
  *) REF_SLOT="_a" ;;
esac

for base in /dev/block/by-name /dev/block/bootdevice/by-name; do
  if [ -e "$base/boot$REF_SLOT" ]; then
    REF_BLOCK="$base/boot$REF_SLOT"
    break
  fi
done

if [ -n "$REF_BLOCK" ]; then
  REF_DIR="$AKHOME/.refslot"
  rm -rf "$REF_DIR"
  mkdir -p "$REF_DIR"
  ui_print "参考槽：boot$REF_SLOT"
  if dd if="$REF_BLOCK" of="$REF_DIR/boot.img" bs=1048576 2>/dev/null; then
    (
      cd "$REF_DIR" || exit 1
      magiskboot unpack -h boot.img >/dev/null 2>&1 || exit 1
      KFILE=""
      for k in kernel kernel.gz kernel.lz4 Image Image.gz Image.lz4; do
        [ -f "$k" ] && { KFILE="$k"; break; }
      done
      [ -n "$KFILE" ] || exit 1
      BANNER="$(strings "$KFILE" 2>/dev/null | grep -m1 '^Linux version ')"
      if [ -z "$BANNER" ]; then
        magiskboot decompress "$KFILE" kernel.dec >/dev/null 2>&1 || true
        [ -f kernel.dec ] && BANNER="$(strings kernel.dec 2>/dev/null | grep -m1 '^Linux version ')"
      fi
      [ -n "$BANNER" ] || exit 1
      printf '%s\n' "$BANNER" > banner.txt
    )
    if [ -s "$REF_DIR/banner.txt" ]; then
      REF_BANNER="$(cat "$REF_DIR/banner.txt")"
      REF_UNAME="$(printf '%s\n' "$REF_BANNER" | sed -n 's/^Linux version \([^ ]*\).*/\1/p')"
      REF_BUILD="$(printf '%s\n' "$REF_BANNER" | sed -n 's/.*\(#[0-9][^#]*\)$/\1/p')"
      if ! printf '%s' "$REF_UNAME" | grep -Eq '^[A-Za-z0-9._:+-]+$'; then
        REF_UNAME=""
      fi
      if ! printf '%s' "$REF_BUILD" | grep -Eq '^[A-Za-z0-9# ._:+()/-]+$'; then
        REF_BUILD=""
      fi
      if [ -n "$REF_UNAME" ] && [ -n "$REF_BUILD" ]; then
        ui_print "参考 Uname：$REF_UNAME"
        ui_print "参考构建：$REF_BUILD"
      else
        ui_print "ℹ️ 参考槽信息格式异常，本次不启用 Uname 伪造。"
      fi
    else
      ui_print "ℹ️ 无法解析参考槽内核，本次不启用 Uname 伪造。"
    fi
  else
    ui_print "ℹ️ 无法读取参考槽，本次不启用 Uname 伪造。"
  fi
  rm -rf "$REF_DIR"
else
  ui_print "ℹ️ 未找到另一槽 boot，本次不启用 Uname 伪造。"
fi

if [ -n "$FORCED_UNAME" ]; then
  if printf '%s' "$FORCED_UNAME" | grep -Eq '^[A-Za-z0-9._:+-]+$'; then
    REF_UNAME="$FORCED_UNAME"
    [ -n "$REF_BUILD" ] || REF_BUILD="$(uname -v 2>/dev/null)"
    ui_print "指定 Uname：$REF_UNAME"
  else
    ui_print "⚠️ 指定 Uname 格式异常，忽略。"
  fi
fi

# ------------------------------------------------------------
# SUSFS 模块：相同/更高版本直接跳过；仅旧版/未安装时更新。
# 模块更新失败不会把已经成功的内核刷入判定为失败。
# ------------------------------------------------------------
MODULE_PATH=""
for f in "$AKHOME"/ksu_module_susfs*.zip "$AKHOME"/susfs*.zip; do
  if [ -f "$f" ]; then
    MODULE_PATH="$f"
    break
  fi
done

SUSFS_MODULE_ID="susfs4ksu"
SUSFS_BUNDLED_CODE=0
SUSFS_BUNDLED_VERSION="unknown"
SUSFS_INSTALLED_CODE=0
SUSFS_INSTALLED_VERSION="none"
SUSFS_NEED_INSTALL=0

if [ -n "$MODULE_PATH" ]; then
  BPROP="$AKHOME/.susfs_bundled.prop"
  rm -f "$BPROP"
  unzip -p "$MODULE_PATH" module.prop > "$BPROP" 2>/dev/null || true
  if [ -s "$BPROP" ]; then
    PID="$(grep '^id=' "$BPROP" | head -n1 | cut -d= -f2-)"
    PCODE="$(grep '^versionCode=' "$BPROP" | head -n1 | cut -d= -f2-)"
    PVER="$(grep '^version=' "$BPROP" | head -n1 | cut -d= -f2-)"
    [ -n "$PID" ] && SUSFS_MODULE_ID="$PID"
    case "$PCODE" in ''|*[!0-9]*) ;; *) SUSFS_BUNDLED_CODE="$PCODE" ;; esac
    [ -n "$PVER" ] && SUSFS_BUNDLED_VERSION="$PVER"
  fi

  for iprop in "/data/adb/modules/$SUSFS_MODULE_ID/module.prop" "/data/adb/modules_update/$SUSFS_MODULE_ID/module.prop"; do
    [ -f "$iprop" ] || continue
    ICODE="$(grep '^versionCode=' "$iprop" | head -n1 | cut -d= -f2-)"
    IVER="$(grep '^version=' "$iprop" | head -n1 | cut -d= -f2-)"
    case "$ICODE" in
      ''|*[!0-9]*) ;;
      *)
        if [ "$ICODE" -gt "$SUSFS_INSTALLED_CODE" ] 2>/dev/null; then
          SUSFS_INSTALLED_CODE="$ICODE"
          [ -n "$IVER" ] && SUSFS_INSTALLED_VERSION="$IVER"
        fi
        ;;
    esac
  done

  if [ "$SUSFS_BUNDLED_CODE" -gt 0 ] 2>/dev/null && [ "$SUSFS_INSTALLED_CODE" -ge "$SUSFS_BUNDLED_CODE" ] 2>/dev/null; then
    ui_print "✅ SUSFS 已是相同或更高版本：$SUSFS_INSTALLED_VERSION"
    ui_print "   跳过重复安装。"
  else
    SUSFS_NEED_INSTALL=1
    if [ "$SUSFS_INSTALLED_CODE" -gt 0 ] 2>/dev/null; then
      ui_print "SUSFS 旧版：$SUSFS_INSTALLED_VERSION → $SUSFS_BUNDLED_VERSION"
    else
      ui_print "未检测到 SUSFS 模块，将安装：$SUSFS_BUNDLED_VERSION"
    fi
  fi
fi
rm -f "$AKHOME/.susfs_bundled.prop"

KSUD_PATH=""
for p in /data/adb/ksud /data/adb/ksu/bin/ksud /data/adb/sukisu/bin/ksud; do
  if [ -x "$p" ]; then
    KSUD_PATH="$p"
    break
  fi
done

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

if [ "$SUSFS_NEED_INSTALL" = "1" ]; then
  if [ -n "$KSUD_PATH" ] && [ -x "$KSUD_PATH" ]; then
    ui_print "正在更新 SUSFS 模块..."
    if "$KSUD_PATH" module install "$MODULE_PATH"; then
      sync
      ui_print "✅ SUSFS 模块更新完成。"
    else
      ui_print "⚠️ SUSFS 模块更新失败；内核刷入仍然成功。"
    fi
  else
    ui_print "⚠️ 未找到 ksud，跳过 SUSFS 模块更新；内核刷入仍然成功。"
  fi
fi

# 写入持久化 Uname/Build 伪造配置。
if [ -n "$REF_UNAME" ] && [ -n "$REF_BUILD" ]; then
  PERSISTENT_DIR="/data/adb/susfs4ksu"
  CFG="$PERSISTENT_DIR/config.sh"
  mkdir -p "$PERSISTENT_DIR"
  if [ ! -f "$CFG" ] && [ -n "$MODULE_PATH" ]; then
    unzip -p "$MODULE_PATH" config.sh > "$CFG" 2>/dev/null || true
  fi
  [ -f "$CFG" ] || touch "$CFG"

  set_cfg_num() {
    key="$1"; val="$2"
    if grep -q "^$key=" "$CFG"; then
      sed -i "s|^$key=.*|$key=$val|" "$CFG"
    else
      echo "$key=$val" >> "$CFG"
    fi
  }
  set_cfg_str() {
    key="$1"; val="$2"
    if grep -q "^$key=" "$CFG"; then
      sed -i "s|^$key=.*|$key='$val'|" "$CFG"
    else
      echo "$key='$val'" >> "$CFG"
    fi
  }

  set_cfg_num spoof_uname 2
  set_cfg_str kernel_version "$REF_UNAME"
  set_cfg_str kernel_build "$REF_BUILD"
  chmod 600 "$CFG" 2>/dev/null || true
  ui_print "✅ 已设置自动 Uname/构建信息伪造："
  ui_print "   $REF_UNAME"
  ui_print "   $REF_BUILD"

  for sb in /data/adb/ksu/bin/ksu_susfs /data/adb/ksu/bin/ksu_susfs_arm64; do
    if [ -x "$sb" ]; then
      "$sb" set_uname "$REF_UNAME" "$REF_BUILD" >/dev/null 2>&1 || true
      break
    fi
  done
fi

ui_print "========================================"
ui_print " 安装完成，请重启设备。"
ui_print " 作者：心中都是莫"
ui_print " Author: xiaomo"
ui_print "========================================"
