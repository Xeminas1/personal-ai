from __future__ import annotations

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
import py_compile
import shutil
import ssl
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
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


def _https_bytes(url: str, timeout: int = 120, *, fresh: bool = False) -> bytes:
    if not url.lower().startswith("https://"):
        raise UpdateError("Update URLs must use HTTPS.")
    headers = {"User-Agent": f"PersonalAI/{VERSION}"}
    if fresh:
        headers.update({"Cache-Control": "no-cache, max-age=0", "Pragma": "no-cache"})
        parts = urllib.parse.urlsplit(url)
        if parts.hostname == "raw.githubusercontent.com":
            # GitHub's mutable branch URLs can be cached for five minutes.
            # Preserve existing query bytes; signed/custom hosts stay untouched.
            query = parts.query + ("&" if parts.query else "")
            query += "_xemai_check=" + uuid.uuid4().hex
            url = urllib.parse.urlunsplit(parts._replace(query=query))
    req = urllib.request.Request(
        url,
        headers=headers,
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
        parsed = json.loads(_https_bytes(url, timeout=timeout, fresh=True).decode("utf-8"))
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


def _validate_python_files(root: Path) -> None:
    """Reject an update before install if any staged Python file has invalid syntax."""
    failures: list[str] = []
    python_sources = [
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".py", ".pyw"}
    ]
    for path in sorted(python_sources):
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as e:
            failures.append(f"{path.relative_to(root)}: {e.msg}")
    if failures:
        detail = " | ".join(failures[:5])
        raise UpdateError(f"Update contains invalid Python code: {detail}")


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


@dataclass
class PreparedFileUpdate:
    """A verified delta staged away from the live application.

    Downloading and syntax checks never acquire a server chat/update lock.
    The caller MUST close this handle even on failed or cancelled updates.
    """
    version: str
    base_dir: Path
    temporary: tempfile.TemporaryDirectory
    stage: Path
    changed: tuple[Path, ...]
    skipped: int
    download_count: int
    prepared_at: float

    def close(self) -> None:
        self.temporary.cleanup()


def _existing_sha256(path: Path) -> str | None:
    if not path.is_file() or path.is_symlink():
        return None
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 256), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return None


def _safe_update_target(base_dir: Path, relative: Path) -> Path:
    base = base_dir.resolve()
    target = base_dir / relative
    # No manifest item may escape the install root through symlinks/junctions.
    if not target.resolve(strict=False).is_relative_to(base):
        raise UpdateError(f"Update file escapes application directory: {relative}")
    if target.is_symlink():
        raise UpdateError(f"Update would overwrite a symbolic link: {relative}")
    return target


def prepare_file_update(
    *, base_dir: Path, manifest: dict[str, Any], logger=None
) -> PreparedFileUpdate:
    """Check unchanged assets locally and download changed ones in parallel.

    Verify EVERY pinned asset either against existing on-disk content or a
    freshly downloaded SHA-256. The live program is never modified here.
    """
    if "files" not in manifest or not isinstance(manifest["files"], list):
        raise UpdateError("File manifest required for staged delta updating.")
    base_dir = Path(base_dir)
    version = str(manifest["version"])
    items: list[tuple[Path, str, str]] = []
    paths_seen = set()
    for entry in manifest["files"]:
        if not isinstance(entry, dict):
            raise UpdateError("Malformed update file entry.")
        relative = _safe_relative_path(str(entry.get("path", "")))
        key = relative.as_posix().lower()
        if key in paths_seen:
            raise UpdateError(f"Duplicate update path: {relative}")
        paths_seen.add(key)
        _safe_update_target(base_dir, relative)
        digest = str(entry.get("sha256", "")).lower()
        url = str(entry.get("url", ""))
        if not _valid_sha256(digest) or not url.lower().startswith("https://"):
            raise UpdateError(f"Invalid HTTPS or SHA-256 for {relative}")
        items.append((relative, url, digest))

    to_download = [
        entry for entry in items
        if _existing_sha256(base_dir / entry[0]) != entry[2]
    ]
    temp = tempfile.TemporaryDirectory(prefix="personal_ai_delta_")
    stage = Path(temp.name) / "stage"
    stage.mkdir()
    try:
        def fetch(entry):
            relative, url, digest = entry
            data = _https_bytes(url)
            if _sha256_bytes(data) != digest:
                raise UpdateError(
                    f"Verification failed for {relative}: SHA-256 mismatch."
                )
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
            return relative

        if to_download:
            # Bounded to avoid overwhelming the laptop or public source host.
            with ThreadPoolExecutor(max_workers=min(6, len(to_download))) as pool:
                changes = list(pool.map(fetch, to_download))
        else:
            changes = []
        _validate_python_files(stage)
        prepared = PreparedFileUpdate(
            version=version, base_dir=base_dir.resolve(),
            temporary=temp, stage=stage, changed=tuple(changes),
            skipped=len(items) - len(to_download),
            download_count=len(to_download), prepared_at=time.monotonic(),
        )
        if logger:
            logger.info(
                "Update prepared off-line | target=%s downloads=%d unchanged=%d",
                version, len(to_download), prepared.skipped,
            )
        return prepared
    except BaseException:
        temp.cleanup()
        raise


