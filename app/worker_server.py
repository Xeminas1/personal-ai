from __future__ import annotations

import json
import math
import os
import platform
import re
import shutil
import subprocess
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import BASE_DIR, DATA_DIR, LOG_DIR, load_config
from .support_http import handle_support_read
from .llm import OllamaClient
from .logging_setup import setup_logging
from .secrets import (
    claim_hybrid_worker_pairing,
    ensure_hybrid_worker_server_token,
    load_hybrid_pairing_state,
)
from .version import VERSION
from .vision import VisionService, is_vision_model

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
        and not is_vision_model(item)
    ]


def _recommended_model(client: OllamaClient) -> tuple[str, list[str], list[str]]:
    installed = _qwen_only(client.installed_models())
    try:
        running = _qwen_only(client.running_models())
    except Exception:
        running = []

    # Keep the configured everyday worker model stable even when a larger
    # teacher is temporarily running after a review.
    configured = str(getattr(client, "model", "") or "").strip().lower()
    selected = next(
        (
            item for item in installed
            if _model_name(item).lower() == configured
            or _model_name(item).lower() == configured + ":latest"
        ),
        None,
    )
    if selected is None:
        teacher_names = {"qwen3:14b", "qwen3:30b"}
        ordinary_running = [
            item for item in running
            if _model_name(item).lower().replace(":latest", "") not in teacher_names
        ]
        ordinary_installed = [
            item for item in installed
            if _model_name(item).lower().replace(":latest", "") not in teacher_names
        ]
        pool = ordinary_running or ordinary_installed or running or installed
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


