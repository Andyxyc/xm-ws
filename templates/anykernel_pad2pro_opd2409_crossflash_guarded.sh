### AnyKernel3 Ramdisk Mod Script
# OPD2413 physical hardware with OPD2409_15.0.1.501(CN01) cross-flashed ROM
# The software-visible model is NOT sufficient proof of kernel vendor ABI compatibility.
# 6.6.57 source-built artifact for review only. NO DEVICE FLASHING.
# Author: 闲心中都是莫

properties() { printf '%s\n' '
kernel.string=Pad2Pro hardware / OPD2409 ROM / 6.6.57 SukiSU (UNVERIFIED)
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
ui_print " 一加平板 2 Pro 硬件 / OPPO Pad 4 Pro 跨刷系统"
ui_print " 固件：OPD2409_15.0.1.501(CN01)"
ui_print " 内核：6.6.57 / 管理器：SukiSU 40996"
ui_print " KPM：Enabled"
ui_print " SUSFS：Enabled"
ui_print " 原厂调度：未添加自定义调度"
ui_print " 作者：闲心中都是莫"
ui_print "================================================"
ui_print " 尚未取得本机 boot.img 和厂商模块 ABI 校验结果。"
ui_print " 此包只用于核对编译镜像，不允许安装。"
ui_print " 请保留现有 boot / vendor_boot / dtbo，勿刷错槽位。"

# Fail closed even if any software model properties have been spoofed by crossflash.
# Never call split_boot, unpack_ramdisk, write_boot, flash_boot, dd or fastboot.
abort "跨刷设备的原厂启动镜像和厂商 ABI 未核实，已终止刷写。"
