from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .config import DATA_DIR, load_config
from .version import VERSION


BASE_DIR = Path(__file__).resolve().parent.parent
STATE_PATH = DATA_DIR / "mobile_server.json"


def mobile_endpoint() -> tuple[str, int]:
    config = load_config()
    host = str(config.get("mobile_server_host", "127.0.0.1"))
    port = int(config.get("mobile_server_port", 8765))
    return host, port


def mobile_local_url() -> str:
    host, port = mobile_endpoint()
    display_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host
    return f"http://{display_host}:{port}"


def _target_host() -> str:
    host, _ = mobile_endpoint()
    return "127.0.0.1" if host in {"0.0.0.0", "::", "localhost"} else host


def mobile_server_is_running(timeout: float = 0.35) -> bool:
    _, port = mobile_endpoint()
    try:
        with socket.create_connection((_target_host(), port), timeout=timeout):
            return True
    except OSError:
        return False


def mobile_server_health(timeout: float = 1.0) -> dict | None:
    _, port = mobile_endpoint()
    url = f"http://{_target_host()}:{port}/api/health?t={time.time_ns()}"
    request = urllib.request.Request(
        url,
        headers={"Cache-Control": "no-cache", "User-Agent": f"XemAi/{VERSION}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            data = json.loads(raw)
            return data if isinstance(data, dict) else None
    except (OSError, urllib.error.URLError, json.JSONDecodeError, UnicodeError):
        return None


def mobile_server_version() -> str | None:
    health = mobile_server_health()
    if health and health.get("ok"):
        return str(health.get("version", "")).strip() or None
    return None


def _pythonw_executable() -> Path:
    exe = Path(sys.executable)
    if os.name == "nt":
        candidate = exe.with_name("pythonw.exe")
        if candidate.exists():
            return candidate
    return exe


def _read_state_pid() -> int | None:
    if not STATE_PATH.exists():
        return None
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        pid = int(data.get("pid", 0))
        return pid if pid > 0 else None
    except Exception:
        return None


def _stop_pid(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        if os.name == "nt":
            result = subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            )
            return result.returncode == 0
        os.kill(pid, 15)
        return True
    except OSError:
        return False


def _stop_legacy_windows_server() -> bool:
    """
    v0.4.0-v0.4.2 did not write a PID file. On Windows, identify only Python
    processes whose command line contains this exact XemAiServer.pyw path.
    """
    if os.name != "nt":
        return False

    target = str((BASE_DIR / "XemAiServer.pyw").resolve())
    escaped = target.replace("'", "''")
    command = (
        "$target='" + escaped + "';"
        "Get-CimInstance Win32_Process | "
        "Where-Object { "
        "($_.Name -ieq 'pythonw.exe' -or $_.Name -ieq 'python.exe') "
        "-and $_.CommandLine -and $_.CommandLine.Contains($target) "
        "} | ForEach-Object { "
        "Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue "
        "}"
    )
    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy", "Bypass",
                "-Command", command,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )
        return result.returncode == 0
    except OSError:
        return False


def stop_mobile_server_process(wait_seconds: float = 4.0) -> bool:
    if not mobile_server_is_running():
        return True

    pid = _read_state_pid()
    stopped = _stop_pid(pid) if pid else False
    if not stopped:
        _stop_legacy_windows_server()

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if not mobile_server_is_running(timeout=0.2):
            try:
                if STATE_PATH.exists():
                    STATE_PATH.unlink()
            except OSError:
                pass
            return True
        time.sleep(0.15)
    return not mobile_server_is_running(timeout=0.2)


def start_mobile_server_process(wait_seconds: float = 4.0) -> bool:
    if mobile_server_version() == VERSION:
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
        subprocess.Popen([str(executable), str(script)], **kwargs)
    except OSError:
        return False

    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        if mobile_server_version() == VERSION:
            return True
        time.sleep(0.15)
    return mobile_server_version() == VERSION


def ensure_mobile_server_current(force_restart: bool = False) -> bool:
    current = mobile_server_version()

    if not force_restart and current == VERSION:
        return True

    if mobile_server_is_running():
        if not stop_mobile_server_process():
            return False

    return start_mobile_server_process()


def restart_mobile_server_process() -> bool:
    return ensure_mobile_server_current(force_restart=True)
