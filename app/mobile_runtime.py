from __future__ import annotations

import os
import socket
import subprocess
import sys
from pathlib import Path

from .config import load_config


BASE_DIR = Path(__file__).resolve().parent.parent


def mobile_endpoint() -> tuple[str, int]:
    config = load_config()
    host = str(config.get("mobile_server_host", "127.0.0.1"))
    port = int(config.get("mobile_server_port", 8765))
    return host, port


def mobile_local_url() -> str:
    host, port = mobile_endpoint()
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return f"http://{display_host}:{port}"


def mobile_server_is_running(timeout: float = 0.35) -> bool:
    host, port = mobile_endpoint()
    target = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    try:
        with socket.create_connection((target, port), timeout=timeout):
            return True
    except OSError:
        return False


def _pythonw_executable() -> Path:
    exe = Path(sys.executable)
    if os.name == "nt":
        candidate = exe.with_name("pythonw.exe")
        if candidate.exists():
            return candidate
    return exe


def start_mobile_server_process() -> bool:
    if mobile_server_is_running():
        return True

    script = BASE_DIR / "XemAiServer.pyw"
    if not script.exists():
        return False

    executable = _pythonw_executable()
    kwargs = {
        "cwd": str(BASE_DIR),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }

    if os.name == "nt":
        detached = getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
        new_group = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        kwargs["creationflags"] = detached | new_group | no_window

    try:
        subprocess.Popen(
            [str(executable), str(script)],
            **kwargs,
        )
    except OSError:
        return False
    return True
