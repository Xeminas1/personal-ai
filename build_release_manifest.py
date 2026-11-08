"""Rebuild update_manifest.json for a new XemAi release from the working tree.

Developer tool only (not shipped to installed copies). Every SHA-256 is computed
from the files on disk; nothing is typed by hand.

For each file already in the manifest (plus any --add paths):
  * unchanged content  -> keep its existing entry and immutable release ref;
  * changed or new     -> point it at raw.githubusercontent.com/<repo>/release-v<VERSION>/<path>.
Files that no longer exist are dropped and reported.

The working tree must equal the tree that will be frozen as release-v<VERSION>.
Run verify_release_manifest.py afterwards (it downloads and re-hashes every asset).

Usage:
    python build_release_manifest.py --notes "..." [--add path ...]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "update_manifest.json"
REPO = "Xeminas1/personal-ai"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_version() -> str:
    text = (ROOT / "app" / "version.py").read_text(encoding="utf-8")
    match = re.fullmatch(r'VERSION = "(\d+\.\d+\.\d+)"\n', text)
    if not match:
        raise SystemExit("app/version.py is not in the expected one-line format")
    return match.group(1)


def build(notes: str, extra: list[str]) -> dict:
    version = current_version()
    old = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if old.get("version") == version:
        raise SystemExit(f"Manifest already at {version}; bump app/version.py first")
    ref = f"release-v{version}"
    entries = {entry["path"]: entry for entry in old["files"]}
    for path in extra:
        entries.setdefault(path.replace("\\", "/"), {"path": path.replace("\\", "/"), "sha256": ""})

    files, changed, dropped = [], [], []
    for path in entries:  # keep existing order; new paths appended
        disk = ROOT / path
        if not disk.is_file():
            dropped.append(path)
            continue
        digest = sha256(disk)
        entry = entries[path]
        if entry.get("sha256") == digest and entry.get("url"):
            files.append({"path": path, "url": entry["url"], "sha256": digest})
        else:
            changed.append(path)
            files.append({
                "path": path,
                "url": f"https://raw.githubusercontent.com/{REPO}/{ref}/{path}",
                "sha256": digest,
            })
    if "app/version.py" not in changed:
        raise SystemExit("app/version.py did not change; refusing to build")
    print(f"version {old.get('version')} -> {version}; {len(files)} files, {len(changed)} pinned to {ref}")
    for path in changed:
        print("  changed:", path)
    for path in dropped:
        print("  dropped (missing on disk):", path)
    return {"version": version, "notes": notes, "files": files}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--notes", required=True)
    parser.add_argument("--add", nargs="*", default=[], help="new repo-relative paths to ship")
    args = parser.parse_args(argv)
    manifest = build(args.notes, args.add)
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
