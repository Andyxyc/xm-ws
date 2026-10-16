#!/usr/bin/env python3
"""Isolated AnyKernel3 installer flow checks for OnePlus Ace6 PLQ110.
Only fake getprop/uname, fake ak3-core and fake Image/sidecar are used.
The test has no access to physical device partitions and never flashes.
"""
from __future__ import annotations

import os
import pathlib
import re
import subprocess
import tempfile


ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "templates/ace6-plq110-sukisu-kpm-susfs-anykernel.sh"


def run_case(root: pathlib.Path, variables: dict[str, str], image: bool, sidecar: str | None) -> subprocess.CompletedProcess[str]:
    bin_dir = root / "bin"
    home = root / "ak3"
    tools = root / "tools"
    bin_dir.mkdir(exist_ok=True)
    home.mkdir(exist_ok=True)
    tools.mkdir(exist_ok=True)

    getprop = bin_dir / "getprop"
    getprop.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        'ro.product.device) printf "%s" "$MOCK_DEVICE";;\n'
        'ro.product.vendor.device) printf "%s" "$MOCK_VENDOR";;\n'
        'ro.build.version.release) printf "%s" "$MOCK_ANDROID";;\n'
        'ro.build.version.ota) printf "%s" "$MOCK_OTA";;\n'
        'ro.build.display.id) printf "%s" "$MOCK_DISPLAY";;\n'
        'ro.vendor.build.fingerprint) printf "%s" "$MOCK_FINGERPRINT";;\n'
        'esac\n',
        encoding="utf-8")
    uname = bin_dir / "uname"
    uname.write_text('#!/bin/sh\nif [ "$1" = "-r" ]; then printf "%s\\n" "$MOCK_KERNEL"; else /usr/bin/uname "$@"; fi\n')
    getprop.chmod(0o755)
    uname.chmod(0o755)

    (tools / "ak3-core.sh").write_text(
        'AKHOME="$FAKE_AKHOME"\n'
        'ui_print() { printf "%s\\n" "$*"; }\n'
        'abort() { printf "ABORT: %s\\n" "$*" >&2; exit 55; }\n'
        'split_boot() { echo SPLIT_CALLED >> "$CALL_LOG"; }\n'
        'flash_boot() { echo FLASH_CALLED >> "$CALL_LOG"; }\n',
        encoding="utf-8")

    image_path = home / "Image"
    if image:
        image_path.write_bytes(b"dummy no device image")
    if sidecar is not None:
        (home / "ACE6_FW500_ABI_VERIFIED.txt").write_text(sidecar, encoding="utf-8")

    env = os.environ.copy()
    env.update({
        "PATH": str(bin_dir) + os.pathsep + env["PATH"],
        "FAKE_AKHOME": str(home),
        "CALL_LOG": str(root / "flash-calls.txt"),
        "MOCK_DEVICE": "ktm",
        "MOCK_VENDOR": "ktm",
        "MOCK_ANDROID": "16",
        "MOCK_OTA": "PLQ110_16.0.10.500(CN01B110P02)",
        "MOCK_DISPLAY": "ColorOS 16",
        "MOCK_FINGERPRINT": "oneplus/PLQ110",
        "MOCK_KERNEL": "6.6.118-android15-8-g93e223c276e7-abogki500782043-4k",
    })
    env.update(variables)
    return subprocess.run(
        ["sh", str(SCRIPT)],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def main() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    for expected in (
        "BLOCK=boot", "SLOT_SELECT=active",
        "device.name1=ktm", "PLQ110_16.0.10.500",
        "SUSFS: Enabled", "KPM: Enabled",
        "作者：闲心中都是莫", "ACE6_FW500_ABI_VERIFIED.txt",
        "REAL_VENDOR_MODULE_ABI=PASS",
    ):
        if expected not in text:
            raise AssertionError("Required installer gate missing: " + expected)
    if re.search(r"^\s*(reboot|poweroff|fastboot|dd\s+if=)", text, re.M):
        raise AssertionError("Unexpected reboot or arbitrary partition-write command")
    subprocess.run(["sh", "-n", str(SCRIPT)], check=True)
    baseline = (
        "TARGET=PLQ110_16.0.10.500(CN01B110P02)\n"
        "REAL_VENDOR_MODULE_ABI=PASS\n"
    )
    cases = [
        ("wrong_model", {"MOCK_DEVICE": "alioth", "MOCK_VENDOR": "alioth"}, True, baseline, False),
        ("wrong_android", {"MOCK_ANDROID": "15"}, True, baseline, False),
        ("wrong_firmware", {"MOCK_OTA": "PLQ110_16.0.9.401(CN01)"}, True, baseline, False),
        ("wrong_kernel", {"MOCK_KERNEL": "6.6.66"}, True, baseline, False),
        ("missing_image", {}, False, baseline, False),
        ("missing_vendor_check", {}, True, None, False),
        ("bad_vendor_check", {}, True, "TARGET=PLQ110_16.0.10.500(CN01B110P02)\nREAL_VENDOR_MODULE_ABI=NO\n", False),
        ("dryrun_authorized", {}, True, baseline, True),
    ]
    for name, env, image, sidecar, permitted in cases:
        with tempfile.TemporaryDirectory(prefix=f"ace6-ak3-{name}-") as tmp:
            root = pathlib.Path(tmp)
            result = run_case(root, env, image, sidecar)
            log = root / "flash-calls.txt"
            calls = log.read_text() if log.exists() else ""
            if permitted:
                assert result.returncode == 0, (name, result.stderr, result.stdout)
                assert "SPLIT_CALLED" in calls and "FLASH_CALLED" in calls, (name, calls)
            else:
                assert result.returncode == 55, (name, result.returncode, result.stderr, result.stdout)
                assert not calls, f"Rejected {name} unexpectedly attempted boot manipulation"
            print(f"PASS: {name} (mock calls only)")
    print("PASS: isolated AnyKernel3 device/firmware/ABI gates, no auto reboot")


if __name__ == "__main__":
    main()
