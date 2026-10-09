#!/usr/bin/env bash
# Correct the pinned SukiSU builtin v2->v5 UAPI backport for the Ace5Pro
# Android16 / Linux6.6 minimal SUSFS trial.
# Strictly refuse missing/incompatible sources; do not forge a UAPI version
# unless the required driver and dispatch implementations exist.
set -euo pipefail

KSU_DIR="${1:?usage: ace5pro_fix_uapi5.sh KernelSU-directory}"
PATCH_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/ksu_uapi_sync/builtin-uapi5.patch"
HEADER="$KSU_DIR/kernel/include/uapi/supercall.h"
DRIVER="$KSU_DIR/kernel/supercall/supercall.c"
DISPATCH="$KSU_DIR/kernel/supercall/dispatch.c"

for f in "$PATCH_FILE" "$HEADER" "$DRIVER" "$DISPATCH"; do
    [[ -f "$f" ]] || { echo "::error::Required UAPI source not found: $f"; exit 11; }
done

get_uapi() {
    sed -nE 's/.*KERNEL_SU_UAPI_VERSION,[[:space:]]*([0-9]+)\).*/\1/p' "$HEADER" | head -n1
}
CURRENT="$(get_uapi)"
case "$CURRENT" in
    2)
        # Use the known audited patch, never change the version using an
        # isolated sed that could claim unimplemented driver capabilities.
        patch --batch -p1 -F0 --forward --dry-run -d "$KSU_DIR" < "$PATCH_FILE"
        patch --batch -p1 -F0 --forward -d "$KSU_DIR" < "$PATCH_FILE"
        ;;
    5)
        echo "UAPI5 already present: verifying actual prerequisites"
        ;;
    *)
        echo "::error::Unexpected pinned SukiSU UAPI version: $CURRENT"
        exit 12
        ;;
esac

[[ "$(get_uapi)" = 5 ]] || { echo "::error::UAPI5 backport not effective"; exit 13; }
grep -qF 'KSU_GET_INFO_FLAG_BUNDLED' "$HEADER" || {
    echo "::error::UAPI5 bundled capability flag missing"; exit 14;
}
# These features already exist in the pinned builtin implementation. Verify
# their real source and do not merely set the header version to 5.
grep -qF 'KSU_DRIVER_PERMISSION_SU_SESSION' "$DRIVER" || {
    echo "::error::Scoped su-session FD driver not implemented"; exit 15;
}
grep -qF 'EVENT_SERVICES' "$DISPATCH" || {
    echo "::error::Services event support not implemented"; exit 16;
}
grep -qF 'cmd.uapi_version = KERNEL_SU_UAPI_VERSION;' "$DISPATCH" || {
    echo "::error::Kernel info ioctl does not expose UAPI version"; exit 17;
}

if grep -RqF '[object Object]' "$HEADER" "$DRIVER" "$DISPATCH"; then
    echo "::error::Malformed template remains in runtime kernel sources"
    exit 18
fi
echo "PASS: SukiSU builtin UAPI=5, scoped su-session, services event, flags and info ioctl verified"
