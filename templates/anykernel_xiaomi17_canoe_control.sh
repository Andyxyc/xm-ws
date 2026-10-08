### AnyKernel3 Ramdisk Mod Script
## Xiaomi 17 series canoe control installer
## Mirrors Kokuban canoe boot-only flow.

properties() { printf '%s\n' '
kernel.string=Xiaomi17-Kokuban-Control
do.devicecheck=1
do.modules=0
do.systemless=0
do.cleanup=1
do.cleanuponabort=0
device.name1=nezha
device.name2=popsicle
device.name3=pandora
device.name4=pudding
supported.versions=
supported.patchlevels=
supported.vendorpatchlevels=
'; }

BLOCK=/dev/block/by-name/boot
IS_SLOT_DEVICE=1
RAMDISK_COMPRESSION=auto
PATCH_VBMETA_FLAG=auto

. tools/ak3-core.sh

ui_print "========================================"
ui_print " Xiaomi 17 Series Kokuban 6.12.23"
ui_print " BOOT CONTROL - no root / no SUSFS"
ui_print " no KPM / no xiaomo FUSE patches"
ui_print "========================================"

split_boot
flash_boot

ui_print "✅ Control kernel flashed."
