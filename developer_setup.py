"""Opt-in local checkout setup for XemAi read-only developer inspection.

Run on the machine hosting XemAi chats, not by the language model.
This does not edit XemTV code or upload anything to GitHub.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from app.config import BASE_DIR, load_config, save_config
from app.developer_projects import DeveloperProjects


def main() -> int:
    print("XemAi Developer Mode - read-only XemTV checkout")
    print("No XemTV files will be edited, built, installed or pushed.\n")
    default = Path.home() / "Documents" / "XemAi-Developer-Projects" / "XemTV"
    raw = input(f"XemTV checkout directory [{default}]: ").strip()
    target = Path(raw).expanduser() if raw else default
    target = target.resolve()
    guard = DeveloperProjects(
        [{"id": "xemtv", "path": str(target)}],
        workspace=BASE_DIR / "workspace",
    )
    if not guard.enabled:
        print("Rejected: project must be an absolute directory outside XemAi's writable workspace.")
        return 1

    if not target.is_dir():
        answer = input("Checkout not found. Clone XemTV from private GitHub now? [y/N]: ").strip().lower()
        if answer != "y":
            print("No changes made. Re-run when your XemTV checkout is available.")
            return 1
        if not shutil.which("git"):
            print("Git is not available. Install Git for Windows or provide an existing checkout.")
            return 1
        if target.exists():
            print("Destination exists but is not a directory. No changes made.")
            return 1
        target.parent.mkdir(parents=True, exist_ok=True)
        print("Git may request you to sign in to GitHub. Do not paste access tokens into this chat.")
        result = subprocess.run(
            ["git", "clone", "--", "https://github.com/Xeminas1/XemTV.git", str(target)],
            check=False,
        )
        if result.returncode:
            print("Clone failed. Check GitHub access; no developer settings were changed.")
            return 1

    if not (target / "android-app").is_dir():
        print("This does not look like the XemTV checkout. No developer settings changed.")
        return 1

    config = load_config()
    existing = [
        entry for entry in config.get("developer_projects", [])
        if isinstance(entry, dict) and entry.get("id") != "xemtv"
    ]
    config["developer_projects"] = existing + [{"id": "xemtv", "path": str(target)}]
    save_config(config)
    print("\nXemTV registered for read-only Developer Mode.")
    print("Restart XemAi so its tools load the new project.")
    print("Try: Inspect XemTV's sidebar focus and tell me which files control it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
