"""Read-only access to explicitly configured development project directories.

Project content is untrusted evidence, not instructions. This module does not
invoke shell commands, write files or alter Git repositories.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

PROJECT_ID = re.compile(r"^[a-z][a-z0-9_-]{0,31}$")
TEXT_SUFFIXES = frozenset({
    ".py", ".pyw", ".kt", ".kts", ".java", ".gradle", ".xml", ".json",
    ".md", ".txt", ".toml", ".yaml", ".yml", ".properties", ".sh",
    ".bat", ".cmd", ".ps1", ".html", ".css", ".js", ".ts", ".tsx",
    ".jsx", ".sql", ".ini", ".cfg", ".conf", ".c", ".h", ".cpp",
    ".hpp", ".cs", ".go", ".rs", ".swift", ".gitignore",
})
TEXT_NAMES = frozenset({"gradlew", "makefile", "dockerfile", "readme", "license"})
BLOCKED_DIRS = frozenset({
    ".git", ".gradle", ".idea", ".venv", "venv", "node_modules",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".next", "build",
    "dist", "data", "logs", "secrets", ".ssh", ".aws",
})
BLOCKED_FILES = frozenset({
    "local.properties", "config.json", ".env", ".npmrc", ".pypirc",
    "id_rsa", "id_ed25519", "credentials", "credentials.json",
})
BLOCKED_EXTENSIONS = frozenset({
    ".pem", ".key", ".p12", ".pfx", ".keystore", ".jks", ".db",
    ".sqlite", ".sqlite3", ".kdbx", ".env",
})
MAX_FILE_BYTES = 400_000
MAX_SCAN_FILES = 1200


class ProjectError(RuntimeError):
    pass


def _inside(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _blocked_name(name: str, is_dir: bool = False) -> bool:
    original = name
    name = name.lower()
    if is_dir:
        return name in BLOCKED_DIRS
    if name in BLOCKED_FILES or name.startswith(".env.") or name.endswith(tuple(BLOCKED_EXTENSIONS)):
        return True
    # Protect separator-based names (secret_token.kt) and CamelCase
    # names (SecretToken.kt, AppSecrets.kt) from accidental model reads.
    separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", original).lower()
    return bool(re.search(
        r"(?:^|[-_.])(secrets?|passwords?|tokens?|credentials?|private[-_]?keys?)(?:[-_.]|$)",
        separated,
    ))


def _safe_relative(relative: str) -> Path:
    raw = str(relative or ".").replace("\\", "/")
    if len(raw) > 500 or raw.startswith("/") or "\x00" in raw or ":" in raw:
        raise ProjectError("Invalid project-relative path.")
    parts = raw.split("/")
    if any(part == ".." for part in parts):
        raise ProjectError("Parent traversal is not permitted.")
    return Path(raw)


class DeveloperProjects:
    def __init__(self, entries: object, *, workspace: Path):
        self._roots: dict[str, Path] = {}
        workspace = workspace.resolve()
        if not isinstance(entries, list):
            return
        for entry in entries[:12]:
            if not isinstance(entry, dict):
                continue
            project_id, configured = entry.get("id"), entry.get("path")
            if not isinstance(project_id, str) or not PROJECT_ID.fullmatch(project_id):
                continue
            if not isinstance(configured, str) or not configured.strip():
                continue
            path = Path(os.path.expandvars(os.path.expanduser(configured)))
            if not path.is_absolute():
                continue
            root = path.resolve()
            # Existing workspace_write must never grant write access to a
            # supposedly read-only development project.
            if _inside(root, workspace) or _inside(workspace, root):
                continue
            self._roots[project_id] = root

    @property
    def enabled(self) -> bool:
        return bool(self._roots)

    def projects(self) -> list[dict[str, object]]:
        return [
            {"project": key, "available": root.is_dir(), "mode": "read-only"}
            for key, root in sorted(self._roots.items())
        ]

    def _location(self, project: str, relative: str, *, directory: bool = False) -> tuple[Path, Path]:
        root = self._roots.get(str(project))
        if root is None:
            raise ProjectError("This project is not explicitly authorised.")
        if not root.is_dir():
            raise ProjectError("The configured project directory is not available.")
        path = _safe_relative(relative)
        target = root
        for part in path.parts:
            if part in ("", "."):
                continue
            if _blocked_name(part, is_dir=True):
                raise ProjectError("A protected directory cannot be accessed.")
            candidate = target / part
            if candidate.is_symlink():
                raise ProjectError("Symbolic links are not accessible.")
            target = candidate
        if not _inside(target.resolve(), root):
            raise ProjectError("Project path escapes the approved directory.")
        if not directory and _blocked_name(target.name):
            raise ProjectError("A protected file cannot be accessed.")
        return root, target

    def list_files(self, project: str, path: str = ".") -> dict:
        root, target = self._location(project, path, directory=True)
        if not target.is_dir():
            raise ProjectError("Project directory does not exist.")
        items = []
        for child in sorted(target.iterdir(), key=lambda item: item.name.lower()):
            if child.is_symlink() or _blocked_name(child.name, is_dir=child.is_dir()):
                continue
            if child.is_file() and (_blocked_name(child.name) or not self._is_text(child)):
                continue
            items.append({"path": child.relative_to(root).as_posix(), "type": "directory" if child.is_dir() else "file"})
            if len(items) >= 100:
                break
        return {"project": project, "path": target.relative_to(root).as_posix(), "items": items, "limit": 100}

    @staticmethod
    def _is_text(path: Path) -> bool:
        return path.suffix.lower() in TEXT_SUFFIXES or path.name.lower() in TEXT_NAMES

    def read_file(self, project: str, path: str, max_chars: int = 12000) -> dict:
        root, target = self._location(project, path)
        if not target.is_file() or not self._is_text(target):
            raise ProjectError("The requested readable source file does not exist.")
        size = target.stat().st_size
        if size > MAX_FILE_BYTES:
            raise ProjectError("Source file exceeds the read-only inspection limit.")
        limit = max(500, min(20000, int(max_chars)))
        with target.open("rb") as stream:
            raw = stream.read(min(size, limit * 4 + 4))
        if b"\x00" in raw:
            raise ProjectError("Binary file contents are not accessible.")
        text = raw.decode("utf-8", errors="replace")
        return {
            "project": project, "path": target.relative_to(root).as_posix(),
            "content": text[:limit], "truncated": len(text) > limit or size > len(raw),
            "read_only": True,
        }

    def search(self, project: str, term: str) -> dict:
        term = str(term).strip()
        if not 2 <= len(term) <= 120 or "\x00" in term:
            raise ProjectError("Search term must be between 2 and 120 characters.")
        root, _ = self._location(project, ".", directory=True)
        matches = []
        scanned = 0
        for current, folders, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            folders[:] = sorted(
                folder for folder in folders
                if not _blocked_name(folder, is_dir=True)
                and not (current_path / folder).is_symlink()
            )
            for name in sorted(files):
                candidate = current_path / name
                if candidate.is_symlink() or _blocked_name(name) or not self._is_text(candidate):
                    continue
                scanned += 1
                if scanned > MAX_SCAN_FILES:
                    return {"project": project, "matches": matches, "scanned": MAX_SCAN_FILES, "scan_limited": True}
                try:
                    if candidate.stat().st_size > MAX_FILE_BYTES:
                        continue
                    with candidate.open("rb") as stream:
                        raw = stream.read(MAX_FILE_BYTES + 1)
                    if b"\x00" in raw:
                        continue
                    lines = raw.decode("utf-8", errors="replace").splitlines()
                except OSError:
                    continue
                for line_number, line in enumerate(lines, 1):
                    if term.casefold() in line.casefold():
                        matches.append({
                            "path": candidate.relative_to(root).as_posix(),
                            "line": line_number, "excerpt": line.strip()[:250],
                        })
                        if len(matches) >= 25:
                            return {"project": project, "matches": matches, "scanned": scanned, "scan_limited": True}
        return {"project": project, "matches": matches, "scanned": scanned, "scan_limited": False}

    def find_source_files(
        self, project: str, *, filenames: list[str] | None = None,
        terms: list[str] | None = None, limit: int = 3,
    ) -> list[str]:
        """Select bounded, approved source paths for read-only code inspection.

        A filename match is exact (case-insensitive); broad terms match only
        source basenames. Source text is never executed or treated as policy.
        """
        root, _ = self._location(project, ".", directory=True)
        if not (1 <= int(limit) <= 4):
            raise ProjectError("Invalid source selection limit.")
        wanted = [
            str(item).replace("\\", "/").strip("/").casefold()
            for item in (filenames or [])[:4]
            if isinstance(item, str) and 1 <= len(item) <= 200
            and ".." not in item.split("/")
        ]
        words = [
            str(item).casefold() for item in (terms or [])[:20]
            if isinstance(item, str) and 3 <= len(item) <= 35 and item.isalpha()
        ]
        if not wanted and not words:
            return []

        ranked = []
        scanned = 0
        for current, folders, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            folders[:] = sorted(
                folder for folder in folders
                if not _blocked_name(folder, is_dir=True)
                and not (current_path / folder).is_symlink()
            )
            for name in sorted(files):
                file_path = current_path / name
                if file_path.is_symlink() or _blocked_name(name) or not self._is_text(file_path):
                    continue
                # Broad CODE questions should not prefer matching markdown
                # specifications over the source files the user asked to inspect.
                # Explicit filenames can still select Markdown when requested.
                if not wanted and file_path.suffix.lower() not in {
                    ".py", ".pyw", ".kt", ".kts", ".java", ".cs",
                    ".js", ".ts", ".tsx", ".jsx", ".c", ".cpp",
                    ".h", ".hpp", ".go", ".rs", ".swift",
                }:
                    continue
                scanned += 1
                if scanned > MAX_SCAN_FILES:
                    break
                relative = file_path.relative_to(root).as_posix()
                stem = file_path.stem.casefold()
                if wanted:
                    full = relative.casefold()
                    exact = any(full == item or full.endswith("/" + item) for item in wanted)
                    match = any(name.casefold() == item.split("/")[-1] for item in wanted)
                    score = 100 if exact else 50 if match else 0
                else:
                    score = sum(1 for word in set(words) if word in stem)
                if score <= 0:
                    continue
                try:
                    if file_path.stat().st_size > MAX_FILE_BYTES:
                        continue
                except OSError:
                    continue
                ranked.append((-score, relative.casefold(), relative))
            if scanned > MAX_SCAN_FILES:
                break
        ranked.sort()
        return [relative for _, _, relative in ranked[:limit]]
