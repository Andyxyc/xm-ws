### AnyKernel3 - OnePlus Pad 2 Pro / OPD2413
# Based on osm0sis/cctv18 AnyKernel3. Author: 闲鱼 心中都是莫
properties() { printf '%s\n' '
kernel.string=OnePlus Pad 2 Pro 6.6.57 SukiSU KPM
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
AKHOME=${AKHOME:-$PWD}
LOGFILE="$AKHOME/pad2pro-install.log"
BACKUP_DIR=
: > "$LOGFILE" || exit 1
persist_log() {
    result=$?
    trap - 0
    if [ -n "$BACKUP_DIR" ]; then
        cp "$LOGFILE" "$BACKUP_DIR/install.log" 2>/dev/null
        printf '安装日志：%s/install.log\n' "$BACKUP_DIR"
    else
        printf '安装日志暂存在：%s\n' "$LOGFILE"
    fi
    exit "$result"
}
trap persist_log 0
. tools/ak3-core.sh >> "$LOGFILE" 2>&1
ui_print() {
    for text in "$@"; do
        printf '%s\n' "$text" >> "$LOGFILE"
        case "${OUTFD:-}" in
            ''|*[!0-9]*) printf '%s\n' "$text" ;;
            *) printf 'ui_print %s\nui_print\n' "$text" >> "/proc/self/fd/$OUTFD" ;;
        esac
    done
}
abort() { ui_print "安装失败：$*"; exit 1; }
for base in /sdcard/Download /data/media/0/Download /data/local/tmp; do
    if [ -d "$base" ] && [ -w "$base" ]; then
        BACKUP_DIR=$(mktemp -d "$base/Pad2Pro_Kernel_XXXXXX" 2>/dev/null)
        [ -n "$BACKUP_DIR" ] && break
    fi
done
[ -n "$BACKUP_DIR" ] || abort '没有可写的日志和启动镜像备份目录，尚未写入分区。'
ui_print '一加平板 2 Pro / OPD2413' '内核 6.6.57 · SukiSU · KPM' '作者：闲鱼 心中都是莫'
MODEL="$(getprop ro.product.model) $(getprop ro.product.vendor.model) $(getprop ro.product.odm.model)"
OTA="$(getprop ro.build.version.ota) $(getprop ro.build.display.id) $(getprop ro.build.version.incremental)"
SDK=$(getprop ro.build.version.sdk)
case "$MODEL $OTA" in *OPD2413*) ;; *) abort "机型不是 OPD2413：$MODEL" ;; esac
[ "$SDK" = 35 ] || abort "Android SDK 不匹配，需要 Android 15 / SDK 35，当前：$SDK"
case "$OTA" in *15.0.1.801*) ;; *) abort "系统版本不是 15.0.1.801：$OTA" ;; esac
ui_print "目标分区：$BLOCK" "备份目录：$BACKUP_DIR"
[ -b "$BLOCK" ] || abort "启动分区无效：$BLOCK"
[ -s "$AKHOME/Image" ] || abort '安装包缺少内核 Image。'
BB="$BIN/busybox"
[ -x "$BB" ] || abort '安装工具 busybox 不可执行。'
(cd "$AKHOME" && "$BB" sha256sum -c Image.sha256) >> "$LOGFILE" 2>&1 || abort '内核校验失败。'
split_boot >> "$LOGFILE" 2>&1 || abort '启动镜像读取或解包失败，详情见日志。'
[ -s "$BOOTIMG" ] || abort '没有取得原启动镜像。'
cp "$BOOTIMG" "$BACKUP_DIR/boot-before.img" || abort '启动镜像备份失败。'
"$BB" cmp "$BOOTIMG" "$BACKUP_DIR/boot-before.img" || abort '启动镜像备份回读不一致。'
(cd "$BACKUP_DIR" && "$BB" sha256sum boot-before.img > boot-before.img.sha256) || abort '备份校验值保存失败。'
printf 'MODEL=%s\nOTA=%s\nBLOCK=%s\n' "$MODEL" "$OTA" "$BLOCK" > "$BACKUP_DIR/device.txt"
OLD_KERNEL="$SPLITIMG/kernel"
[ -s "$OLD_KERNEL" ] || abort '无法取得原内核，拒绝猜测兼容性。'
"$BB" strings "$OLD_KERNEL" > "$AKHOME/old-kernel-strings.txt" || abort '原内核读取失败。'
grep -q 'Linux version 6\.6\.57-' "$AKHOME/old-kernel-strings.txt" || abort '原启动镜像不是 6.6.57 内核，未写入分区。'
sync
ui_print '原启动镜像已备份并核验。' '测试构建：尚未经过本机启动验证。'
if [ -f "$SPLITIMG/ramdisk.cpio" ]; then
    unpack_ramdisk >> "$LOGFILE" 2>&1 || abort 'ramdisk 解包失败。'
    write_boot >> "$LOGFILE" 2>&1 || abort '启动镜像写入失败。'
else
    flash_boot >> "$LOGFILE" 2>&1 || abort '启动镜像写入失败。'
fi
NEW="$AKHOME/boot-new.img"
[ -s "$NEW" ] || abort '无法找到重打包镜像进行写入回读校验，请保留备份。'
SIZE=$("$BB" stat -c %s "$NEW")
case "$SIZE" in ''|*[!0-9]*) abort '重打包镜像长度无效。' ;; esac
"$BB" head -c "$SIZE" "$BLOCK" > "$AKHOME/readback.img" || abort '分区回读失败，请保留备份。'
"$BB" cmp "$NEW" "$AKHOME/readback.img" || abort '分区写入回读不一致，请恢复备份。'
sync
ui_print '启动镜像写入及回读校验完成。' "原启动镜像：$BACKUP_DIR/boot-before.img" "日志：$BACKUP_DIR/install.log"
