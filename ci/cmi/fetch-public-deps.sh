#!/usr/bin/env bash
set -euo pipefail
[ "${GITHUB_REF:?}" = "refs/heads/cmi-miui12510-driver-build-20261019" ] || exit 2
ROOT="${GITHUB_WORKSPACE:?}"
WORK="${RUNNER_TEMP:?}/cmi-public-deps"
OUT="$ROOT/public-deps"
mkdir "$WORK" "$OUT"
fetch_archive() {
  local name="$1" url="$2" sha="$3"
  git init "$WORK/$name"
  git -C "$WORK/$name" fetch --depth=1 "$url" "$sha"
  git -C "$WORK/$name" checkout --detach FETCH_HEAD
  [ "$(git -C "$WORK/$name" rev-parse HEAD)" = "$sha" ] || return 2
  git -C "$WORK/$name" archive --format=tar HEAD | gzip -n > "$OUT/$name.tar.gz"
  printf '%s %s %s\n' "$name" "$sha" "$url" >> "$OUT/SOURCES.txt"
}
CLANG_URL='https://android.googlesource.com/platform/prebuilts/clang/host/linux-x86/+archive/refs/tags/android-11.0.0_r3/clang-r377782c.tar.gz'
curl --fail --location --retry 2 --connect-timeout 30 --max-time 1200 "$CLANG_URL" -o "$OUT/clang-r377782c.tar.gz"
# The previous generated archive SHA failed. Validate all files and modes
# against the immutable AOSP android-11.0.0_r3 subtree instead of trusting a
# renamed archive, ignoring a failed check, or accepting a moving branch.
python3 "$ROOT/ci/cmi/verify-git-archive.py" "$OUT/clang-r377782c.tar.gz" \
  4c73695e3f20f85d0e50b3001806cff59bf7f3dc "$OUT/clang-tree-verification.json"
printf 'clang Android-r377782c-10.0.5 %s\n' "$CLANG_URL" >> "$OUT/SOURCES.txt"
mkdir "$WORK/clang-r377782c"
tar -xzf "$OUT/clang-r377782c.tar.gz" -C "$WORK/clang-r377782c"
fetch_archive gcc64 https://android.googlesource.com/platform/prebuilts/gcc/linux-x86/aarch64/aarch64-linux-android-4.9 606f80986096476912e04e5c2913685a8f2c3b65
fetch_archive gcc32 https://android.googlesource.com/platform/prebuilts/gcc/linux-x86/arm/arm-linux-androideabi-4.9 b0c6a654327ca8796bed1e61dffcf523d04dceaa
fetch_archive wlan https://github.com/MiCode/vendor_qcom_opensource_wlan.git 89be27c877aa52bf2fb53ca1ced645d7779bd51a
fetch_archive data-kernel https://github.com/MiCode/vendor_qcom_opensource_data-kernel.git 6f75eda790703951ab719aefab274934ee689a4e
export PATH="$WORK/clang-r377782c/bin:$WORK/gcc64/bin:$WORK/gcc32/bin:$PATH"
clang --version | tee "$OUT/clang-version.txt"
aarch64-linux-androidkernel-ld --version | tee "$OUT/linker-version.txt"
arm-linux-androideabi-as --version | tee "$OUT/assembler32-version.txt"
grep -F '10.0.5' "$OUT/clang-version.txt"
grep -F 'r377782c' "$OUT/clang-version.txt"
grep -F '2.27.0.20170315' "$OUT/linker-version.txt"
printf 'unsigned long cmi_compiler_probe(unsigned long x) { return x + 1; }\n' > "$OUT/probe.c"
clang --target=aarch64-linux-gnu -ffreestanding -fno-stack-protector -c "$OUT/probe.c" -o "$OUT/probe.o"
aarch64-linux-androidkernel-ld -r "$OUT/probe.o" -o "$OUT/probe-linked.o"
readelf -h "$OUT/probe-linked.o" | tee "$OUT/probe-elf.txt"
grep -F AArch64 "$OUT/probe-elf.txt"
test -f "$WORK/wlan/qcacld-3.0/configs/qca6390_defconfig"
test -d "$WORK/wlan/qca-wifi-host-cmn"
test -d "$WORK/wlan/fw-api"
printf '公开工具链与原厂驱动源码。Clang/BFD 的 ARM64 编译链接探针通过。\n不是小米 10 Pro 内核产物，不是刷机包；不包含聊天、设备资料或自定义补丁。\n' > "$OUT/README.txt"
(cd "$OUT"; find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS)
