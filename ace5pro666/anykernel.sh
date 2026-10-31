### AnyKernel3 / OnePlus Ace 5 Pro
properties() { '
kernel.string=OnePlus Ace 5 Pro / 6.6.66 / SukiSU / SUSFS / KPM
do.devicecheck=1
do.modules=0
do.systemless=0
do.cleanup=1
do.cleanuponabort=0
device.name1=OP60EBL1
device.name2=PKR110
supported.versions=
supported.patchlevels=
supported.vendorpatchlevels=
'; }
BLOCK=boot
IS_SLOT_DEVICE=auto
SLOT_SELECT=active
RAMDISK_COMPRESSION=auto
PATCH_VBMETA_FLAG=auto
. tools/ak3-core.sh
. "$AKHOME/tools/ace-install.sh"
ui_print " "
ui_print "               心中都是墨"
ui_print " "
ui_print " OnePlus Ace 5 Pro"
ui_print " 6.6.66 / SukiSU / SUSFS 2.3.0 / KPM"
ui_print " "
cd "$AKHOME" || abort "Cannot open installer directory."
sha256sum -c kernel-image.sha256 >/dev/null 2>&1 || abort "Kernel file is damaged."
split_boot
# Check the installed boot kernel, including when Recovery has its own uname.
if ! strings "$SPLITIMG/kernel" | grep -q 'Linux version 6\.6\.[0-9]*-android15-8'; then
  magiskboot decompress "$SPLITIMG/kernel" "$AKHOME/kernel-current" >/dev/null 2>&1 || abort "Cannot read the installed kernel version."
  strings "$AKHOME/kernel-current" | grep -q 'Linux version 6\.6\.[0-9]*-android15-8' || abort "This boot requires android15-6.6 / KMI 8."
fi
if [ -f "$SPLITIMG/ramdisk.cpio" ]; then
  unpack_ramdisk
  write_boot
else
  flash_boot
fi
ui_print " "
ui_print " Installation complete."
