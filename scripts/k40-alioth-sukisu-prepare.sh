#!/usr/bin/env bash
# Redmi K40/alioth — SukiSU Ultra Non-GKI built-in integration.
# Author: 闲鱼 心中都是莫
# Upstream kernel: zfdx123/kernel_xiaomi_alioth (GPL kernel, full credits preserved)
# Upstream root: SukiSU-Ultra/SukiSU-Ultra GPL-2.0 kernel component.
# Based on official SukiSU non-GKI manual hook documentation.
# No flashing, no changes to the user's phone or existing data/modules.
set -euo pipefail

KERNEL_ROOT="${1:?usage: k40-alioth-sukisu-prepare.sh path-to-kernel-tree}"
SOURCE_REPO="zfdx123/kernel_xiaomi_alioth"
SOURCE_SHA="8b19a1dd26ae283a2bfc33781905255339aae485"
SUKI_SHA="6c284e957feaa9a388a9f1c37dc4ec80d95e434b"
WORKSPACE="${GITHUB_WORKSPACE:-$(cd "$(dirname "$0")/.." && pwd)}"

error() { printf '::error::K40 NON-GKI: %s\n' "$*" >&2; exit 1; }
note() { printf '\033[1;36m[K40/alioth] %s\033[0m\n' "$*"; }

[[ -f "$KERNEL_ROOT/Makefile" && -d "$KERNEL_ROOT/arch/arm64" ]] || error "Alioth source not found"
[[ "$(git -C "$KERNEL_ROOT" rev-parse HEAD)" == "$SOURCE_SHA" ]] || error "Kernel source commit drift"
grep -qxF 'SUBLEVEL = 325' "$KERNEL_ROOT/Makefile" || error "Expected Linux 4.19.325"
grep -qxF 'VERSION = 4' "$KERNEL_ROOT/Makefile" || error "Expected 4.19 major"
grep -qxF 'PATCHLEVEL = 19' "$KERNEL_ROOT/Makefile" || error "Expected 4.19 minor"
[[ -s "$KERNEL_ROOT/arch/arm64/configs/alioth_defconfig" ]] || error "Alioth defconfig missing"
grep -qF 'CONFIG_BOARD_ALIOTH=y' "$KERNEL_ROOT/arch/arm64/configs/alioth_defconfig" || error "Not an alioth device tree"
grep -qF 'CONFIG_SCHED_WALT=y' "$KERNEL_ROOT/arch/arm64/configs/alioth_defconfig" || error "Original Xiaomi WALT scheduler missing"
grep -qF 'config KSU_MANUAL_HOOK' "$KERNEL_ROOT/init/Kconfig" || error "Non-GKI manual hook Kconfig missing"
grep -qF 'ksu_handle_execveat' "$KERNEL_ROOT/fs/exec.c" || error "Alioth KSU manual exec hook missing"
grep -qF 'ksu_handle_faccessat' "$KERNEL_ROOT/fs/open.c" || error "Alioth KSU manual faccessat hook missing"
grep -qF 'ksu_handle_sys_reboot' "$KERNEL_ROOT/kernel/reboot.c" || error "Alioth KSU manual FD hook missing"

cd "$KERNEL_ROOT"
[[ ! -e drivers/kernelsu && ! -L drivers/kernelsu ]] || error "Unexpected preexisting kernelsu integration"
[[ ! -e KernelSU ]] || error "KernelSU path already exists: refusing to replace"

note "Pinning current builtin branch of official SukiSU Ultra"
git clone --quiet --depth=1 --single-branch --branch builtin \
    https://github.com/SukiSU-Ultra/SukiSU-Ultra.git KernelSU
[[ "$(git -C KernelSU rev-parse HEAD)" == "$SUKI_SHA" ]] || error "SukiSU builtin commit moved; aborting"

# Kernel SukiSU 4.2.0 defaults to UAPI2, while latest matching manager uses
# UAPI5. Backport existing protocol declarations only AFTER verifying the
# scoped fd driver, services event and info ioctl really exist.
SUHEAD="KernelSU/kernel/include/uapi/supercall.h"
[[ -f "$SUHEAD" ]] || error "SukiSU UAPI header missing"
grep -qF 'KERNEL_SU_UAPI_VERSION, 2' "$SUHEAD" || error "Unexpected UAPI baseline"
grep -qF 'KSU_DRIVER_PERMISSION_SU_SESSION' KernelSU/kernel/supercall/supercall.c || error "Scoped SU fd not implemented"
grep -qF 'EVENT_SERVICES' KernelSU/kernel/supercall/dispatch.c || error "Service event not implemented"
grep -qF 'cmd.uapi_version = KERNEL_SU_UAPI_VERSION' KernelSU/kernel/supercall/dispatch.c || error "Info ioctl missing"
[[ -f "$WORKSPACE/scripts/ksu_uapi_sync/builtin-uapi5.patch" ]] || error "UAPI5 patch unavailable"
patch --batch --dry-run --forward --fuzz=0 -p1 -d KernelSU \
    < "$WORKSPACE/scripts/ksu_uapi_sync/builtin-uapi5.patch"
