from __future__ import annotations

import json
import os
import platform
import re
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import DATA_DIR, LOG_DIR, load_config
from .llm import OllamaClient
from .logging_setup import setup_logging
from .secrets import ensure_hybrid_worker_server_token
from .version import VERSION

MAX_BODY = 8_000_000


def _model_name(item: dict) -> str:
    return str(item.get("name") or item.get("model") or "").strip()


def _parameter_billions(item: dict) -> float:
    details = item.get("details") if isinstance(item, dict) else {}
    value = str(
        (details or {}).get("parameter_size")
        or _model_name(item)
        or ""
    ).lower()
    match = re.search(r"(\d+(?:\.\d+)?)\s*b", value)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return 0.0


def _qwen_only(items) -> list[dict]:
    return [
        item for item in items
        if isinstance(item, dict) and "qwen" in _model_name(item).lower()
    ]


def _recommended_model(client: OllamaClient) -> tuple[str, list[str], list[str]]:
    installed = _qwen_only(client.installed_models())
    try:
        running = _qwen_only(client.running_models())
    except Exception:
        running = []

    # A running model is treated as deliberate. Otherwise choose the largest
    # installed Qwen model on the stronger worker PC.
    pool = running or installed
    selected = max(
        pool,
        key=lambda item: (
            _parameter_billions(item),
            str(item.get("modified_at", "")),
        ),
        default=None,
    )
    model = _model_name(selected) if selected else ""
    return (
        model,
        [_model_name(item) for item in installed if _model_name(item)],
        [_model_name(item) for item in running if _model_name(item)],
    )


class XemAiWorkerHandler(BaseHTTPRequestHandler):
    server_version = "XemAiWorker/1.0"

    def log_message(self, format, *args):
        logger = getattr(self.server, "xemai_logger", None)
        if logger:
            logger.debug("Worker HTTP | " + format, *args)

    def _json(self, payload: dict, status=HTTPStatus.OK) -> None:
        raw = json.dumps(payload).encode("utf-8")
        self.send_response(int(status))
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _error(self, message, status=HTTPStatus.BAD_REQUEST) -> None:
        self._json({"ok": False, "error": str(message)}, status)

    def _authorized(self) -> bool:
        expected = getattr(self.server, "worker_token", "")
        supplied = self.headers.get("Authorization", "")
        return bool(expected) and supplied == f"Bearer {expected}"

    def _require_auth(self) -> bool:
        if self._authorized():
            return True
        self._error("Unauthorized.", HTTPStatus.UNAUTHORIZED)
        return False

    def _read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid Content-Length.")
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("Request body is too large.")
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw.decode("utf-8"))
        except Exception as e:
            raise ValueError("Invalid JSON body.") from e
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object.")
        return value

    def do_GET(self):
        if not self._require_auth():
            return

        client = self.server.ollama_client
        try:
            if self.path == "/api/health":
                if not client.health_check():
                    self._error(
                        "Worker can run, but local Ollama is unavailable.",
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                    return
                model, installed, running = _recommended_model(client)
                if not model:
                    self._error(
                        "No installed Qwen model was found on this worker.",
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                    return
                self._json({
                    "ok": True,
                    "version": VERSION,
                    "role": "xemai_hybrid_worker",
                    "machine_name": platform.node() or "Powerful PC",
                    "recommended_model": model,
                    "installed_qwen": installed,
                    "running_qwen": running,
                })
                return

            if self.path == "/api/tags":
                data = client._request("/api/tags", timeout=10)
                data["models"] = _qwen_only(data.get("models", []))
                self._json(data)
                return

            if self.path == "/api/ps":
                data = client._request("/api/ps", timeout=10)
                data["models"] = _qwen_only(data.get("models", []))
                self._json(data)
                return

            self._error("Unknown worker endpoint.", HTTPStatus.NOT_FOUND)
        except Exception as e:
            self._error(e, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self):
        if not self._require_auth():
            return
        if self.path != "/api/chat":
            self._error("Unknown worker endpoint.", HTTPStatus.NOT_FOUND)
            return

        try:
            payload = self._read_json()
            payload["stream"] = False

            client = self.server.ollama_client
            recommended, installed, _ = _recommended_model(client)
            requested = str(payload.get("model") or recommended).strip()
            if not requested:
                self._error("No Qwen model is available on this worker.")
                return

            installed_names = set(installed)
            if (
                "qwen" not in requested.lower()
                or requested not in installed_names
            ):
                self._error(
                    f"Worker model '{requested}' is not an installed Qwen model.",
                    HTTPStatus.BAD_REQUEST,
                )
                return

            payload["model"] = requested
            with self.server.generation_lock:
                result = client._request(
                    "/api/chat",
                    payload=payload,
                    timeout=600,
                )
            self._json(result)
        except ValueError as e:
            self._error(e, HTTPStatus.BAD_REQUEST)
        except Exception as e:
            self._error(e, HTTPStatus.INTERNAL_SERVER_ERROR)


class XemAiWorkerServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def run_worker_server() -> int:
    config = load_config()
    logger = setup_logging(LOG_DIR)
    token = ensure_hybrid_worker_server_token(DATA_DIR)
    port = int(config.get("hybrid_worker_port", 8766))
    host = "127.0.0.1"

    ollama = OllamaClient(
        base_url=str(config.get("ollama_url", "http://localhost:11434")),
        model=str(config.get("model", "qwen3:8b")),
        logger=logger,
        provider_name="worker-local-ollama",
    )

    try:
        server = XemAiWorkerServer((host, port), XemAiWorkerHandler)
    except OSError as e:
        logger.info(
            "Hybrid worker not started | host=%s port=%s reason=%r",
            host,
            port,
            e,
        )
        return 0

    server.xemai_logger = logger
    server.worker_token = token
    server.ollama_client = ollama
    server.generation_lock = threading.Lock()

    state_path = DATA_DIR / "hybrid_worker.json"
    try:
        state_path.write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "version": VERSION,
                    "host": host,
                    "port": port,
                    "machine_name": platform.node(),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    except OSError:
        pass

    logger.info(
        "Hybrid worker start | version=%s host=%s port=%s machine=%s pid=%s",
        VERSION,
        host,
        port,
        platform.node(),
        os.getpid(),
    )
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        try:
            if state_path.exists():
                current = json.loads(state_path.read_text(encoding="utf-8"))
                if int(current.get("pid", -1)) == os.getpid():
                    state_path.unlink()
        except Exception:
            pass
        logger.info("Hybrid worker stop")
    return 0