def _ollama_executable() -> str:
    found = shutil.which("ollama")
    if found:
        return found
    candidates = [
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path(os.environ.get("ProgramFiles", "")) / "Ollama" / "ollama.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    return "ollama"


def _system_ram_gb() -> float:
    try:
        import ctypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return round(status.ullTotalPhys / (1024 ** 3), 1)
    except Exception:
        pass
    try:
        if hasattr(os, "sysconf"):
            pages = os.sysconf("SC_PHYS_PAGES")
            size = os.sysconf("SC_PAGE_SIZE")
            return round((pages * size) / (1024 ** 3), 1)
    except Exception:
        pass
    return 0.0


def _nvidia_vram_gb() -> float:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.total",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        values = []
        for line in result.stdout.splitlines():
            try:
                values.append(float(line.strip()) / 1024.0)
            except ValueError:
                pass
        return round(max(values), 1) if values else 0.0
    except Exception:
        return 0.0


def _teacher_target_model() -> tuple[str, dict]:
    ram_gb = _system_ram_gb()
    vram_gb = _nvidia_vram_gb()
    if vram_gb >= 20 or ram_gb >= 48:
        target = "qwen3:30b"
    elif vram_gb >= 12 or ram_gb >= 24:
        target = "qwen3:14b"
    else:
        target = ""
    return target, {"system_ram_gb": ram_gb, "gpu_vram_gb": vram_gb}


def _installed_model_names(client: OllamaClient) -> list[str]:
    return [
        _model_name(item)
        for item in client.installed_models()
        if isinstance(item, dict) and _model_name(item)
    ]


def _teacher_model(client: OllamaClient) -> tuple[str, dict]:
    target, hardware = _teacher_target_model()
    installed = _installed_model_names(client)
    installed_lower = {
        name.lower().replace(":latest", ""): name
        for name in installed
    }
    for candidate in (target, "qwen3:30b", "qwen3:14b"):
        key = candidate.lower().replace(":latest", "")
        if candidate and key in installed_lower:
            return installed_lower[key], hardware
    return "", {**hardware, "target_model": target, "installed_models": installed}


def _teacher_health_snapshot(server, installed: list[str]) -> tuple[str, dict]:
    """Describe optional teacher availability without another hardware/API probe.

    Ordinary health already retrieved the model inventory. Hardware remains
    unknown until optional preparation has sampled it; stale/malformed optional
    metadata must not turn a usable everyday worker into an unavailable one.
    """
    hardware = {}
    target = ""
    try:
        cached = getattr(server, "teacher_hardware", None)
        if isinstance(cached, dict):
            for key in ("system_ram_gb", "gpu_vram_gb"):
                value = cached.get(key)
                if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0:
                    hardware[key] = value
            if cached.get("target_model") in ("qwen3:14b", "qwen3:30b"):
                target = cached["target_model"]
                hardware["target_model"] = target
    except Exception:
        hardware = {}
    names = {name.lower().replace(":latest", ""): name for name in installed}
    model = next((names[name] for name in (target, "qwen3:30b", "qwen3:14b") if name and name in names), "")
    return model, hardware


def _ensure_teacher_model_async(server) -> None:
    if getattr(server, "teacher_install_started", False):
        return
    config = load_config()
    if not bool(config.get("teacher_enabled", True)) or not bool(
        config.get("teacher_auto_install", True)
    ):
        return
    target, hardware = _teacher_target_model()
    server.teacher_hardware = {**hardware, "target_model": target}
    if not target:
        return
    try:
        installed = {
            name.lower().replace(":latest", "")
            for name in _installed_model_names(server.ollama_client)
        }
    except Exception:
        return
    if target.lower() in installed:
        return

    server.teacher_install_started = True

    def install() -> None:
        logger = getattr(server, "xemai_logger", None)
        try:
            if logger:
                logger.info(
                    "Teacher model install start | target=%s ram_gb=%s vram_gb=%s",
                    target,
                    hardware.get("system_ram_gb", 0),
                    hardware.get("gpu_vram_gb", 0),
                )
            result = subprocess.run(
                [_ollama_executable(), "pull", target],
                cwd=str(BASE_DIR),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=6 * 60 * 60,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if logger:
                logger.info(
                    "Teacher model install finish | target=%s returncode=%s",
                    target,
                    result.returncode,
                )
        except Exception as e:
            if logger:
                logger.warning(
                    "Teacher model install failed | target=%s error=%r",
                    target,
                    e,
                )
        finally:
            server.teacher_install_started = False

    threading.Thread(
        target=install,
        daemon=True,
        name="XemAiTeacherInstall",
    ).start()


def _teacher_review_prompt(question: str, draft: str) -> list[dict]:
    return [
        {
            "role": "system",
            "content": (
                "You are XemAi's independent local teacher and critic. Review the "
                "draft for factual mistakes, faulty reasoning, missed constraints, "
                "unsafe assumptions and important omissions. Do not agree merely to "
                "be polite. Return a better final answer only, written for the user. "
                "Preserve correct useful details, avoid inventing facts or citations, "
                "and state uncertainty when it remains."
            ),
        },
        {
            "role": "user",
            "content": (
                "USER QUESTION:\n" + question.strip() + "\n\n"
                "XEMAI DRAFT:\n" + draft.strip()
            ),
        },
    ]


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
        self.send_header("X-Content-Type-Options", "nosniff")
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
        if handle_support_read(self, BASE_DIR):
            return
        if self.path == "/api/pair/status":
            client = self.server.ollama_client
            try:
                model, installed, running = _recommended_model(client)
                pairing = load_hybrid_pairing_state(DATA_DIR)
                self._json({
                    "ok": bool(model),
                    "role": "xemai_hybrid_worker",
                    "pairing_available": not bool(pairing["host_id"]),
                    "machine_name": platform.node() or "Powerful PC",
                    "recommended_model": model,
                    "installed_qwen": installed,
                    "running_qwen": running,
                })
            except Exception as e:
                self._error(e, HTTPStatus.SERVICE_UNAVAILABLE)
            return

        if not self._require_auth():
            return

        client = self.server.ollama_client
        try:
            if self.path == "/api/vision/status":
                service = getattr(self.server, "vision_service", None)
                if service is None:
                    self._error("Vision service is unavailable on this worker.", HTTPStatus.SERVICE_UNAVAILABLE)
                else:
                    self._json({"ok": True, **service.status()})
                return

            if self.path == "/api/health":
                try:
                    # Inventory retrieval already checks Ollama connectivity;
                    # avoid an extra /api/tags request before discovering it.
                    model, installed, running = _recommended_model(client)
                except Exception:
                    self._error(
                        "Worker can run, but local Ollama is unavailable.",
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                    return
                if not model:
                    self._error(
                        "No installed Qwen model was found on this worker.",
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                    return
                teacher_model, teacher_hardware = _teacher_health_snapshot(self.server, installed)
                self._json({
                    "ok": True,
                    "version": VERSION,
                    "role": "xemai_hybrid_worker",
                    "machine_name": platform.node() or "Powerful PC",
                    "recommended_model": model,
                    "installed_qwen": installed,
                    "running_qwen": running,
                    "teacher_model": teacher_model,
                    "teacher_hardware": teacher_hardware,
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
        if self.path.startswith("/api/support/"):
            self._error("Support access is read-only.", HTTPStatus.METHOD_NOT_ALLOWED)
            return
        if self.path == "/api/pair/claim":
            try:
                payload = self._read_json()
                host_id = str(payload.get("host_id") or "").strip()
                token = str(payload.get("token") or "").strip()
                with self.server.pairing_lock:
                    if not claim_hybrid_worker_pairing(
                        DATA_DIR, host_id=host_id, token=token
                    ):
                        self._error(
                            "Pairing was rejected. This worker may already be paired.",
                            HTTPStatus.CONFLICT,
                        )
                        return
                    self.server.worker_token = token
                try:
                    (DATA_DIR / "hybrid_pairing.txt").unlink()
                except OSError:
                    pass
                model, installed, running = _recommended_model(
                    self.server.ollama_client
                )
                self._json({
                    "ok": True,
                    "machine_name": platform.node() or "Powerful PC",
                    "recommended_model": model,
                    "installed_qwen": installed,
                    "running_qwen": running,
                })
            except ValueError as e:
                self._error(e, HTTPStatus.BAD_REQUEST)
            except Exception as e:
                self._error(e, HTTPStatus.INTERNAL_SERVER_ERROR)
            return

        if not self._require_auth():
            return
        if self.path in {"/api/vision/setup", "/api/vision/analyse"}:
            try:
                service = getattr(self.server, "vision_service", None)
                if service is None:
                    self._error("Vision service is unavailable on this worker.", HTTPStatus.SERVICE_UNAVAILABLE)
                    return
                payload = self._read_json()
                if self.path == "/api/vision/setup":
                    if payload:
                        raise ValueError("Vision setup accepts no model or request options.")
                    result = service.start_setup()
                else:
                    if set(payload) - {"images", "prompt"}:
                        raise ValueError("Invalid visual-analysis request fields.")
                    result = service.analyse(payload.get("images"), payload.get("prompt"))
                self._json({"ok": True, **result})
            except ValueError as error:
                self._error(error, HTTPStatus.BAD_REQUEST)
            except Exception:
                self._error("Vision service could not complete this request.", HTTPStatus.SERVICE_UNAVAILABLE)
            return
        if self.path == "/api/teacher/review":
            try:
                config = load_config()
                if not bool(config.get("teacher_enabled", True)):
                    self._error(
                        "Teacher review is disabled.",
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                    return
                payload = self._read_json()
                if set(payload) - {"question", "draft"}:
                    raise ValueError("Invalid teacher-review request fields.")
                question = str(payload.get("question") or "").strip()
                draft = str(payload.get("draft") or "").strip()
                if not question or not draft:
                    raise ValueError("Teacher review requires question and draft.")

                model, hardware = _teacher_model(self.server.ollama_client)
                if not model:
                    _ensure_teacher_model_async(self.server)
                    self._json(
                        {
                            "ok": False,
                            "ready": False,
                            "error": "A stronger local teacher model is not ready yet.",
                            "target_model": hardware.get("target_model", ""),
                            "hardware": hardware,
                        },
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                    return

                review_payload = {
                    "model": model,
                    "messages": _teacher_review_prompt(question, draft),
                    "stream": False,
                }
                with self.server.generation_lock:
                    result = self.server.ollama_client._request(
                        "/api/chat",
                        payload=review_payload,
                        timeout=900,
                    )
                message = result.get("message") or {}
                content = str(message.get("content") or "").strip()
                if not content:
                    self._error(
                        "Teacher model returned no review.",
                        HTTPStatus.BAD_GATEWAY,
                    )
                    return
                self._json(
                    {
                        "ok": True,
                        "ready": True,
                        "model": model,
                        "answer": content,
                        "hardware": hardware,
                    }
                )
            except ValueError as e:
                self._error(e, HTTPStatus.BAD_REQUEST)
            except Exception:
                self._error(
                    "Teacher review could not complete.",
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
            return
        if self.path != "/api/chat":
            self._error("Unknown worker endpoint.", HTTPStatus.NOT_FOUND)
            return

        discovery_ms = queue_ms = generation_ms = 0
        success = False
        discovery_started = None
        try:
            payload = self._read_json()
            payload["stream"] = False

            client = self.server.ollama_client
            discovery_started = time.perf_counter()
            if payload.get("model"):
                # The host already selected its model. Validate it without a
                # second running-model discovery before each inference call.
                requested = str(payload["model"]).strip()
                installed = [_model_name(item) for item in _qwen_only(client.installed_models())]
            else:
                requested, installed, _ = _recommended_model(client)
                requested = requested.strip()
            discovery_ms = max(0, int((time.perf_counter() - discovery_started) * 1000))
            discovery_started = None
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
            queue_started = time.perf_counter()
            with self.server.generation_lock:
                generation_started = time.perf_counter()
                queue_ms = max(0, int((generation_started - queue_started) * 1000))
                try:
                    result = client._request(
                        "/api/chat",
                        payload=payload,
                        timeout=600,
                    )
                finally:
                    generation_ms = max(0, int((time.perf_counter() - generation_started) * 1000))
            success = True
            self._json(result)
        except ValueError as e:
            self._error(e, HTTPStatus.BAD_REQUEST)
        except Exception as e:
            self._error(e, HTTPStatus.INTERNAL_SERVER_ERROR)
        finally:
            if discovery_started is not None:
                discovery_ms = max(0, int((time.perf_counter() - discovery_started) * 1000))
            logger = getattr(self.server, "xemai_logger", None)
            if logger:
                logger.info(
                    "Worker timing | discovery_ms=%d queue_ms=%d generation_ms=%d success=%s",
                    discovery_ms, queue_ms, generation_ms, success,
                )


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
    server.pairing_lock = threading.Lock()
    server.vision_service = VisionService(ollama, server.generation_lock, logger)
    server.teacher_install_started = False
    try:
        _ensure_teacher_model_async(server)
    except Exception:
        logger.info("Teacher preparation unavailable; ordinary worker startup continues")

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