patch --batch --forward --fuzz=0 -p1 -d KernelSU \
    < "$WORKSPACE/scripts/ksu_uapi_sync/builtin-uapi5.patch"
grep -qF 'KERNEL_SU_UAPI_VERSION, 5' "$SUHEAD" || error "UAPI5 not effective"
grep -qF 'KSU_GET_INFO_FLAG_BUNDLED' "$SUHEAD" || error "UAPI5 feature flag missing"

# Current builtin sync may omit kernel/include/arch.h: provide only the
# original arch header from existing source-controlled compatibility files.
if grep -qF '#include "arch.h"' KernelSU/kernel/kernel_includes.h &&
  [[ ! -f KernelSU/kernel/include/arch.h ]]; then
    install -m 0644 "$WORKSPACE/scripts/sukisu_compat/arch.h" KernelSU/kernel/include/arch.h
fi

# Leave ReSukiSU-compatible syscall hooks wired into the same kernel tree.
# With CONFIG_KSU_SUSFS=n, SukiSU provides the original user-pointer
# signatures compatible with alioth hooks; do not use the alternative
# CONFIG_KSU_SUSFS=y struct-filename hooks on this unverified source.
ln -s ../KernelSU/kernel drivers/kernelsu
printf '\nobj-$(CONFIG_KSU) += kernelsu/\n' >> drivers/Makefile
printf '\nsource "drivers/kernelsu/Kconfig"\n' >> drivers/Kconfig

defconfig="arch/arm64/configs/alioth_defconfig"
scripts/config --file "$defconfig" \
    --enable KSU \
    --enable KSU_MANUAL_HOOK \
    --enable KALLSYMS \
    --enable KALLSYMS_ALL \
    --disable KSU_FEATURE_ADBROOT \
    --disable KSU_SUSFS \
    --disable KPM \
    --disable UNAME_OVERRIDE

# Do not touch CPU governor, frequencies, WALT, Xiaomi DT or vendor drivers.
grep -qxF 'CONFIG_SCHED_WALT=y' "$defconfig" || error "Vendor WALT config accidentally removed"
grep -qxF 'CONFIG_KSU=y' "$defconfig" || error "KernelSU not configured"
grep -qxF 'CONFIG_KSU_MANUAL_HOOK=y' "$defconfig" || error "Manual hooks not configured"
grep -qxF '# CONFIG_KSU_SUSFS is not set' "$defconfig" || error "Unsafe SUSFS default"
grep -qxF '# CONFIG_KPM is not set' "$defconfig" || error "Unsafe KPM default"
grep -qxF '# CONFIG_UNAME_OVERRIDE is not set' "$defconfig" || error "UNAME override must be disabled"
note "SukiSU UAPI5 and legacy 4.19 manual hooks prepared; no SUSFS, KPM or scheduler changes"

cat > "$KERNEL_ROOT/K40_SOURCE_PROVENANCE.txt" <<EOF
DEVICE=Redmi K40
CODENAME=alioth
KERNEL_SOURCE=https://github.com/$SOURCE_REPO
KERNEL_COMMIT=$SOURCE_SHA
KERNEL_VERSION=4.19.325
SUKISU_SOURCE=https://github.com/SukiSU-Ultra/SukiSU-Ultra
SUKISU_BRANCH=builtin
SUKISU_COMMIT=$SUKI_SHA
SUKISU_RELEASE=v4.2.0
SUKISU_UAPI=5
SUSFS=disabled_for_initial_compatibility_trial
KPM=disabled
MANUAL_HOOK=yes
CONFIG=alioth_defconfig
ROM_CROSS_COMPATIBILITY=not_verified
REAL_DEVICE_TEST=not_performed
AUTHOR=闲鱼 心中都是莫
UPSTREAM_CREDITS=LeviMarvin_zfdx123_SukiSUUltra
EOF
