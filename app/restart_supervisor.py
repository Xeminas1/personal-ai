"""Detached Windows-safe XemAi server restart verifier.

Started ONLY after the verified updater has installed assets. Does not
restart the whole PC, touch user data, or terminate arbitrary processes.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


def _listening(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _health(port: int, version: str) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/api/health", timeout=2
        ) as resp:
            if resp.status != 200:
                return False
            result = json.loads(resp.read(3000))
            return (
                result.get("ok") is True
                and result.get("server") == "XemAiMobile"
                and result.get("version") == version
            )
    except (OSError, ValueError, TypeError):
        return False


def _record(data_dir: Path, expected: str, state: str, attempts: int) -> None:
    path = data_dir / "server_restart_status.json"
    payload = {
        "target_version": expected, "state": state,
        "attempts": attempts, "recorded_at": time.time(),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        pass


def relaunch(
    executable: str, entrypoint: str, root: str, data: str,
    expected_version: str, port: int,
    *, wait=lambda n: time.sleep(n),
    spawn=None,
) -> bool:
    """Wait for the old listener to leave, then retry/verify one new server."""
    base = Path(root).resolve()
    script = Path(entrypoint).resolve()
    data_dir = Path(data).resolve()
    if (
        port < 1 or port > 65535
        or not script.is_file()
        or script.parent != base
        or script.name != "XemAiServer.pyw"
    ):
        _record(data_dir, expected_version, "invalid_launch", 0)
        return False
    _record(data_dir, expected_version, "waiting_for_old_server", 0)

    for _ in range(80):
        if not _listening(port):
            break
        if _health(port, expected_version):
            _record(data_dir, expected_version, "already_updated", 0)
            return True
        wait(0.25)
    else:
        _record(data_dir, expected_version, "old_server_still_running", 0)
        return False

    launch = spawn or subprocess.Popen
    for attempt in range(1, 4):
        _record(data_dir, expected_version, "starting", attempt)
        flags = 0
        if os.name == "nt":
            flags = (
                getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
                | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
                | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
            )
        try:
            process = launch(
                [executable, str(script)], cwd=str(base),
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, close_fds=True,
                creationflags=flags,
            )
        except (OSError, ValueError):
            if attempt != 3:
                wait(0.5)
            continue
        for _ in range(48):
            if _health(port, expected_version):
                _record(data_dir, expected_version, "healthy", attempt)
                return True
            if process.poll() is not None:
                break
            wait(0.5)
        if _health(port, expected_version):
            _record(data_dir, expected_version, "healthy", attempt)
            return True
        if process.poll() is None:
            # Could be hung or starting slowly; don't spawn duplicates.
            _record(data_dir, expected_version, "started_but_not_healthy", attempt)
            return False
    _record(data_dir, expected_version, "failed_to_start", 3)
    return False


def main() -> int:
    if len(sys.argv) != 7:
        return 2
    try:
        port = int(sys.argv[6])
    except (ValueError, TypeError):
        return 2
    return 0 if relaunch(*sys.argv[1:6], port) else 1


if __name__ == "__main__":
    raise SystemExit(main())
