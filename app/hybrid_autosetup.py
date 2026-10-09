from __future__ import annotations

import json
import os
import secrets
import shutil
import subprocess
import threading
import urllib.request
from pathlib import Path
from typing import Any

from .config import BASE_DIR, DATA_DIR, load_config, save_config
from .llm import OllamaClient, open_model_request
from .secrets import (
    complete_hybrid_worker_client_pairing,
    load_hybrid_pairing_state,
    save_hybrid_worker_client_pairing,
)
from .version import VERSION


def _tailscale_exe() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    for env_name in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(env_name, "")
        candidate = Path(root) / "Tailscale" / "tailscale.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def _tailscale_json(ts: str, *args: str) -> dict[str, Any] | None:
    try:
        result = subprocess.run(
            [ts, *args], capture_output=True, text=True, timeout=8, check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        value = json.loads(result.stdout)
        return value if isinstance(value, dict) else None
    except Exception:
        return None


def _serve_status(ts: str) -> str:
    try:
        result = subprocess.run(
            [ts, "serve", "status", "--json"], capture_output=True,
            text=True, timeout=8, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return result.stdout + "\n" + result.stderr
    except Exception:
        return ""


def is_central_host(ts: str | None = None) -> bool:
    """Identify the existing phone-facing XemAi host from its Serve route."""
    ts = ts or _tailscale_exe()
    if not ts:
        return False
    config = load_config()
    mobile_port = str(int(config.get("mobile_server_port", 8765)))
    status = _serve_status(ts).lower()
    return bool(status and mobile_port in status)


def _peer_candidates(ts: str) -> tuple[str, list[str]]:
    data = _tailscale_json(ts, "status", "--json")
    if not data:
        return "", []
    self_data = data.get("Self") or {}
    own_name = str(self_data.get("DNSName") or "").strip().rstrip(".")
    peers = data.get("Peer") or data.get("Peers") or {}
    names = []
    for peer in peers.values() if isinstance(peers, dict) else []:
        if not isinstance(peer, dict) or not peer.get("Online"):
            continue
        dns = str(peer.get("DNSName") or "").strip().rstrip(".")
        if dns and dns != own_name:
            names.append(dns)
    return own_name, names


def _request_json(url: str, *, payload: dict | None = None, timeout: float = 3) -> dict:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Cache-Control": "no-store"},
        method="GET" if body is None else "POST",
    )
    with open_model_request(request, timeout=timeout) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Worker returned an invalid response.")
    return value


def _model_size(model: str) -> float:
    import re
    match = re.search(r"(\d+(?:\.\d+)?)\s*b", model.lower())
    return float(match.group(1)) if match else 0.0


def try_auto_pair(logger=None) -> bool:
    """Discover one Qwen worker on the private tailnet and pair it once."""
    config = load_config()
    if config.get("hybrid_worker_url"):
        from .hybrid import build_llm_client
        from .logging_setup import setup_logging
        candidate = dict(config, hybrid_enabled=True)
        client = build_llm_client(candidate, logger or setup_logging(BASE_DIR / "logs"), DATA_DIR)
        if not getattr(client, "is_hybrid", False):
            return False
        if client.refresh_route().get("compute") != "remote_worker":
            return False
        if not config.get("hybrid_enabled"):
            save_config(candidate)
        return True
    if os.environ.get("XEMAI_WORKER_TOKEN", "").strip():
        if logger:
            logger.warning("Hybrid auto-pair skipped | explicit worker-token override is set")
        return True
    ts = _tailscale_exe()
    if not ts or not is_central_host(ts):
        if logger:
            logger.info("Hybrid auto-pair waiting | reason=%s", "Tailscale executable unavailable" if not ts else "No central-host Serve route detected")
        return False
    host_id, peers = _peer_candidates(ts)
    if not host_id or not peers:
        if logger:
            logger.info("Hybrid auto-pair waiting | reason=%s", "Tailscale identity unavailable" if not host_id else "No online Tailscale peers")
        return False

    state = load_hybrid_pairing_state(DATA_DIR)
    if state.get("client_host_id") and state["client_host_id"] != host_id:
        if logger:
            logger.warning("Hybrid auto-pair skipped | configured host identity changed")
        return False
    token = state.get("pending_token") or secrets.token_urlsafe(32)
    save_hybrid_worker_client_pairing(DATA_DIR, host_id=host_id, token=token)
    candidates = []
    for dns in peers:
        url = f"https://{dns}:{int(config.get('hybrid_worker_port', 8766))}"
        try:
            status = _request_json(url + "/api/pair/status", timeout=2.5)
            if status.get("role") == "xemai_hybrid_worker" and status.get("ok"):
                candidates.append((url, status))
        except Exception as e:
            if logger:
                logger.info("Hybrid worker discovery failed | worker=%s error=%s", dns, type(e).__name__)
            continue

    if not candidates and logger:
        logger.info("Hybrid auto-pair waiting | reason=No reachable Qwen workers | peers=%d", len(peers))

    candidates.sort(
        key=lambda item: _model_size(str(item[1].get("recommended_model") or "")),
        reverse=True,
    )
    for url, status in candidates:
        try:
            claimed = _request_json(
                url + "/api/pair/claim",
                payload={"host_id": host_id, "token": token},
                timeout=4,
            )
            if not claimed.get("ok"):
                continue
            health_req = urllib.request.Request(
                url + "/api/health",
                headers={"Authorization": f"Bearer {token}"},
            )
            with open_model_request(health_req, timeout=5) as response:
                health = json.loads(response.read().decode("utf-8"))
            if not health.get("ok"):
                continue
            config["hybrid_enabled"] = True
            config["hybrid_worker_url"] = url
            config["hybrid_worker_model"] = str(
                health.get("recommended_model") or status.get("recommended_model")
                or config.get("hybrid_worker_model", "qwen3:8b")
            )
            config["hybrid_routing_mode"] = "prefer_worker"
            save_config(config)
            complete_hybrid_worker_client_pairing(DATA_DIR)
            if logger:
                logger.info(
                    "Hybrid auto-pair succeeded | worker=%s model=%s",
                    health.get("machine_name", "worker"),
                    config["hybrid_worker_model"],
                )
            return True
        except Exception as e:
            if logger:
                logger.info("Hybrid auto-pair candidate failed | url=%s error=%r", url, e)
    return False


def _has_local_qwen(logger=None) -> bool:
    try:
        from .logging_setup import setup_logging
        client = OllamaClient(
            base_url=str(load_config().get("ollama_url", "http://localhost:11434")),
            model=str(load_config().get("model", "qwen3:8b")),
            logger=logger or setup_logging(BASE_DIR / "logs"),
            provider_name="hybrid-autosetup-check",
        )
        return any(
            "qwen" in str(item.get("name") or item.get("model") or "").lower()
            for item in client.installed_models()
            if isinstance(item, dict)
        )
    except Exception:
        return False


def _ensure_worker(logger=None) -> bool:
    if os.name != "nt":
        return True
    ts = _tailscale_exe()
    tailscale_state = _tailscale_json(ts, "status", "--json") if ts else None
    if not tailscale_state or not str(
        (tailscale_state.get("Self") or {}).get("DNSName") or ""
    ).strip():
        if logger:
            logger.info("Hybrid worker setup waiting | reason=%s", "Tailscale executable unavailable" if not ts else "Tailscale identity unavailable")
        return False
    if is_central_host(ts):
        return True
    if not _has_local_qwen(logger):
        if logger:
            logger.info("Hybrid worker setup waiting | reason=Local Ollama has no reachable Qwen model")
        return False
    local_status = _request_worker_local_status()
    worker_port = str(int(load_config().get("hybrid_worker_port", 8766)))
    if local_status and worker_port in _serve_status(ts):
        return True

    attempted = DATA_DIR / "hybrid_worker_autosetup_attempted"
    try:
        if attempted.read_text(encoding="utf-8").strip() == VERSION:
            import time
            if time.time() - attempted.stat().st_mtime < 120:
                return False
    except OSError:
        pass
    attempted.parent.mkdir(parents=True, exist_ok=True)
    attempted.write_text(VERSION + "\n", encoding="utf-8")
    setup = BASE_DIR / "hybrid_worker_setup.bat"
    if not setup.is_file():
        return False
    try:
        subprocess.Popen(
            ["cmd.exe", "/c", "start", "", str(setup), "--silent"],
            cwd=str(BASE_DIR),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if logger:
            logger.info("Hybrid worker auto-setup launched with Windows approval prompt")
        return False
    except Exception as e:
        if logger:
            logger.warning("Hybrid worker auto-setup could not launch | error=%r", e)
        try:
            attempted.unlink()
        except OSError:
            pass
        return False


def _request_worker_local_status() -> bool:
    port = int(load_config().get("hybrid_worker_port", 8766))
    try:
        value = _request_json(f"http://127.0.0.1:{port}/api/pair/status", timeout=1)
        return value.get("role") == "xemai_hybrid_worker"
    except Exception:
        return False


def start_hybrid_auto_setup(stop_event, logger=None) -> threading.Thread:
    def loop() -> None:
        if stop_event.wait(15):
            return
        # Tailscale can start or restore Serve routes after XemAi. Re-evaluate
        # the role each time instead of permanently selecting it at startup.
        while not stop_event.is_set():
            try:
                central = is_central_host()
                if logger:
                    logger.info("Hybrid auto-setup check | role=%s", "host" if central else "worker-or-waiting")
                if central:
                    try_auto_pair(logger)
                else:
                    _ensure_worker(logger)
            except Exception as e:
                if logger:
                    logger.warning("Hybrid auto-setup check failed; will retry | error=%s", type(e).__name__)
            if stop_event.wait(60):
                return

    thread = threading.Thread(target=loop, daemon=True, name="XemAiHybridAutoSetup")
    thread.start()
    return thread
