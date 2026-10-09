#!/usr/bin/env python3
"""One-time, exact-artifact LanZouCloud upload for Ace 5 Pro SUSFS-only trial.

The original (untested) AK3 ZIP is copied byte-for-byte from one successful,
exact GitHub Actions artifact. This script never recompiles, repacks, renames,
replaces, deletes, or modifies existing cloud files or directories.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import zipfile
from urllib.parse import urlsplit

from publish_lanzou_ak3 import ROOT_FOLDER, VERSION_FOLDER, PublishError, make_secure_client

REPOSITORY = "Andyxyc/xm-ws"
SOURCE_RUN_ID = 37939160448
SOURCE_ARTIFACT_NAME = (
    "Ace5Pro_Android16_6.6.66_SukiSU40959_"
    "SUSFS_Minimal_UNTESTED_37939160448"
)
ZIP_NAME = (
    "Android16_Kernel6.6.66_OnePlusAce5Pro_PKR110_"
    "SukiSU40959_SUSFSOnly_MINIMAL_UNTESTED_run37939160448.zip"
)
REMOTE_MODEL_DIR = "一加Ace5Pro"
MAX_SIZE = 75 * 1024 * 1024


def download_source(directory: Path) -> tuple[Path, str]:
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        raise PublishError("GH_TOKEN was not supplied")
    environment = os.environ.copy()
    environment["GH_TOKEN"] = token
    result = subprocess.run(
        ["gh", "run", "download", str(SOURCE_RUN_ID),
         "--repo", REPOSITORY, "--name", SOURCE_ARTIFACT_NAME,
         "--dir", str(directory)],
        env=environment, capture_output=True, text=True, timeout=180,
        check=False,
    )
    if result.returncode:
        raise PublishError(f"GitHub artifact fetch failed with code {result.returncode}")
    files = sorted(p.name for p in directory.iterdir())
    expected = sorted((ZIP_NAME, ZIP_NAME + ".sha256"))
    if files != expected:
        raise PublishError(f"Unexpected source artifact contents: {files}")
    archive = directory / ZIP_NAME
    checksum_file = directory / (ZIP_NAME + ".sha256")
    text = checksum_file.read_text(encoding="ascii").strip()
    match = re.fullmatch(r"([0-9a-fA-F]{64})  \*?(.+)", text)
    if not match or match.group(2) != ZIP_NAME:
        raise PublishError("Original SHA256 manifest format or filename unexpected")
    if not archive.is_file() or not (1024 * 1024 < archive.stat().st_size < MAX_SIZE):
        raise PublishError("Source AK3 has invalid size")
    sha = hashlib.sha256()
    with archive.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(chunk)
    digest = sha.hexdigest()
    if digest.lower() != match.group(1).lower():
        raise PublishError("SHA256 mismatch with original build artifact")

    with zipfile.ZipFile(archive, "r") as z:
        infos = z.infolist()
        if len(infos) > 250:
            raise PublishError("Source AK3 contains too many entries")
        for member in infos:
            segments = member.filename.replace("\\", "/").split("/")
            if member.filename.startswith("/") or ".." in segments or "\x00" in member.filename:
                raise PublishError("Unexpected unsafe ZIP member path")
            if (member.external_attr >> 16) & 0o170000 == 0o120000:
                raise PublishError("Symbolic link in source archive")
        if z.testzip() is not None:
            raise PublishError("Source AK3 failed ZIP CRC integrity check")
        names = set(z.namelist())
        required = {"anykernel.sh", "Image", "tools/ak3-core.sh",
                    "minimal-susfs-test-info.txt"}
        if not required.issubset(names):
            raise PublishError(f"Missing AK3 members: {sorted(required - names)}")
        if z.getinfo("Image").file_size < 6_000_000:
            raise PublishError("Kernel Image unreasonably small")
        metadata = z.read("minimal-susfs-test-info.txt").decode("utf-8")
        for requirement in (
            "TARGET=OnePlus Ace 5 Pro",
            "DEVICE=PKR110",
            "OS=Android 16",
            "STOCK_KERNEL_BASE=6.6.66",
            "SUKISU=40959",
            "SUSFS=builtin_minimal",
            "KPM=disabled",
            "SERIAL_BINDING=none",
            "PRODUCTION_RELEASE=no",
            "REAL_DEVICE_STABILITY_TEST=not_performed",
        ):
            if requirement not in metadata.splitlines():
                raise PublishError(f"Source ZIP metadata missing {requirement}")
        script = z.read("anykernel.sh").decode("utf-8")
        if ('BLOCK=boot' not in script
                or 'PKR110' not in script
                or 'OP60EBL1' not in script
                or '6.6.66-android15-8-' not in script):
            raise PublishError("Source installer safety checks missing")
    return archive, digest


def cloud_cookies() -> dict:
    uid = os.environ.get("LANZOU_YLOGIN", "")
    phpdisk = os.environ.get("LANZOU_PHPDISK_INFO", "")
    if not uid.isdecimal() or not phpdisk.strip():
        raise PublishError("Configured LanZouCloud session missing or malformed")
    result = {"ylogin": uid, "phpdisk_info": phpdisk}
    if os.environ.get("LANZOU_PHPSESSID"):
        result["PHPSESSID"] = os.environ["LANZOU_PHPSESSID"]
    return result


def existing_dir(client, parent_id: int, name: str) -> int:
    matches = [x for x in client.get_dir_list(parent_id) if x.name == name]
    if len(matches) != 1:
        raise PublishError(f"Expected exactly one existing LanZou folder {name!r}; got {len(matches)}")
    return int(matches[0].id)


def share_metadata(client, file_id: int) -> dict:
    """Read native share URL, never manufacture a link or expose cookies."""
    from lanzou.api import LanZouCloud
    try:
        info = client.get_share_info(file_id, is_file=True)
        if info.code != LanZouCloud.SUCCESS:
            return {"share_status": f"not_available_code_{info.code}"}
        url = str(info.url or "")
        parsed = urlsplit(url)
        host = (parsed.hostname or "").lower()
        if (parsed.scheme != "https" or not host
                or not (host.endswith("lanzou.com")
                        or host.endswith("lanzouu.com")
                        or host.endswith("lanzoux.com")
                        or host.endswith("lanzoub.com")
                        or host.endswith("lanzous.com")
                        or host.endswith("lanzoui.com")
                        or host.endswith("woozooo.com"))):
            return {"share_status": "provider_link_not_validated"}
        return {
            "share_status": "available",
            "share_url": url,
            "extraction_code": str(info.pwd or ""),
        }
    except (OSError, ValueError, KeyError, AttributeError, PublishError) as exc:
        return {"share_status": f"provider_readback_unavailable_{type(exc).__name__}"}


def main() -> int:
    from lanzou.api import LanZouCloud

    if os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise PublishError("Unrecognized GitHub source repository")
    receipt = {
        "source_run_id": SOURCE_RUN_ID,
        "source_artifact_name": SOURCE_ARTIFACT_NAME,
        "remote_folder": f"{ROOT_FOLDER}/{VERSION_FOLDER}/{REMOTE_MODEL_DIR}",
        "remote_name": ZIP_NAME,
        "content_readback": "not_performed",
        "real_device_stability": "NOT_TESTED",
        "status": "started",
    }
    try:
        with tempfile.TemporaryDirectory(prefix="ace5pro-susfs-trial-") as tmp:
            archive, digest = download_source(Path(tmp))
            receipt["local_sha256_verified"] = digest
            receipt["local_zip_size_bytes"] = archive.stat().st_size
            print("Validated exact source artifact SHA256, ZIP CRC and boot-only installer")
            client = make_secure_client()
            if client.login_by_cookie(cloud_cookies()) != LanZouCloud.SUCCESS:
                raise PublishError("LanZouCloud login failed or session expired")
            parent = -1
            for segment in (ROOT_FOLDER, VERSION_FOLDER, REMOTE_MODEL_DIR):
                parent = existing_dir(client, parent, segment)
            before = list(client.get_file_list(parent))
            matches = [f for f in before if f.name == ZIP_NAME]
            if matches:
                if len(matches) != 1:
                    raise PublishError("Existing duplicate remote names; refusing")
                receipt["status"] = "already_exists_unverified"
                receipt["remote_file_id"] = int(matches[0].id)
                print("SKIP: exact remote filename exists; never overwrite", flush=True)
            else:
                captured = []
                result = client.upload_file(
                    str(archive), parent,
                    uploaded_handler=lambda file_id, is_file: captured.append(int(file_id))
                    if is_file else None,
                )
                if result != LanZouCloud.SUCCESS:
                    raise PublishError(f"LanZouCloud upload failed (code {result})")
                after = list(client.get_file_list(parent))
                found = [f for f in after if f.name == ZIP_NAME]
                if len(found) != 1:
                    raise PublishError("Upload returned but remote name not uniquely verified")
                if captured and captured[-1] != int(found[0].id):
                    raise PublishError("Uploaded file ID differs from remote metadata readback")
                receipt["status"] = "uploaded_with_metadata_readback"
                receipt["remote_file_id"] = int(found[0].id)
                print("Uploaded to existing Chinese Ace5Pro model folder", flush=True)
            receipt.update(share_metadata(client, receipt["remote_file_id"]))
            # Share URL/code are intentionally user-facing, not session secrets.
            print("LANZOU_RESULT " + json.dumps(receipt, ensure_ascii=False, sort_keys=True), flush=True)
            return 0
    finally:
        Path("ace5pro-minimal-lanzou-receipt.json").write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError,
            zipfile.BadZipFile) as exc:
        print(f"::error::LanZou upload rejected: {type(exc).__name__}: {str(exc)[:260]}",
              file=sys.stderr)
        sys.exit(1)
