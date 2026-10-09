#!/usr/bin/env python3
"""Publish a verified OnePlus/SukiSU AK3 CI artifact to LanZouCloud.

Only trusted, completed main workflow runs are eligible. This script never
removes or overwrites a remote file, and never prints authentication cookies.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit
import zipfile
from pathlib import Path

ROOT_FOLDER = "一加suki"
VERSION_FOLDER = "suki-40959"
WORKFLOW_PATH = ".github/workflows/Build Kernel OnePlus.yml"
ARTIFACT_PREFIX = "AnyKernel3_SukiSUUltra_40959_"
MAX_ZIP_SIZE = 100 * 1024 * 1024


class PublishError(RuntimeError):
    pass


def validated_artifact_name(name: str) -> tuple[str, str] | None:
    """Return (model folder, safe basename) or None when not an eligible build."""
    if not name.startswith(ARTIFACT_PREFIX) or "_Android" not in name:
        return None
    model_part = name[len(ARTIFACT_PREFIX):].split("_Android", 1)[0]
    if not re.fullmatch(r"OnePlus[A-Za-z0-9_-]{2,80}", model_part):
        return None
    # LanZouCloud name_format strips parentheses and certain punctuation.
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._-")
    if len(safe_name) > 175:
        raise PublishError("AK3 artifact name is unusually long")
    return model_part, safe_name


def github_api(path: str, token: str) -> dict:
    if not path.startswith("repos/") or ".." in path:
        raise PublishError("Invalid GitHub API path")
    req = urllib.request.Request(
        f"https://api.github.com/{path}",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "OnePlus-SukiSU-Lanzou-Upload",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            return json.load(response)
    except (urllib.error.URLError, ValueError) as exc:
        raise PublishError(f"GitHub API unavailable: {type(exc).__name__}") from exc


def select_artifact(repo: str, run_id: int, token: str):
    run = github_api(f"repos/{repo}/actions/runs/{run_id}", token)
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise PublishError("Source kernel workflow has not completed successfully")
    if run.get("head_branch") != "SukiSU-Ultra" or run.get("path") != WORKFLOW_PATH:
        raise PublishError("Source run is not the trusted OnePlus kernel workflow")
    if run.get("repository", {}).get("full_name", "").lower() != repo.lower():
        raise PublishError("Source run belongs to a different repository")
    response = github_api(f"repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100", token)
    if response.get("total_count", 0) > 100:
        raise PublishError("Unexpectedly many artifacts; cannot safely select one")
    candidates = []
    for item in response.get("artifacts", []):
        parsed = validated_artifact_name(item.get("name", ""))
        if parsed and not item.get("expired"):
            candidates.append((item, parsed))
    if not candidates:
        return None  # Other brands or runs with no eligible OnePlus artifact.
    if len(candidates) != 1:
        raise PublishError("Ambiguous AK3 artifacts; refusing to select one")
    return candidates[0]


def fetch_artifact(repo: str, run_id: int, name: str, dest: Path) -> None:
    env = os.environ.copy()
    env["GH_TOKEN"] = os.environ["GH_TOKEN"]
    # Never invoke a shell; artifact names cannot inject arguments.
    proc = subprocess.run(
        ["gh", "run", "download", str(run_id), "--repo", repo,
         "--name", name, "--dir", str(dest)],
        env=env, text=True, capture_output=True, timeout=240, check=False,
    )
    if proc.returncode:
        raise PublishError(f"GitHub artifact download failed (code {proc.returncode})")


def make_flashable_zip(source: Path, output: Path) -> dict:
    for f in ("anykernel.sh", "Image", "tools/ak3-core.sh"):
        if not (source / f).is_file():
            raise PublishError(f"AK3 artifact missing required file: {f}")
    if (source / "Image").stat().st_size < 1024 * 1024:
        raise PublishError("Kernel Image suspiciously small")
    files = sorted(p for p in source.rglob("*") if p.is_file())
    if not files:
        raise PublishError("Empty AK3 artifact")
    if any(p.is_symlink() or ".git" in p.relative_to(source).parts for p in source.rglob("*")):
        raise PublishError("Unsupported symlink or Git metadata in artifact")
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for path in files:
            z.write(path, path.relative_to(source).as_posix())
    if output.stat().st_size > MAX_ZIP_SIZE:
        raise PublishError("AK3 ZIP exceeds the configured 100 MiB limit")
    with zipfile.ZipFile(output) as z:
        if z.testzip() is not None:
            raise PublishError("ZIP integrity check failed")
        if any(f not in z.namelist() for f in ("anykernel.sh", "Image", "tools/ak3-core.sh")):
            raise PublishError("ZIP structure verification failed")
    h = hashlib.sha256()
    with output.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return {"sha256": h.hexdigest(), "size_bytes": output.stat().st_size,
            "member_count": len(files)}


def make_secure_client():
    # Pin an audited third-party version in the calling workflow. The upstream
    # implementation uses verify=False and replaces same-name files; override
    # both dangerous defaults rather than trusting them with login cookies.
    import requests
    from lanzou.api import LanZouCloud

    class SafeClient(LanZouCloud):
        def _safe_request(self, method, url, *, data=None, **kwargs):
            # Authentication cookies are usable only on the verified LanZouCloud
            # management origin. Never follow an off-origin redirect.
            kwargs.pop("verify", None)
            kwargs.pop("allow_redirects", None)
            kwargs.setdefault("headers", self._headers)
            kwargs["timeout"] = min(kwargs.get("timeout", self._timeout), 120)
            for hop in range(4):
                parsed = urlsplit(url)
                if (parsed.scheme != "https" or
                        parsed.hostname != "pc.woozooo.com" or
                        parsed.port not in (None, 443) or
                        parsed.username or parsed.password):
                    raise PublishError("LanZouCloud authentication request to unapproved host blocked")
                try:
                    response = self._session.request(
                        method, url, data=data, verify=True,
                        allow_redirects=False, **kwargs)
                    if response.is_redirect:
                        destination = response.headers.get("Location", "")
                        if not destination or method != "GET":
                            raise PublishError("Unexpected LanZouCloud upload redirect blocked")
                        url = urljoin(url, destination)
                        # Revalidate the destination before issuing another request.
                        continue
                    response.raise_for_status()
                    return response
                except requests.RequestException as exc:
                    raise PublishError(
                        f"LanZouCloud HTTPS failure: {type(exc).__name__}"
                    ) from exc
            raise PublishError("Too many LanZouCloud same-origin login redirects")

        def _get(self, url, **kwargs):
            return self._safe_request("GET", url, **kwargs)

        def _post(self, url, data, **kwargs):
            return self._safe_request("POST", url, data=data, **kwargs)

        def delete(self, *args, **kwargs):
            raise PublishError("Refusing remote file deletion or overwrite")

    return SafeClient()


def ensure_folder(client, parent: int, folder_name: str) -> int:
    entries = [x for x in client.get_dir_list(parent) if x.name == folder_name]
    if len(entries) > 1:
        raise PublishError(f"Multiple same-name folders: {folder_name}")
    if len(entries) == 1:
        return int(entries[0].id)
    result = client.mkdir(parent, folder_name)
    # The SDK uses numeric error code 5 for MKDIR_ERROR, and may return -1.
    if not isinstance(result, int) or result <= 0:
        raise PublishError(f"Could not create folder {folder_name} (code {result})")
    check = [x for x in client.get_dir_list(parent) if x.name == folder_name]
    if len(check) != 1 or int(check[0].id) != result:
        raise PublishError(f"Folder readback verification failed: {folder_name}")
    return result


def publish_to_lanzou(client, archive: Path, model: str, cookies: dict) -> dict:
    from lanzou.api import LanZouCloud
    if client.login_by_cookie(cookies) != LanZouCloud.SUCCESS:
        raise PublishError("LanZouCloud session expired or login refused")
    folder = -1
    for name in (ROOT_FOLDER, VERSION_FOLDER, model):
        folder = ensure_folder(client, folder, name)
    if any(file.name == archive.name for file in client.get_file_list(folder)):
        raise PublishError("Remote filename already exists; never overwrite an existing backup")
    captured = []
    result = client.upload_file(str(archive), folder,
                                uploaded_handler=lambda file_id, is_file: captured.append(
                                    int(file_id)) if is_file else None)
    if result != LanZouCloud.SUCCESS:
        raise PublishError(f"LanZouCloud upload failed (code {result})")
    matches = [f for f in client.get_file_list(folder) if f.name == archive.name]
    if len(matches) != 1:
        raise PublishError("Upload returned success but remote file was not found uniquely")
    if captured and captured[-1] != int(matches[0].id):
        raise PublishError("Uploaded file ID differs from remote readback")
    # Avoid printing share URLs to the public Actions log. The account owner
    # can manage links and extraction codes in the LanZouCloud dashboard.
    return {"folder": f"{ROOT_FOLDER}/{VERSION_FOLDER}/{model}",
            "remote_name": archive.name, "remote_file_id": int(matches[0].id)}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run-id", required=True, type=int)
    p.add_argument("--repo", required=True)
    args = p.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", args.repo):
        raise PublishError("Invalid repository")
    if args.run_id <= 0:
        raise PublishError("Invalid workflow run ID")
    token = os.environ.get("GH_TOKEN", "")
    if not token:
        raise PublishError("GH_TOKEN is not configured")
    selected = select_artifact(args.repo, args.run_id, token)
    if selected is None:
        print("SKIP: no OnePlus SukiSU 40959 AK3 artifact in this run")
        return 0
    item, (model, safe_name) = selected
    ylogin = os.environ.get("LANZOU_YLOGIN", "")
    phpdisk_info = os.environ.get("LANZOU_PHPDISK_INFO", "")
    php_session = os.environ.get("LANZOU_PHPSESSID", "")
    if not ylogin or not phpdisk_info:
        print("::warning::LanZouCloud credentials missing; kernel artifact remains in GitHub")
        return 0
    if not ylogin.isdecimal() or not phpdisk_info.strip():
        raise PublishError("LanZouCloud Cookie format is invalid; check GitHub Secrets")
    cookies = {"ylogin": ylogin, "phpdisk_info": phpdisk_info}
    if php_session:
        # Newer LanZouCloud sessions may additionally use this HTTP-only
        # cookie; it is injected from a GitHub Secret, never stored or logged.
        cookies["PHPSESSID"] = php_session
    with tempfile.TemporaryDirectory(prefix="lanzou-oneplus-") as tmp:
        temp = Path(tmp)
        folder = temp / "artifact"
        folder.mkdir()
        fetch_artifact(args.repo, args.run_id, item["name"], folder)
        package = temp / (safe_name + f"_run{args.run_id}.zip")
        proof = make_flashable_zip(folder, package)
        client = make_secure_client()
        remote = publish_to_lanzou(client, package, model, cookies)
        receipt = {"source_run_id": args.run_id, "source_artifact_id": item["id"],
                   "model": model, "archive_sha256": proof["sha256"],
                   "archive_size_bytes": proof["size_bytes"],
                   "member_count": proof["member_count"], "remote": remote,
                   "status": "uploaded_with_metadata_readback", "content_readback": "not_performed"}
        print("PUBLISHED " + json.dumps(receipt, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (PublishError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"::error::{exc}", file=sys.stderr)
        sys.exit(1)
