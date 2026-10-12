"""Validate every pinned public XemAi updater asset before publishing a manifest.

This verification performs read-only HTTPS requests and compares downloaded
bytes with the expected SHA-256, including inherited prior-release files.
"""
from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, unquote

MANIFEST = Path(__file__).with_name("update_manifest.json")
EXPECTED_VERSION = "0.9.48"
ALLOWED_REFS = {"release-v0.9.18", "release-v0.9.19", "release-v0.9.20", "release-v0.9.21", "release-v0.9.22", "release-v0.9.23", "release-v0.9.24", "release-v0.9.25", "release-v0.9.26", "release-v0.9.27", "release-v0.9.28", "release-v0.9.29", "release-v0.9.30", "release-v0.9.31", "release-v0.9.32", "release-v0.9.33", "release-v0.9.34", "release-v0.9.35", "release-v0.9.36", "release-v0.9.37", "release-v0.9.38", "release-v0.9.39", "release-v0.9.40", "release-v0.9.41", "release-v0.9.42", "release-v0.9.43", "release-v0.9.44", "release-v0.9.45", "release-v0.9.46", "release-v0.9.47", "release-v0.9.48"}


def inspect(entry):
    path = entry["path"]
    url = entry["url"]
    expected = entry["sha256"]
    if not isinstance(path, str) or not re.fullmatch(r"[A-Za-z0-9_./-]{1,200}", path):
        raise ValueError("Invalid manifest path")
    if ".." in path.split("/") or path.startswith("/"):
        raise ValueError(f"Unsafe path: {path}")
    endpoint = urlsplit(url)
    components = unquote(endpoint.path).split("/")
    if (endpoint.scheme, endpoint.netloc) != ("https", "raw.githubusercontent.com") or endpoint.query or endpoint.fragment:
        raise ValueError(f"Unexpected asset host: {path}")
    if len(components) != 5 or components[1:3] != ["Xeminas1", "personal-ai"]:
        # Nested file paths are allowed, but the repo/ref must be exact.
        if len(components) < 5 or components[1:3] != ["Xeminas1", "personal-ai"]:
            raise ValueError(f"Unexpected repository: {path}")
    if components[3] not in ALLOWED_REFS or "/".join(components[4:]) != path:
        raise ValueError(f"Unpinned or wrong file URL: {path}")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError(f"Invalid digest: {path}")
    request = urllib.request.Request(url, headers={"User-Agent": "XemAi-release-manifest-check/1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        content = response.read(3_000_001)
    if len(content) > 3_000_000:
        raise ValueError(f"Oversized updater asset: {path}")
    actual = hashlib.sha256(content).hexdigest()
    if actual != expected:
        raise ValueError(f"SHA-256 mismatch for {path}: {actual} != {expected}")
    if path == "app/version.py":
        if content != b'VERSION = "0.9.48"\n':
            raise ValueError("Pinned version.py does not identify v0.9.48")
    return path


def main():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if manifest.get("version") != EXPECTED_VERSION:
        raise ValueError("Wrong release version")
    entries = manifest.get("files", [])
    names = [item["path"] for item in entries]
    if len(names) != len(set(names)) or len(names) < 90:
        raise ValueError("Duplicate or incomplete update manifest")
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        verified = list(executor.map(inspect, entries))
    print(f"Verified {len(verified)} pinned update assets via HTTPS/SHA-256 for {EXPECTED_VERSION}.")


if __name__ == "__main__":
    main()
