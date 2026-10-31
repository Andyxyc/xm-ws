#!/system/bin/sh
# Called by AK3 only after its standard unpack/repack has succeeded.
ace_flash_boot() {
  local block="$1" original="$2" image="$3"
  local size newsize dir point fs backup oldhash newhash readhash stamp
  [ -b "$block" ] || abort "Boot partition is unavailable."
  [ -s "$original" ] && [ -s "$image" ] || abort "Boot image is missing."
  size=$(wc -c < "$original")
  newsize=$(wc -c < "$image")
  [ "$size" -gt 0 ] && [ "$newsize" -le "$size" ] || abort "Boot image does not fit."
  [ $((size % 4096)) -eq 0 ] || abort "Invalid boot partition size."
  dir=
  for point in /data/adb/kernel-backups/OnePlus-Ace5-Pro /sdcard/KernelBackups/OnePlus-Ace5-Pro /cache/KernelBackups/OnePlus-Ace5-Pro; do
    fs=$(awk -v path="$point" '($2=="/" || path==$2 || index(path,$2"/")==1) && length($2)>best {best=length($2); type=$3} END {print type}' /proc/mounts)
    case "$fs" in ext4|f2fs|fuse|sdcardfs)
      if mkdir -p "$point" 2>/dev/null && [ -w "$point" ]; then dir=$point; break; fi ;;
    esac
  done
  [ "$dir" ] || abort "A mounted storage location is required for the boot backup."
  stamp="$(date +%Y%m%d-%H%M%S)-$$"
  backup="$dir/$(basename "$block")-$stamp.img"
  ui_print " Saving boot backup..."
  cp "$original" "$backup" || abort "Cannot save boot backup."
  oldhash=$(sha256sum "$original" | cut -d' ' -f1)
  [ "$(sha256sum "$backup" | cut -d' ' -f1)" = "$oldhash" ] || abort "Boot backup could not be verified."
  sync || abort "Cannot sync boot backup."
  printf '%s  %s\n' "$oldhash" "$(basename "$backup")" > "$backup.sha256" || abort "Cannot save backup checksum."
  # Pad a RAM file, then write the complete replacement in one pass.
  # There is no separate erase/zero pass over the physical partition.
  dd if=/dev/zero of="$AKHOME/boot-write.img" bs=4096 count=$((size / 4096)) 2>/dev/null || abort "Cannot prepare boot buffer."
  dd if="$image" of="$AKHOME/boot-write.img" bs=1048576 conv=notrunc 2>/dev/null || abort "Cannot prepare boot buffer."
  newhash=$(sha256sum "$AKHOME/boot-write.img" | cut -d' ' -f1)
  [ "${#newhash}" -eq 64 ] || abort "Cannot verify boot buffer."
  blockdev --setrw "$block" 2>/dev/null || :
  ui_print " Writing $(basename "$block")..."
  dd if="$AKHOME/boot-write.img" of="$block" bs=1048576 conv=fsync 2>/dev/null || abort "Boot write failed. Backup: $backup"
  sync || abort "Boot sync failed. Backup: $backup"
  dd if="$block" of="$AKHOME/boot-readback.img" bs=1048576 2>/dev/null || abort "Cannot read back boot. Backup: $backup"
  readhash=$(sha256sum "$AKHOME/boot-readback.img" | cut -d' ' -f1)
  [ "$newhash" = "$readhash" ] || abort "Boot readback differs. Backup: $backup"
  printf 'partition=%s\nbefore=%s\nafter=%s\n' "$block" "$oldhash" "$newhash" > "$backup.install.txt"
  ui_print " Boot verified."
  ui_print " Backup: $backup"
}
