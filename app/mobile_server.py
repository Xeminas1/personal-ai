from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .config import DATA_DIR, LOG_DIR, load_config
from .database import Database
from .gui_backend import ChatBackend
from .logging_setup import setup_logging
from .version import VERSION


BASE_DIR = Path(__file__).resolve().parent.parent
MOBILE_DIR = BASE_DIR / "mobile"
MAX_BODY = 8_000_000
MAX_ATTACHMENT_BYTES = 5_000_000
MAX_ATTACHMENTS_PER_MESSAGE = 3


def _pythonw_executable() -> Path:
    exe = Path(sys.executable)
    if os.name == "nt":
        candidate = exe.with_name("pythonw.exe")
        if candidate.exists():
            return candidate
    return exe


def _schedule_mobile_server_restart() -> None:
    """
    Launch a tiny detached helper that waits for this server process to exit,
    then starts the freshly updated XemAi mobile server.
    """
    executable = _pythonw_executable()
    script = BASE_DIR / "XemAiServer.pyw"
    helper_code = (
        "import subprocess,sys,time;"
        "time.sleep(2.5);"
        "subprocess.Popen([sys.argv[1],sys.argv[2]],"
        "cwd=sys.argv[3],stdin=subprocess.DEVNULL,"
        "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,"
        "close_fds=True)"
    )
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

    subprocess.Popen(
        [
            str(executable),
            "-c",
            helper_code,
            str(executable),
            str(script),
            str(BASE_DIR),
        ],
        **kwargs,
    )

    def stop_current():
        time.sleep(1.5)
        # The response has already been sent. Exit immediately so the helper can
        # bind the same localhost port using the newly installed code.
        os._exit(0)

    threading.Thread(target=stop_current, daemon=True).start()


def _active_chat_requests(server) -> int:
    lock = getattr(server, "activity_lock", None)
    if lock is None:
        return 0
    with lock:
        return int(getattr(server, "active_chat_requests", 0))


def _change_active_chat_requests(server, delta: int) -> None:
    lock = getattr(server, "activity_lock", None)
    if lock is None:
        return
    with lock:
        current = int(getattr(server, "active_chat_requests", 0))
        server.active_chat_requests = max(0, current + int(delta))


def _set_chat_activity(server, chat_id: int, status: str | None) -> None:
    lock = getattr(server, "activity_lock", None)
    if lock is None:
        return
    with lock:
        activity = getattr(server, "chat_activity", None)
        if activity is None:
            activity = {}
            server.chat_activity = activity
        if status:
            activity[int(chat_id)] = {
                "status": str(status),
                "updated_at": time.time(),
            }
        else:
            activity.pop(int(chat_id), None)


def _get_chat_activity(server, chat_id: int) -> dict:
    lock = getattr(server, "activity_lock", None)
    if lock is None:
        return {"active": False, "status": None}
    with lock:
        item = dict(getattr(server, "chat_activity", {}).get(int(chat_id), {}))
    if not item:
        return {"active": False, "status": None}
    return {
        "active": True,
        "status": str(item.get("status") or "XemAi is thinking"),
    }


def _run_chat_generation(
    server,
    chat_id: int,
    text: str,
    *,
    attachments=None,
    record_user: bool = True,
) -> None:
    backend = None
    logger = getattr(server, "xemai_logger", None)
    try:
        backend = ChatBackend()
        backend.send(
            chat_id,
            text,
            status_callback=lambda status: _set_chat_activity(
                server, chat_id, status
            ),
            record_user=record_user,
            attachments=attachments,
        )
    except Exception as e:
        if logger:
            logger.error(
                "Background reply generation failed | chat_id=%s error=%r",
                chat_id,
                e,
            )
    finally:
        if backend:
            try:
                backend.close()
            except Exception:
                pass
        _set_chat_activity(server, chat_id, None)
        _change_active_chat_requests(server, -1)


