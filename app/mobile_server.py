from __future__ import annotations

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
MAX_BODY = 256_000


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
        "time.sleep(1.5);"
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
        time.sleep(0.5)
        # The response has already been sent. Exit immediately so the helper can
        # bind the same localhost port using the newly installed code.
        os._exit(0)

    threading.Thread(target=stop_current, daemon=True).start()


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
                self._json({
                    "ok": True,
                    "version": VERSION,
                    "assistant_name": backend.config.get("assistant_name", "XemAi"),
                    "user": {
                        "id": backend.user["id"],
                        "name": backend.user["name"],
                    },
                    "capabilities": backend.capabilities(),
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

        match = re.fullmatch(r"/api/chats/(\d+)/messages", path)
        if match:
            backend = None
            try:
                chat_id = int(match.group(1))
                text = str(body.get("text", "")).strip()
                if not text:
                    self._error("Message text is required.")
                    return
                if len(text) > 50_000:
                    self._error("Message is too long.")
                    return

                backend = self._backend()
                chat = backend.get_chat(chat_id)
                if chat is None or chat["user_id"] != backend.user["id"]:
                    self._error("Chat not found.", HTTPStatus.NOT_FOUND)
                    return

                answer = backend.send(chat_id, text)
                updated_chat = backend.get_chat(chat_id)
                self._json({
                    "ok": True,
                    "answer": answer,
                    "chat": _row_dict(updated_chat),
                })
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
            try:
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

                installed = backend.install_update(manifest)
                self._json({
                    "ok": True,
                    "installed": installed,
                    "restart": True,
                    "message": (
                        f"Updated to v{installed}. "
                        "The mobile server is restarting."
                    ),
                })
                self.wfile.flush()
                _schedule_mobile_server_restart()
            except Exception as e:
                self._error(e, HTTPStatus.INTERNAL_SERVER_ERROR)
            finally:
                if backend:
                    backend.close()
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
        logger.info("Mobile server stop")
    return 0
