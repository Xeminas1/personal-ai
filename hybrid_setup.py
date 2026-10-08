from __future__ import annotations

import getpass
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from app.config import BASE_DIR, DATA_DIR, load_config, save_config
from app.secrets import (
    ensure_hybrid_worker_server_token,
    save_hybrid_worker_client_token,
)


def _tailscale_exe() -> str:
    found = shutil.which("tailscale")
    if found:
        return found
    candidates = [
        Path(os.environ.get("ProgramFiles", "")) / "Tailscale" / "tailscale.exe",
        Path(os.environ.get("ProgramFiles(x86)", "")) / "Tailscale" / "tailscale.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError("Tailscale was not found. Install/sign in to Tailscale first.")


def _pythonw() -> str:
    exe = Path(sys.executable)
    candidate = exe.with_name("pythonw.exe")
    return str(candidate if candidate.is_file() else exe)


def _tailscale_dns_name(ts: str) -> str:
    result = subprocess.run(
        [ts, "status", "--json"],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(result.stdout)
    dns = str((data.get("Self") or {}).get("DNSName") or "").strip().rstrip(".")
    if not dns:
        raise RuntimeError("Tailscale did not report a MagicDNS name for this PC.")
    return dns


def _ollama_qwen_models() -> list[str]:
    req = urllib.request.Request("http://127.0.0.1:11434/api/tags", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as e:
        raise RuntimeError(
            "Could not reach Ollama on this PC. Start Ollama and make sure at "
            "least one Qwen model is installed."
        ) from e
    names = [
        str(item.get("name") or item.get("model") or "")
        for item in data.get("models", [])
        if isinstance(item, dict)
    ]
    return [name for name in names if "qwen" in name.lower()]


def _start_worker() -> None:
    worker = BASE_DIR / "XemAiWorker.pyw"
    if not worker.is_file():
        raise RuntimeError("XemAiWorker.pyw is missing from this XemAi installation.")
    subprocess.Popen(
        [_pythonw(), str(worker)],
        cwd=str(BASE_DIR),
        close_fds=True,
    )
    time.sleep(1.2)


def _install_worker_startup() -> Path:
    startup = (
        Path(os.environ["APPDATA"])
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
    )
    startup.mkdir(parents=True, exist_ok=True)
    path = startup / "XemAi Hybrid Worker.cmd"
    path.write_text(
        "@echo off\n"
        f'cd /d "{BASE_DIR}"\n'
        f'start "" "{_pythonw()}" "{BASE_DIR / "XemAiWorker.pyw"}"\n',
        encoding="utf-8",
    )
    return path


def _test_worker(url: str, token: str) -> dict:
    req = urllib.request.Request(
        url.rstrip("/") + "/api/health",
        headers={"Authorization": f"Bearer {token}"},
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Worker returned HTTP {e.code}: {body}") from e
    except Exception as e:
        raise RuntimeError(f"Could not reach the hybrid worker at {url}: {e}") from e
    if not data.get("ok"):
        raise RuntimeError(str(data.get("error") or "Worker health check failed."))
    return data


def setup_worker(*, silent: bool = False) -> int:
    if not silent:
        print("XemAi Hybrid Worker setup")
        print("-------------------------")
    models = _ollama_qwen_models()
    if not models:
        if not silent:
            print("No Qwen model is installed in Ollama on this PC.")
            print("Install the model you want this stronger PC to run, then try again.")
        return 1

    if not silent:
        print("Qwen models found:")
        for name in models:
            print(f"  - {name}")

    token = ensure_hybrid_worker_server_token(DATA_DIR)
    config = load_config()
    port = int(config.get("hybrid_worker_port", 8766))

    _start_worker()
    ts = _tailscale_exe()

    if not silent:
        print()
        print(f"Configuring private Tailscale HTTPS worker on port {port}...")
    serve = subprocess.run(
        [
            ts,
            "serve",
            "--bg",
            "--yes",
            f"--https={port}",
            f"localhost:{port}",
        ],
        capture_output=True,
        text=True,
    )
    if serve.returncode != 0:
        raise RuntimeError(
            "Tailscale Serve setup failed:\n"
            + (serve.stderr.strip() or serve.stdout.strip())
        )

    dns = _tailscale_dns_name(ts)
    url = f"https://{dns}:{port}"
    startup = _install_worker_startup()

    health = _test_worker(url, token)
    if not silent:
        pairing = DATA_DIR / "hybrid_pairing.txt"
        pairing.write_text(
            "XemAi Hybrid Pairing\n"
            f"Worker URL: {url}\n"
            f"Worker token: {token}\n"
            f"Worker PC: {health.get('machine_name', 'Powerful PC')}\n"
            f"Recommended model: {health.get('recommended_model', 'unknown')}\n",
            encoding="utf-8",
        )
        print()
        print("Hybrid worker is ready.")
        print(f"Worker URL:   {url}")
        print(f"Worker token: {token}")
        print(f"Model:        {health.get('recommended_model', 'unknown')}")
        print()
        print("Keep that token private. On the always-on XemAi laptop, run:")
        print("  hybrid_host_setup.bat")
        print("and paste the URL and token above.")
        print()
        print(f"A pairing copy was saved locally to: {pairing}")
        print(f"Worker autostart entry: {startup}")
    return 0


def setup_host() -> int:
    print("XemAi Hybrid Host pairing")
    print("-------------------------")
    print("Enter the details shown by hybrid_worker_setup.bat on the strong PC.")
    print()
    url = input("Worker URL: ").strip().rstrip("/")
    token = getpass.getpass("Worker token (hidden while pasting): ").strip()
    if not url or not token:
        print("Worker URL and token are both required.")
        return 1
    if not url.lower().startswith("https://"):
        print("For the normal Tailscale setup, use the HTTPS worker URL.")
        return 1

    health = _test_worker(url, token)
    config = load_config()
    config["hybrid_enabled"] = True
    config["hybrid_worker_url"] = url
    config["hybrid_worker_model"] = str(
        health.get("recommended_model") or config.get("hybrid_worker_model", "qwen3:8b")
    )
    config["hybrid_routing_mode"] = "prefer_worker"
    save_config(config)
    save_hybrid_worker_client_token(DATA_DIR, token)

    print()
    print("Hybrid compute is paired.")
    print(f"Worker PC: {health.get('machine_name', 'Powerful PC')}")
    print(f"Worker model: {health.get('recommended_model', 'unknown')}")
    print("Routing: prefer the strong PC when reachable; fall back to this host locally.")
    print()
    print("Restart the XemAi server/app on this always-on host once to load the pairing.")
    return 0


def main() -> int:
    mode = (sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
    silent = "--silent" in sys.argv[2:]
    try:
        if mode == "worker":
            return setup_worker(silent=silent)
        if mode == "host":
            return setup_host()
        print("Usage: python hybrid_setup.py worker|host")
        return 2
    except Exception as e:
        print()
        print(f"Setup failed: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