def _start_chat_generation(
    server,
    chat_id: int,
    text: str,
    *,
    attachments=None,
    record_user: bool = True,
) -> None:
    if _active_chat_requests(server) > 0:
        raise RuntimeError("XemAi is already working on another reply.")
    if _get_chat_activity(server, chat_id).get("active"):
        raise RuntimeError("XemAi is already working on a reply in this chat.")

    _change_active_chat_requests(server, 1)
    _set_chat_activity(server, chat_id, "XemAi is thinking")
    try:
        worker = threading.Thread(
            target=_run_chat_generation,
            kwargs={
                "server": server,
                "chat_id": int(chat_id),
                "text": str(text),
                "attachments": attachments,
                "record_user": bool(record_user),
            },
            daemon=True,
            name=f"XemAiReply-{int(chat_id)}",
        )
        worker.start()
    except Exception:
        _set_chat_activity(server, chat_id, None)
        _change_active_chat_requests(server, -1)
        raise

def _auto_update_loop(server) -> None:
    logger = getattr(server, "xemai_logger", None)
    stop_event = getattr(server, "stop_event", None)
    if stop_event is None:
        return

    # Give startup a moment to settle, then check periodically.
    if stop_event.wait(8):
        return

    while not stop_event.is_set():
        backend = None
        try:
            config = load_config()
            enabled = bool(config.get("mobile_updates_enabled", True))
            auto_install = bool(config.get("auto_install_updates", True))
            interval = max(
                30,
                int(config.get("auto_update_interval_seconds", 60)),
            )

            if enabled and auto_install and _active_chat_requests(server) == 0:
                update_lock = getattr(server, "update_lock", None)
                acquired = update_lock.acquire(blocking=False) if update_lock else True
                if acquired:
                    try:
                        backend = ChatBackend()
                        manifest = backend.check_update()
                        if manifest and _active_chat_requests(server) == 0:
                            installed = backend.install_update(manifest)
                            if logger:
                                logger.info(
                                    "Automatic update installed | from=%s to=%s",
                                    VERSION,
                                    installed,
                                )
                            server.update_restarting = True
                            _schedule_mobile_server_restart()
                            return
                    finally:
                        if backend:
                            backend.close()
                            backend = None
                        if update_lock:
                            update_lock.release()

            if stop_event.wait(interval):
                return
        except Exception as e:
            if backend:
                try:
                    backend.close()
                except Exception:
                    pass
                backend = None
            if logger:
                logger.warning("Automatic update check failed | error=%r", e)
            try:
                interval = max(
                    30,
                    int(load_config().get("auto_update_interval_seconds", 60)),
                )
            except Exception:
                interval = 60
            if stop_event.wait(interval):
                return


def _attachment_root(chat_id: int) -> Path:
    root = (DATA_DIR / "attachments" / f"chat_{int(chat_id)}").resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _validated_attachment_refs(chat_id: int, items) -> list[dict]:
    if items in (None, ""):
        return []
    if not isinstance(items, list):
        raise ValueError("Attachments must be a list.")
    if len(items) > MAX_ATTACHMENTS_PER_MESSAGE:
        raise ValueError(
            f"A maximum of {MAX_ATTACHMENTS_PER_MESSAGE} files can be attached to one message."
        )

    root = _attachment_root(chat_id)
    validated = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Invalid attachment reference.")
        relative = str(item.get("path", "")).replace("\\", "/").strip()
        target = (DATA_DIR / relative).resolve()
        if root != target.parent and root not in target.parents:
            raise ValueError("Attachment is outside this chat.")
        if not target.is_file():
            raise ValueError("Attached file could not be found on the XemAi host.")
        size = target.stat().st_size
        if size > MAX_ATTACHMENT_BYTES:
            raise ValueError("Attached file is too large.")
        validated.append({
            "name": Path(str(item.get("name", target.name))).name[:160],
            "path": str(target.relative_to(DATA_DIR)).replace("\\", "/"),
            "mime": str(item.get("mime", "application/octet-stream"))[:120],
            "size": size,
        })
    return validated


def _row_dict(row) -> dict:
    return {key: row[key] for key in row.keys()}


