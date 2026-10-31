#!/usr/bin/env bash
set -euo pipefail
ROOT="${GITHUB_WORKSPACE:-$(pwd)}"
cd "$ROOT"
mkdir -p build-result
COMMON="$ROOT/kernel-work/common"
OUT="$COMMON/out"
KERNEL_PIN=9a56e8288fc62e2047a142114faeb9467447311d
KSU_PIN=b16e899a555e9b96aa1225f049cd7274820ca5b8
AK3_PIN=41f04bdb4ee30a44e429c2c1131d5e8bb32b15f1
fetch_pin() {
  local url="$1" pin="$2" dest="$3"
  git init -q "$dest"
  git -C "$dest" remote add origin "$url"
  git -C "$dest" fetch -q --depth=1 origin "$pin"
  git -C "$dest" checkout -q --detach FETCH_HEAD
  test "$(git -C "$dest" rev-parse HEAD)" = "$pin"
}
case "$1" in
prepare)
  mkdir -p kernel-work
  fetch_pin https://github.com/cctv18/android_kernel_common_oneplus_sm8750.git "$KERNEL_PIN" "$COMMON"
  fetch_pin https://github.com/SukiSU-Ultra/SukiSU-Ultra.git "$KSU_PIN" kernel-work/KernelSU
  python3 ace5pro666/prepare.py "$COMMON" "$ROOT/kernel-work/KernelSU"
  (cd "$COMMON" && git diff --binary) > build-result/kernel-source.patch
  (cd kernel-work/KernelSU && git diff --binary) > build-result/sukisu-source.patch
  ;;
compile)
  export CCACHE_DIR="$HOME/.cache/ccache"
  export CCACHE_BASEDIR="$ROOT"
  export CCACHE_NOHASHDIR=true
  ccache -M 2G
  cd "$COMMON"
  # Official version formula: 40000 + fixed main commit count 3935 - 2815 = 41120.
  # Freeze the two upstream Makefile inputs; keep builtin b16 source identity.
  ARGS=(O=out ARCH=arm64 LLVM=-18 CC="ccache clang-18" LD=ld.lld-18 HOSTCC=clang-18 HOSTLD=ld.lld-18 GITHUB_COMMITS=3935 KSU_GITHUB_VER=4.3.0 KSU_VERSION_FULL=v4.3.0-b16e899a@builtin+708f083c)
  make "${ARGS[@]}" gki_defconfig 2>&1 | tee "$ROOT/build-result/defconfig.log"
  # Generate the actual UAPI headers before the source-integrated preinit runner.
  make "${ARGS[@]}" headers_install INSTALL_HDR_PATH="$OUT/usr" 2>&1 | tee "$ROOT/build-result/headers.log"
  make -j"$(nproc)" "${ARGS[@]}" Image modules 2>&1 | tee "$ROOT/build-result/compile.log"
  test -s "$OUT/arch/arm64/boot/Image"
  cp "$OUT/arch/arm64/boot/Image" "$ROOT/build-result/Image.raw"
  ;;
package)
  fetch_pin https://github.com/osm0sis/AnyKernel3.git "$AK3_PIN" kernel-work/AnyKernel3
  mkdir -p build-result/kpm
  curl -fLSs --retry 3 https://raw.githubusercontent.com/SukiSU-Ultra/SukiSU_patch/eec45788c9a115e5498040298133336d6b6071dd/kpm/kpimg -o build-result/kpm/kpimg
  curl -fLSs --retry 3 https://raw.githubusercontent.com/SukiSU-Ultra/SukiSU_patch/eec45788c9a115e5498040298133336d6b6071dd/kpm/kptools-linux -o build-result/kpm/kptools-linux
  chmod 755 build-result/kpm/kptools-linux
  python3 ace5pro666/kpm_postprocess.py --tool build-result/kpm/kptools-linux --before "$OUT/arch/arm64/boot/Image" --kpimg build-result/kpm/kpimg --system-map "$OUT/System.map" --output "$ROOT/build-result/Image.kpm" --report build-result/kpm-entry.json --log build-result/kpm.log
  python3 ace5pro666/package.py "$COMMON" kernel-work/AnyKernel3 build-result/Image.kpm
  ;;
*) exit 2 ;;
esac
