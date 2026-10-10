### AnyKernel3 Ramdisk Mod Script
## Redmi K40 / Xiaomi alioth (non-GKI Linux 4.19) - TEST ONLY
## Based on osm0sis/AnyKernel3; kernel based on zfdx123 / LeviMarvin.
## SukiSU Ultra official builtin integration.
## Author: 闲鱼 心中都是莫

properties() { printf '%s\n' '
kernel.string=Redmi K40 alioth Non-GKI SukiSU Ultra 4.2 UAPI5 - UNTESTED
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

# Never flash DTBO/VBMETA/VENDOR partitions or modify installed modules.
BLOCK=boot
IS_SLOT_DEVICE=auto
RAMDISK_COMPRESSION=auto
PATCH_VBMETA_FLAG=auto

. tools/ak3-core.sh

ui_print "=============================================="
ui_print " Redmi K40 (alioth) Non-GKI SukiSU 4.2.0"
ui_print " Kernel: Linux 4.19.325 / AArch64"
ui_print " SukiSU: builtin, UAPI5"
ui_print " SUSFS: OFF / KPM: OFF"
ui_print " Config: original Xiaomi WALT/drivers"
ui_print " Author: 闲鱼 心中都是莫"
ui_print " TEST BUILD: Not guaranteed across MIUI/HyperOS"
ui_print "=============================================="

# Verify at least two stock hardware identifiers. User-modified prop spoofing
# can invalidate checks; this is NOT a secure hardware authenticity guarantee.
MODEL="$(getprop ro.product.device 2>/dev/null | tr -d '\r\n ')"
VENDOR="$(getprop ro.product.vendor.device 2>/dev/null | tr -d '\r\n ')"
BOARD="$(getprop ro.build.product 2>/dev/null | tr -d '\r\n ')"
HW="$(getprop ro.hardware 2>/dev/null | tr -d '\r\n ')"
ui_print "Device: system=$MODEL vendor=$VENDOR board=$BOARD hardware=$HW"
case " $MODEL $VENDOR $BOARD " in
    *" alioth "*) ;;
    *) abort "Not alioth: refusing boot partition update" ;;
esac
for value in "$MODEL" "$VENDOR"; do
    case "$value" in
        ""|alioth) ;;
        *) abort "Conflicting device identity ($value). Refusing flash" ;;
    esac
done
KERNEL="$(uname -r 2>/dev/null || true)"
case "$KERNEL" in
    4.19.*) ;;
    *) abort "Current kernel is not Linux 4.19 ($KERNEL); refusing flash" ;;
esac
ui_print "Current kernel: $KERNEL"
ui_print "Do not flash if vendor drivers differ; keep matching stock boot.img."
test -s "$AKHOME/Image.gz-dtb" || abort "Missing compiled Image.gz-dtb"

# Preserve existing ramdisk content; update only current A/B boot partition.
split_boot
flash_boot
sync
ui_print "Finished. No system/data/modules or DTBO modified."