class XemAiMobileHandler(BaseHTTPRequestHandler):
    server_version = "XemAiMobile/0.4.5"

    def log_message(self, fmt, *args):
        logger = getattr(self.server, "xemai_logger", None)
        if logger:
            logger.debug("Mobile HTTP | " + fmt, *args)

    def _json(self, payload, status=HTTPStatus.OK):
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(raw)

    def _error(self, message, status=HTTPStatus.BAD_REQUEST):
        self._json({"ok": False, "error": str(message)}, status)

    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid Content-Length.")
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("Request is too large.")
        raw = self.rfile.read(length)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise ValueError("Request body must be valid JSON.") from e
        if not isinstance(value, dict):
            raise ValueError("JSON body must be an object.")
        return value

    def _backend(self):
        backend = ChatBackend()
        if backend.user is None:
            backend.close()
            raise RuntimeError(
                "No XemAi user profile exists yet. Open the Windows app first."
            )
        return backend

    def _serve_static(self, request_path: str):
        if request_path in {"", "/"}:
            relative = Path("index.html")
        else:
            relative = Path(request_path.lstrip("/"))

        if ".." in relative.parts or relative.is_absolute():
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        target = (MOBILE_DIR / relative).resolve()
        if MOBILE_DIR.resolve() not in target.parents and target != MOBILE_DIR.resolve():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        if not target.is_file():
            # Client-side routes fall back to the app shell.
            if "." not in relative.name:
                target = MOBILE_DIR / "index.html"
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return

        data = target.read_bytes()
        content_type, _ = mimetypes.guess_type(str(target))
        content_type = content_type or "application/octet-stream"

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "script-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "base-uri 'none'; frame-ancestors 'none'"
        )
        if target.name == "sw.js":
            self.send_header("Service-Worker-Allowed", "/")
            self.send_header("Cache-Control", "no-store, max-age=0")
        elif target.suffix in {".html", ".js", ".css", ".webmanifest"}:
            self.send_header("Cache-Control", "no-store, max-age=0")
        else:
            self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/health":
            self._json({
                "ok": True,
                "version": VERSION,
                "pid": os.getpid(),
                "server": "XemAiMobile",
            })
            return

        if path == "/api/bootstrap":
            backend = None
            try:
                backend = self._backend()
                capabilities = backend.capabilities()
                runtime_model_info = dict(backend.runtime_model_info)
                self._json({
                    "ok": True,
                    "version": VERSION,
                    "assistant_name": backend.config.get("assistant_name", "XemAi"),
                    "runtime_model": runtime_model_info.get("model", "unknown"),
                    "model_source": runtime_model_info.get("source", "unknown"),
                    "compute_source": runtime_model_info.get("compute", "local_host"),
                    "compute_name": runtime_model_info.get("compute_name", "Always-on host"),
                    "worker_available": bool(runtime_model_info.get("worker_available", False)),
                    "installed_qwen": runtime_model_info.get("installed_qwen", []),
                    "user": {
                        "id": backend.user["id"],
                        "name": backend.user["name"],
                    },
                    "capabilities": capabilities,
                })
            except Exception as e:
                self._error(e, HTTPStatus.INTERNAL_SERVER_ERROR)
            finally:
                if backend:
                    backend.close()
            return

        if path == "/api/chats":
            backend = None
            try:
                backend = self._backend()
                chats = [_row_dict(row) for row in backend.chats()]
                self._json({"ok": True, "chats": chats})
            except Exception as e:
                self._error(e, HTTPStatus.INTERNAL_SERVER_ERROR)
            finally:
                if backend:
                    backend.close()
            return

        match = re.fullmatch(r"/api/chats/(\d+)/activity", path)
        if match:
            chat_id = int(match.group(1))
            activity = _get_chat_activity(self.server, chat_id)
            self._json({"ok": True, **activity})
            return

        match = re.fullmatch(r"/api/chats/(\d+)/messages", path)
        if match:
            backend = None
            try:
                chat_id = int(match.group(1))
                backend = self._backend()
                chat = backend.get_chat(chat_id)
                if chat is None or chat["user_id"] != backend.user["id"]:
                    self._error("Chat not found.", HTTPStatus.NOT_FOUND)
                    return
                messages = [
                    _row_dict(row)
                    for row in backend.messages(chat_id)
                    if row["role"] in {"user", "assistant"}
                ]
                self._json({
                    "ok": True,
                    "chat": _row_dict(chat),
                    "messages": messages,
                })
            except Exception as e:
                self._error(e, HTTPStatus.INTERNAL_SERVER_ERROR)
            finally:
                if backend:
                    backend.close()
            return

        if path == "/api/update":
            backend = None
            try:
                backend = self._backend()
                enabled = bool(
                    backend.config.get("mobile_updates_enabled", True)
                )
                if not enabled:
                    self._json({
                        "ok": True,
                        "enabled": False,
                        "current_version": VERSION,
                        "update": None,
                    })
                    return

                manifest = backend.check_update()
                self._json({
                    "ok": True,
                    "enabled": True,
                    "current_version": VERSION,
                    "update": (
                        {
                            "version": str(manifest["version"]),
                            "notes": str(manifest.get("notes", "")),
                        }
                        if manifest else None
                    ),
                })
            except Exception as e:
                self._error(e, HTTPStatus.INTERNAL_SERVER_ERROR)
            finally:
                if backend:
                    backend.close()
            return

        if path == "/api/capabilities":
            backend = None
            try:
                backend = self._backend()
                self._json({
                    "ok": True,
                    "capabilities": backend.capabilities(),
                })
            except Exception as e:
                self._error(e, HTTPStatus.INTERNAL_SERVER_ERROR)
            finally:
                if backend:
                    backend.close()
            return

        if path.startswith("/api/"):
            self._error("Unknown API endpoint.", HTTPStatus.NOT_FOUND)
            return

        self._serve_static(path)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path

        try:
            body = self._read_json()
        except ValueError as e:
            self._error(e)
            return

        if path == "/api/chats":
            backend = None
            try:
                backend = self._backend()
                chat = backend.create_chat()
                self._json(
                    {"ok": True, "chat": _row_dict(chat)},
                    HTTPStatus.CREATED,
                )
            except Exception as e:
                self._error(e, HTTPStatus.INTERNAL_SERVER_ERROR)
            finally:
                if backend:
                    backend.close()
            return

        match = re.fullmatch(r"/api/chats/(\d+)/attachments", path)
        if match:
            backend = None
            try:
                chat_id = int(match.group(1))
                backend = self._backend()
                chat = backend.get_chat(chat_id)
                if chat is None or chat["user_id"] != backend.user["id"]:
                    self._error("Chat not found.", HTTPStatus.NOT_FOUND)
                    return

                original_name = Path(str(body.get("name", "")).strip()).name
                if not original_name:
                    self._error("A file name is required.")
                    return

                encoded = str(body.get("data", "")).strip()
                if not encoded:
                    self._error("File data is required.")
                    return
                try:
                    raw = base64.b64decode(encoded, validate=True)
                except Exception:
                    self._error("Attachment data is not valid base64.")
                    return
                if len(raw) > MAX_ATTACHMENT_BYTES:
                    self._error(
                        f"Files are limited to {MAX_ATTACHMENT_BYTES // 1_000_000} MB."
                    )
                    return

                safe_name = re.sub(
                    r"[^A-Za-z0-9._ ()\-]+", "_", original_name
                ).strip(" .")[:120] or "attachment"
                stored_name = f"{time.time_ns()}_{safe_name}"
                target = _attachment_root(chat_id) / stored_name
                target.write_bytes(raw)

                attachment = {
                    "name": original_name[:160],
                    "path": str(target.relative_to(DATA_DIR)).replace("\\", "/"),
                    "mime": str(body.get("mime", "application/octet-stream"))[:120],
                    "size": len(raw),
                }
                self._json(
                    {"ok": True, "attachment": attachment},
                    HTTPStatus.CREATED,
                )
            except Exception as e:
                self._error(e, HTTPStatus.INTERNAL_SERVER_ERROR)
            finally:
                if backend:
                    backend.close()
            return

        match = re.fullmatch(r"/api/chats/(\d+)/messages", path)
        if match:
            backend = None
            try:
                update_lock = getattr(self.server, "update_lock", None)
                if (
                    getattr(self.server, "update_restarting", False)
                    or (update_lock is not None and update_lock.locked())
                ):
                    self._error(
                        "XemAi is updating. Please retry this message in a moment.",
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                    return

                chat_id = int(match.group(1))
                text = str(body.get("text", "")).strip()
                attachments = _validated_attachment_refs(
                    chat_id, body.get("attachments", [])
                )
                if not text and not attachments:
                    self._error("Message text or an attachment is required.")
                    return
                if len(text) > 50_000:
                    self._error("Message is too long.")
                    return
                if _get_chat_activity(self.server, chat_id).get("active"):
                    self._error(
                        "XemAi is already working on a reply in this chat.",
                        HTTPStatus.CONFLICT,
                    )
                    return

                backend = self._backend()
                chat = backend.get_chat(chat_id)
                if chat is None or chat["user_id"] != backend.user["id"]:
                    self._error("Chat not found.", HTTPStatus.NOT_FOUND)
                    return

                _start_chat_generation(
                    self.server,
                    chat_id,
                    text,
                    attachments=attachments,
                    record_user=True,
                )
                self._json(
                    {
                        "ok": True,
                        "accepted": True,
                        "chat_id": chat_id,
                        "status": "XemAi is thinking",
                    },
                    HTTPStatus.ACCEPTED,
                )
            except RuntimeError as e:
                self._error(e, HTTPStatus.CONFLICT)
            except Exception as e:
                self._error(e, HTTPStatus.INTERNAL_SERVER_ERROR)
            finally:
                if backend:
                    backend.close()
            return

        match = re.fullmatch(r"/api/chats/(\d+)/retry", path)
        if match:
            backend = None
            try:
                update_lock = getattr(self.server, "update_lock", None)
                if (
                    getattr(self.server, "update_restarting", False)
                    or (update_lock is not None and update_lock.locked())
                ):
                    self._error(
                        "XemAi is updating. Please retry in a moment.",
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                    return

                chat_id = int(match.group(1))
                if _get_chat_activity(self.server, chat_id).get("active"):
                    self._error(
                        "XemAi is already working on a reply in this chat.",
                        HTTPStatus.CONFLICT,
                    )
                    return

                backend = self._backend()
                chat = backend.get_chat(chat_id)
                if chat is None or chat["user_id"] != backend.user["id"]:
                    self._error("Chat not found.", HTTPStatus.NOT_FOUND)
                    return

                recent = list(backend.messages(chat_id))
                last_user = next(
                    (
                        row for row in reversed(recent)
                        if row["role"] == "user"
                    ),
                    None,
                )
                if last_user is None:
                    self._error("No user message is available to retry.")
                    return

                _start_chat_generation(
                    self.server,
                    chat_id,
                    str(last_user["content"]),
                    record_user=False,
                )
                self._json(
                    {
                        "ok": True,
                        "accepted": True,
                        "chat_id": chat_id,
                        "status": "XemAi is thinking",
                    },
                    HTTPStatus.ACCEPTED,
                )
            except RuntimeError as e:
                self._error(e, HTTPStatus.CONFLICT)
            except Exception as e:
                self._error(e, HTTPStatus.INTERNAL_SERVER_ERROR)
            finally:
                if backend:
                    backend.close()
            return

        match = re.fullmatch(r"/api/chats/(\d+)/feedback", path)
        if match:
            backend = None
            try:
                chat_id = int(match.group(1))
                score = int(body.get("score"))
                note = str(body.get("note", "")).strip()
                backend = self._backend()
                backend.rate_chat(chat_id, score, note)
                self._json({"ok": True})
            except (TypeError, ValueError) as e:
                self._error(e)
            except Exception as e:
                self._error(e, HTTPStatus.INTERNAL_SERVER_ERROR)
            finally:
                if backend:
                    backend.close()
            return

        if path == "/api/update/install":
            backend = None
            update_lock = getattr(self.server, "update_lock", None)
            acquired = False
            try:
                if _active_chat_requests(self.server) > 0:
                    self._error(
                        "XemAi is finishing a reply. The updater will retry shortly.",
                        HTTPStatus.CONFLICT,
                    )
                    return

                if update_lock is not None:
                    acquired = update_lock.acquire(blocking=False)
                    if not acquired:
                        self._error(
                            "An XemAi update is already in progress.",
                            HTTPStatus.CONFLICT,
                        )
                        return

                backend = self._backend()
                if not backend.config.get("mobile_updates_enabled", True):
                    self._error(
                        "Mobile updates are disabled.",
                        HTTPStatus.FORBIDDEN,
                    )
                    return

                manifest = backend.check_update()
                if not manifest:
                    self._json({
                        "ok": True,
                        "installed": VERSION,
                        "restart": False,
                        "message": "XemAi is already up to date.",
                    })
                    return

                if _active_chat_requests(self.server) > 0:
                    self._error(
                        "XemAi became busy. The updater will retry shortly.",
                        HTTPStatus.CONFLICT,
                    )
                    return

                installed = backend.install_update(manifest)
                self._json({
                    "ok": True,
                    "installed": installed,
                    "restart": True,
                    "message": (
                        f"Updated to v{installed}. "
                        "The shared XemAi server is restarting."
                    ),
                })
                self.wfile.flush()
                self.server.update_restarting = True
                _schedule_mobile_server_restart()
            except Exception as e:
                self._error(e, HTTPStatus.INTERNAL_SERVER_ERROR)
            finally:
                if backend:
                    backend.close()
                if acquired and update_lock is not None:
                    update_lock.release()
            return

        self._error("Unknown endpoint.", HTTPStatus.NOT_FOUND)


class XemAiMobileServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def run_mobile_server() -> int:
    config = load_config()
    host = str(config.get("mobile_server_host", "127.0.0.1")).strip() or "127.0.0.1"
    port = int(config.get("mobile_server_port", 8765))
    logger = setup_logging(LOG_DIR)

    if host not in {"127.0.0.1", "localhost", "::1"}:
        logger.warning(
            "Mobile server configured on non-loopback host=%s. "
            "This is less secure than localhost + Tailscale Serve.",
            host,
        )

    try:
        server = XemAiMobileServer((host, port), XemAiMobileHandler)
    except OSError as e:
        # If another XemAi mobile server already owns the port, simply exit.
        logger.info(
            "Mobile server not started | host=%s port=%s reason=%r",
            host, port, e
        )
        return 0

    server.xemai_logger = logger
    server.update_lock = threading.Lock()
    server.activity_lock = threading.Lock()
    server.active_chat_requests = 0
    server.chat_activity = {}
    server.update_restarting = False
    server.stop_event = threading.Event()
    state_path = DATA_DIR / "mobile_server.json"
    state = {
        "pid": os.getpid(),
        "version": VERSION,
        "host": host,
        "port": port,
    }
    try:
        state_path.write_text(
            json.dumps(state, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass

    logger.info(
        "Mobile server start | version=%s host=%s port=%s pid=%s",
        VERSION, host, port, os.getpid()
    )
    threading.Thread(
        target=_auto_update_loop,
        args=(server,),
        daemon=True,
        name="XemAiAutoUpdater",
    ).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop_event.set()
        server.server_close()
        try:
            if state_path.exists():
                current = json.loads(state_path.read_text(encoding="utf-8"))
                if int(current.get("pid", -1)) == os.getpid():
                    state_path.unlink()
        except Exception:
            pass
        logger.info("Mobile server stop")
    return 0
