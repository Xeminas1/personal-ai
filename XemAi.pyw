from __future__ import annotations

import os
import subprocess
import traceback
import webbrowser
from pathlib import Path

from app.mobile_runtime import ensure_mobile_server_current, mobile_local_url

BASE_DIR = Path(__file__).resolve().parent


def _find_edge() -> Path | None:
    candidates = []
    for env_name in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        base = os.environ.get(env_name)
        if base:
            candidates.append(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe")
    for path in candidates:
        if path.exists():
            return path
    return None


def main() -> int:
    if not ensure_mobile_server_current():
        raise RuntimeError("XemAi could not start its local web server.")

    url = mobile_local_url() + "/?desktop=1"
    edge = _find_edge()
    if edge:
        subprocess.Popen(
            [
                str(edge),
                f"--app={url}",
                "--start-maximized",
                "--disable-features=msEdgeSidebarV2",
            ],
            cwd=str(BASE_DIR),
        )
    else:
        webbrowser.open(url, new=1)
    return 0


try:
    raise SystemExit(main())
except SystemExit:
    raise
except Exception:
    path = BASE_DIR / "logs" / "desktop_startup_error.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(traceback.format_exc(), encoding="utf-8")
    raise
