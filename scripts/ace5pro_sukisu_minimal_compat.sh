#!/usr/bin/env bash
# SukiSU builtin 40959: 6.6 ONLY, minimal compile compatibility.
# No 6.8+ LSM ID, 6.11+ KPM, or custom seccomp filtering changes.
set -euo pipefail

KSU="${1:-KernelSU}"
COMPAT="$(cd "$(dirname "${BASH_SOURCE[0]}")/sukisu_compat" && pwd)"
[[ -d "$KSU/kernel" ]] || { echo "::error::KernelSU dir missing"; exit 3; }
[[ -f "$KSU/kernel/kernel_includes.h" ]] || { echo "::error::Pinned SukiSU source layout missing"; exit 4; }

# Pinned 6.6 builtin needs an arch.h header that the upstream builtin tree
# does not include; copy only that missing compilation dependency.
if grep -qF '#include "arch.h"' "$KSU/kernel/kernel_includes.h" &&
   [[ ! -f "$KSU/kernel/include/arch.h" ]]; then
    install -m 0644 "$COMPAT/arch.h" "$KSU/kernel/include/arch.h"
    echo "Builtin arch.h dependency restored"
fi

# Fix EVENT_SERVICES and duplicate SELinux declarations only.
D="$KSU/kernel/supercall/dispatch.c"
U="$KSU/kernel/include/uapi/supercall.h"
R="$KSU/kernel/selinux/rules.c"
[[ -f "$D" && -f "$U" && -f "$R" ]] || {
    echo "::error::Pinned builtin dispatch/SELinux sources missing"; exit 5;
}
if grep -q "EVENT_SERVICES" "$D" &&
   ! grep -q "EVENT_SERVICES" "$U" &&
   grep -qF 'struct selinux_policy *pol, *old_pol = selinux_state.policy;' "$R"; then
    patch --batch --dry-run --forward -p1 -F0 -d "$KSU" < "$COMPAT/builtin-sync-fixes.patch"
    patch --batch --forward -p1 -F0 -d "$KSU" < "$COMPAT/builtin-sync-fixes.patch"
fi
grep -q "EVENT_SERVICES" "$U" || {
    echo "::error::SukiSU dispatch fix was not verified"; exit 6;
}
! grep -qF 'struct selinux_policy *pol, *old_pol = selinux_state.policy;' "$R" || {
    echo "::error::SukiSU SELinux duplicate declaration persists"; exit 7;
}

# The 6.6 tree should keep the original LSM API and seccomp semantics.
LSM="$KSU/kernel/hook/lsm_hook.c"
if [[ -f "$LSM" ]] && grep -q 'ksu_lsm_id' "$LSM"; then
    echo "::error::Unexpected 6.8+ LSM code in 6.6 trial"; exit 8;
fi
if [[ -f "$LSM" ]] && grep -q 'ksu_seccomp_allow_cache' "$LSM"; then
    echo "::error::Unexpected seccomp runtime rewrite in minimal trial"; exit 9;
fi
echo "PASS: 6.6 builtin compile fixes only, no extra runtime compatibility rewrites"
