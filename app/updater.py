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


PRESERVE_TOP_LEVEL = {
    "data",
    "logs",
    "config.json",
}


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


def _https_json(url: str, timeout: int = 20) -> dict[str, Any]:
    if not url.lower().startswith("https://"):
        raise UpdateError("Update manifest must use HTTPS.")

    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"PersonalAI/{VERSION}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            raw = r.read().decode("utf-8")
    except urllib.error.URLError as e:
        raise UpdateError(f"Could not reach update server: {e}") from e

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as e:
        raise UpdateError("Update manifest was not valid JSON.") from e

    if not isinstance(parsed, dict):
        raise UpdateError("Update manifest must be a JSON object.")
    return parsed


def fetch_manifest(url: str) -> dict[str, Any]:
    manifest = _https_json(url)

    required = {"version", "download_url", "sha256"}
    missing = required - set(manifest)
    if missing:
        raise UpdateError(
            "Update manifest is missing: " + ", ".join(sorted(missing))
        )

    if not str(manifest["download_url"]).lower().startswith("https://"):
        raise UpdateError("Update download URL must use HTTPS.")

    sha = str(manifest["sha256"]).strip().lower()
    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise UpdateError("Update manifest contains an invalid SHA-256 hash.")

    return manifest


def check_for_update(manifest_url: str) -> dict[str, Any] | None:
    manifest = fetch_manifest(manifest_url)
    if is_newer_version(str(manifest["version"])):
        return manifest
    return None


def _download(url: str, destination: Path, timeout: int = 120) -> None:
    if not url.lower().startswith("https://"):
        raise UpdateError("Update download URL must use HTTPS.")

    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"PersonalAI/{VERSION}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            with destination.open("wb") as f:
                shutil.copyfileobj(r, f)
    except urllib.error.URLError as e:
        raise UpdateError(f"Update download failed: {e}") from e


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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

    children = [p for p in extracted.iterdir() if p.is_dir()]
    for child in children:
        if (child / "main.py").exists() and (child / "app").exists():
            return child

    raise UpdateError(
        "Downloaded update does not look like a Personal AI release."
    )


def _backup_install(base_dir: Path, backup_dir: Path) -> None:
    backup_dir.mkdir(parents=True, exist_ok=True)
    for item in base_dir.iterdir():
        if item.name in PRESERVE_TOP_LEVEL:
            continue
        if item.name.startswith(".update_"):
            continue

        target = backup_dir / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True)
        else:
            shutil.copy2(item, target)


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
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def install_update(
    *,
    base_dir: Path,
    manifest: dict[str, Any],
    logger=None,
) -> str:
    target_version = str(manifest["version"])
    if not is_newer_version(target_version):
        return VERSION

    with tempfile.TemporaryDirectory(prefix="personal_ai_update_") as tmp:
        tmp_dir = Path(tmp)
        package = tmp_dir / "update.zip"
        extracted = tmp_dir / "extracted"

        if logger:
            logger.info(
                "Update download start | current=%s target=%s",
                VERSION, target_version
            )

        _download(str(manifest["download_url"]), package)

        actual_hash = _sha256(package)
        expected_hash = str(manifest["sha256"]).strip().lower()
        if actual_hash != expected_hash:
            raise UpdateError(
                "Update verification failed: SHA-256 does not match manifest."
            )

        extracted.mkdir(parents=True, exist_ok=True)
        _safe_extract(package, extracted)
        release_root = _find_release_root(extracted)

        backup_dir = (
            base_dir
            / ".update_backups"
            / f"before_{target_version.replace('.', '_')}"
        )
        if backup_dir.exists():
            shutil.rmtree(backup_dir)

        _backup_install(base_dir, backup_dir)
        _copy_release(release_root, base_dir)

        if logger:
            logger.info(
                "Update installed | from=%s to=%s backup=%s",
                VERSION, target_version, backup_dir
            )

    return target_version
