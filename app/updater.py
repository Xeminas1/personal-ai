from __future__ import annotations

import hashlib
import json
import shutil
import ssl
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from .version import VERSION

PRESERVE_TOP_LEVEL = {"data", "logs", "config.json"}


class UpdateError(RuntimeError):
    pass


def _version_tuple(value: str) -> tuple[int, ...]:
    parts = []
    for piece in value.strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in piece if ch.isdigit())
        parts.append(int(digits or "0"))
    return tuple(parts)


def is_newer_version(candidate: str, current: str = VERSION) -> bool:
    return _version_tuple(candidate) > _version_tuple(current)


def _https_bytes(url: str, timeout: int = 120) -> bytes:
    if not url.lower().startswith("https://"):
        raise UpdateError("Update URLs must use HTTPS.")
    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"PersonalAI/{VERSION}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(
            req, timeout=timeout, context=ssl.create_default_context()
        ) as response:
            return response.read()
    except urllib.error.URLError as e:
        raise UpdateError(f"Could not download update content: {e}") from e


def _https_json(url: str, timeout: int = 20) -> dict[str, Any]:
    try:
        parsed = json.loads(_https_bytes(url, timeout=timeout).decode("utf-8"))
    except json.JSONDecodeError as e:
        raise UpdateError("Update manifest was not valid JSON.") from e
    if not isinstance(parsed, dict):
        raise UpdateError("Update manifest must be a JSON object.")
    return parsed


def _valid_sha256(value: str) -> bool:
    value = value.strip().lower()
    return len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def fetch_manifest(url: str) -> dict[str, Any]:
    manifest = _https_json(url)
    if "version" not in manifest:
        raise UpdateError("Update manifest is missing: version")

    files = manifest.get("files")
    if files is not None:
        if not isinstance(files, list) or not files:
            raise UpdateError("Manifest 'files' must be a non-empty list.")
        for item in files:
            if not isinstance(item, dict):
                raise UpdateError("Every manifest file entry must be an object.")
            if not {"path", "url", "sha256"}.issubset(item):
                raise UpdateError("A file entry is missing path, url, or sha256.")
            if not str(item["url"]).lower().startswith("https://"):
                raise UpdateError("Every update file URL must use HTTPS.")
            if not _valid_sha256(str(item["sha256"])):
                raise UpdateError("A file entry has an invalid SHA-256 hash.")
        return manifest

    required = {"download_url", "sha256"}
    missing = required - set(manifest)
    if missing:
        raise UpdateError(
            "Update manifest is missing: " + ", ".join(sorted(missing))
        )
    if not str(manifest["download_url"]).lower().startswith("https://"):
        raise UpdateError("Update download URL must use HTTPS.")
    if not _valid_sha256(str(manifest["sha256"])):
        raise UpdateError("Update manifest contains an invalid SHA-256 hash.")
    return manifest


def check_for_update(manifest_url: str) -> dict[str, Any] | None:
    manifest = fetch_manifest(manifest_url)
    if is_newer_version(str(manifest["version"])):
        return manifest
    return None


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_relative_path(value: str) -> Path:
    path = Path(value.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise UpdateError(f"Unsafe update path: {value}")
    if path.parts[0] in PRESERVE_TOP_LEVEL:
        raise UpdateError(f"Update attempted to replace preserved path: {value}")
    return path


def _backup_program_files(base_dir: Path, backup_dir: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    for item in base_dir.iterdir():
        if item.name in PRESERVE_TOP_LEVEL or item.name.startswith(".update_"):
            continue
        target = backup_dir / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


def _install_file_manifest(
    *, base_dir: Path, manifest: dict[str, Any], logger=None
) -> str:
    target_version = str(manifest["version"])
    with tempfile.TemporaryDirectory(prefix="personal_ai_update_") as tmp:
        stage = Path(tmp) / "stage"
        stage.mkdir(parents=True, exist_ok=True)

        for item in manifest["files"]:
            relative = _safe_relative_path(str(item["path"]))
            data = _https_bytes(str(item["url"]))
            actual = _sha256_bytes(data)
            expected = str(item["sha256"]).lower()
            if actual != expected:
                raise UpdateError(
                    f"Verification failed for {relative}: SHA-256 mismatch."
                )
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)

        backup_dir = base_dir / ".update_backups" / f"before_{target_version.replace('.', '_')}"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        _backup_program_files(base_dir, backup_dir)

        for staged in stage.rglob("*"):
            if not staged.is_file():
                continue
            relative = staged.relative_to(stage)
            destination = base_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(staged, destination)

        if logger:
            logger.info(
                "File update installed | from=%s to=%s files=%d backup=%s",
                VERSION, target_version, len(manifest["files"]), backup_dir
            )
    return target_version


def _safe_extract(zip_path: Path, destination: Path) -> None:
    with zipfile.ZipFile(zip_path, "r") as zf:
        destination_resolved = destination.resolve()
        for member in zf.infolist():
            target = (destination / member.filename).resolve()
            if destination_resolved not in target.parents and target != destination_resolved:
                raise UpdateError("Unsafe path detected inside update package.")
        zf.extractall(destination)


def _find_release_root(extracted: Path) -> Path:
    if (extracted / "main.py").exists() and (extracted / "app").exists():
        return extracted
    for child in [p for p in extracted.iterdir() if p.is_dir()]:
        if (child / "main.py").exists() and (child / "app").exists():
            return child
    raise UpdateError("Downloaded update does not look like a Personal AI release.")


def _copy_release(release_root: Path, base_dir: Path) -> None:
    for item in release_root.iterdir():
        if item.name in PRESERVE_TOP_LEVEL:
            continue
        target = base_dir / item.name
        if item.is_dir():
            if target.exists() and target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
            shutil.copytree(item, target)
        else:
            shutil.copy2(item, target)


def _install_zip_manifest(
    *, base_dir: Path, manifest: dict[str, Any], logger=None
) -> str:
    target_version = str(manifest["version"])
    with tempfile.TemporaryDirectory(prefix="personal_ai_update_") as tmp:
        tmp_dir = Path(tmp)
        package = tmp_dir / "update.zip"
        data = _https_bytes(str(manifest["download_url"]))
        if _sha256_bytes(data) != str(manifest["sha256"]).lower():
            raise UpdateError("Update verification failed: SHA-256 mismatch.")
        package.write_bytes(data)
        extracted = tmp_dir / "extracted"
        extracted.mkdir(parents=True, exist_ok=True)
        _safe_extract(package, extracted)
        release_root = _find_release_root(extracted)
        backup_dir = base_dir / ".update_backups" / f"before_{target_version.replace('.', '_')}"
        if backup_dir.exists():
            shutil.rmtree(backup_dir)
        _backup_program_files(base_dir, backup_dir)
        _copy_release(release_root, base_dir)
        if logger:
            logger.info(
                "ZIP update installed | from=%s to=%s backup=%s",
                VERSION, target_version, backup_dir
            )
    return target_version


def install_update(
    *, base_dir: Path, manifest: dict[str, Any], logger=None
) -> str:
    target_version = str(manifest["version"])
    if not is_newer_version(target_version):
        return VERSION
    if "files" in manifest:
        return _install_file_manifest(
            base_dir=base_dir, manifest=manifest, logger=logger
        )
    return _install_zip_manifest(
        base_dir=base_dir, manifest=manifest, logger=logger
    )
