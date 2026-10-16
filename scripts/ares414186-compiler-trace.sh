#!/usr/bin/env bash
# Read-only diagnostic wrapper for failing kernel cc-option tests.
# Writes compiler failure args/stderr to a CI artifact only, not to the device.
set -u
REAL_CC="$(command -v clang-15)"
LOG_FILE="$(printenv ARES_CC_TRACE_FILE || true)"
if [ -z "$LOG_FILE" ]; then
  exec "$REAL_CC" "$@"
fi
temp="$(mktemp)" || exit 80
"$REAL_CC" "$@" 2>"$temp"
rc=$?
if [ "$rc" -ne 0 ]; then
  {
    printf 'EXIT=%s\nARGS=' "$rc"
    printf '%q ' "$@"
    printf '\nSTDERR:\n'
    cat "$temp"
    printf '\n-----\n'
  } >> "$LOG_FILE" 2>/dev/null || true
fi
cat "$temp" >&2
rm -f "$temp"
exit "$rc"
