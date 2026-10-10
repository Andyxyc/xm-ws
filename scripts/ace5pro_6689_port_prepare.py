#!/usr/bin/env python3
"""Port the verified minimal Ace5Pro SukiSU/SUSFS builder to official 6.6.89.

Upstream acknowledgments:
- cctv18/oppo_oplus_realme_sm8750: original builder (adapted, not copied blind)
- OnePlusOSS/android_kernel_common_oneplus_sm8750: PKR110 official source
- WildKernels/OnePlus_KernelSU_SUSFS: A16 Ace5Pro 6.6.89 manifest
- WildKernels/kernel_patches: dedicated 6.6.89 A16 HMBIRD patch set
- XiaoXin: user's known-booting 40830 6.6.89 AK3 image/reference

Only commit-pinned OnePlus and WildKernels source revisions are used.
No reference ZIP binary or script is included in the new build.
"""
from __future__ import annotations

import argparse
from pathlib import Path

OLD_CLONE = (
    "git clone --depth=1 https://github.com/cctv18/"
    "android_kernel_common_oneplus_sm8750 "
    "-b oneplus/sm8750_v_15.0.2_oneplus_13_6.6.66 common"
)
OLD_GUARD = (
    'test "$(git -C common rev-parse HEAD)" = '
    '"9a56e8288fc62e2047a142114faeb9467447311d" || '
    "{ echo 'Kernel source pin changed; refusing build'; exit 40; }"
)

SOURCE_SHA = "f4dd5c0457798af7e2e9cf5a6edce3447947d067"
WILD_PATCH_SHA = "41ae18b35d20e0c6ac04116785a4a1089528ae94"
BRANCH = "oneplus/sm8750_b_16.0.0_oneplus_ace5_pro"

CLONE = f'''git clone --depth=1 --filter=blob:none --no-checkout \
--branch {BRANCH} \
https://github.com/OnePlusOSS/android_kernel_common_oneplus_sm8750.git common
git -C common fetch --no-tags --depth=1 origin {SOURCE_SHA}
git -C common checkout --detach {SOURCE_SHA}
test "$(git -C common rev-parse HEAD)" = "{SOURCE_SHA}" || {{
  echo "Official PKR110 source version changed; aborting"; exit 40;
}}
grep -qx 'SUBLEVEL = 89' common/Makefile || {{
  echo "Official PKR110 kernel is not 6.6.89"; exit 41;
}}'''

HMBIRD = f'''# ===== Minimal PKR110 Android16 HMBIRD support from WildKernels =====
# 6.6.89 working reference has CONFIG_HMBIRD_SCHED=y, while stock
# OnePlusOSS PKR110 common uses CONFIG_SLIM_SCHED=y. Apply only the
# model-specific scheduler adaptation, not WildKernels' other optimizations.
echo "Applying known PKR110 A16 6.6.89 HMBIRD scheduler support..."
HMBIRD_FILES="$WORKDIR/kernel_workspace/ace5pro-hmbird"
mkdir -p "$HMBIRD_FILES"
HMBIRD_BASE="https://raw.githubusercontent.com/WildKernels/kernel_patches/{WILD_PATCH_SHA}/oneplus/hmbird"
curl -fLSs --retry 3 "$HMBIRD_BASE/deprecated/fengchi_OP-ACE-5-PRO_A16.patch" \
  -o "$HMBIRD_FILES/fengchi.patch"
curl -fLSs --retry 3 "$HMBIRD_BASE/overwriter.patch" \
  -o "$HMBIRD_FILES/overwriter.patch"
curl -fLSs --retry 3 "$HMBIRD_BASE/hmbird_config.patch" \
  -o "$HMBIRD_FILES/hmbird_config.patch"

cd "$WORKDIR/kernel_workspace/common"
for p in fengchi.patch overwriter.patch hmbird_config.patch; do
  echo "Checking $p..."
  patch --batch --dry-run -p1 -F3 --forward < "$HMBIRD_FILES/$p"
  patch --batch -p1 -F3 --forward < "$HMBIRD_FILES/$p"
done
[ -f drivers/of/overwriter/overwrite_configs/convert_configs.sh ] || {{
  echo "HMBIRD DT overlay converter missing; aborting"; exit 44;
}}
chmod 755 drivers/of/overwriter/overwrite_configs/convert_configs.sh
DEFCONFIG=arch/arm64/configs/gki_defconfig
# Explicitly request the scheduler seen in the working 6.6.89 Image.
sed -i '/^CONFIG_SLIM_SCHED=y$/d; /^CONFIG_SCHED_CLASS_EXT=y$/d' "$DEFCONFIG"
if ! grep -q '^CONFIG_HMBIRD_SCHED=y$' "$DEFCONFIG"; then
  echo "CONFIG_HMBIRD_SCHED=y" >> "$DEFCONFIG"
fi
if find . -name '*.rej' -type f -print -quit | grep -q .; then
  echo "HMBIRD patch rejected hunks found; aborting"; exit 45;
fi
echo "PASS: A16 6.6.89 vendor scheduler patch applied cleanly"
cd "$WORKDIR/kernel_workspace"

'''


def adapt(s: str) -> str:
    def replace_one(original: str, replacement: str, label: str) -> None:
        nonlocal s
        count = s.count(original)
        if count != 1:
            raise RuntimeError(f"Builder drift at {label}: found {count}")
        s = s.replace(original, replacement, 1)

    replace_one(OLD_CLONE + "\n" + OLD_GUARD, CLONE, "6.6.66 13->6.6.89 PKR110 source")
    replace_one(
        "# ===== 禁用 defconfig 检查 =====",
        HMBIRD + "# ===== 禁用 defconfig 检查 =====",
        "scheduler adaptation before compile",
    )
    if "oneplus_13_6.6.66 common" in s or "9a56e8288fc62e2047a142114faeb9467447311d" in s:
        raise RuntimeError("Old OnePlus 13 6.6.66 source remains")
    if "ace5pro_fix_uapi5.sh" not in s or "ace5pro_susfs_rebase_minimal.py" not in s:
        raise RuntimeError("Minimal SukiSU40959 UAPI5/SUSFS integration missing")
    if not all(w in s for w in [SOURCE_SHA, WILD_PATCH_SHA, "CONFIG_HMBIRD_SCHED=y"]):
        raise RuntimeError("Pin/scheduler verification missing")
    return s


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("builder", type=Path)
    args = ap.parse_args()
    original = args.builder.read_text(encoding="utf-8")
    updated = adapt(original)
    args.builder.write_text(updated, encoding="utf-8")
    print("PASS: Official PKR110 Android16 6.6.89 + pinned HMBIRD + SukiSU40959 UAPI5/SUSFS-only builder")


if __name__ == "__main__":
    main()