def install_prepared_update(
    *, base_dir: Path, prepared: PreparedFileUpdate, logger=None
) -> str:
    """Short critical section: back up and replace only changed files."""
    base_dir = Path(base_dir).resolve()
    if prepared.base_dir != base_dir:
        raise UpdateError("Prepared update belongs to a different installation.")
    if not prepared.stage.is_dir():
        raise UpdateError("Prepared update is no longer available.")
    backup_dir = (
        base_dir / ".update_backups"
        / f"before_{prepared.version.replace('.', '_')}"
    )
    changed = []
    # Verify again in case staging changed while the chat remained active.
    for relative in prepared.changed:
        staged = prepared.stage / relative
        if not staged.is_file() or staged.is_symlink():
            raise UpdateError(f"Staged update file is missing: {relative}")
        _safe_update_target(base_dir, relative)
        changed.append(relative)
    if backup_dir.exists():
        shutil.rmtree(backup_dir)
    backup_dir.mkdir(parents=True)
    existed: list[Path] = []
    created: list[Path] = []
    try:
        # Back up BEFORE making any program changes; no large full-tree copy.
        for relative in changed:
            target = _safe_update_target(base_dir, relative)
            if target.exists():
                if not target.is_file():
                    raise UpdateError(f"Update target is not a regular file: {relative}")
                dest = backup_dir / relative
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, dest)
                existed.append(relative)
            else:
                created.append(relative)
        (backup_dir / "rollback_manifest.json").write_text(
            json.dumps({
                "version": prepared.version,
                "restorable_files": [p.as_posix() for p in existed],
                "new_files": [p.as_posix() for p in created],
            }, indent=2),
            encoding="utf-8",
        )
        for relative in changed:
            target = _safe_update_target(base_dir, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(prepared.stage / relative, target)
    except Exception:
        # If final replacement fails, restore only the files this update touched.
        for relative in existed:
            source = backup_dir / relative
            if source.is_file():
                target = base_dir / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
        for relative in created:
            target = base_dir / relative
            if target.is_file():
                target.unlink()
        raise
    if logger:
        logger.info(
            "Delta update installed | from=%s to=%s downloaded=%d reused=%d "
            "replaced=%d backup=%s preflight_seconds=%d",
            VERSION, prepared.version, prepared.download_count,
            prepared.skipped, len(changed), backup_dir,
            int(time.monotonic() - prepared.prepared_at),
        )
    return prepared.version


def _install_file_manifest(
    *, base_dir: Path, manifest: dict[str, Any], logger=None
) -> str:
    prepared = prepare_file_update(
        base_dir=base_dir, manifest=manifest, logger=logger
    )
    try:
        return install_prepared_update(
            base_dir=base_dir, prepared=prepared, logger=logger
        )
    finally:
        prepared.close()


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
        _validate_python_files(release_root)
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
