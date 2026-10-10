"""Explicit, temporary, read-only access to a small safe support surface.

This module never serves arbitrary files. Routes must call ``authorized``
before using ``get_report``, ``list_files`` or ``read_file``.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import secrets
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit, urlunsplit

from .version import VERSION

MAX_FILE_BYTES = 1_048_576
ACCESS_SECONDS = 24 * 60 * 60
_LOCK = threading.RLock()
_ROOT_SOURCES = {
    "LegacyDesktop.pyw", "XemAi.pyw", "XemAiServer.pyw", "XemAiWorker.pyw",
    "XemAiSupport.pyw", "main.py", "ui.py", "hybrid_setup.py", "self_test.py",
    "test_support_access.py", "README.md", "live_support.bat",
    "test.bat", "run.bat", "console.bat", "setup.bat", "install.bat", "update.bat",
    "mobile_server.bat", "restart_mobile_server.bat", "mobile_tailscale_setup.bat",
    "hybrid_host_setup.bat", "hybrid_worker_setup.bat",
}
_MOBILE_SOURCES = {
    "mobile/index.html", "mobile/app.js", "mobile/styles.css",
    "mobile/sw.js", "mobile/manifest.webmanifest",
    "mobile/support.html", "mobile/support.js",
}
_CONFIG_BOOLS = {
    "hybrid_enabled", "auto_detect_ollama_model", "mobile_server_autostart",
    "mobile_updates_enabled", "auto_install_updates", "check_updates_on_startup",
}
_CONFIG_NUMBERS = {
    "hybrid_worker_port", "mobile_server_port", "auto_update_interval_seconds",
}
_CONFIG_MODELS = {"model", "hybrid_worker_model"}
_CONFIG_URLS = {"ollama_url", "hybrid_worker_url", "update_manifest_url"}
_EVENTS = {
    "Application start", "Mobile server start", "Mobile server stop",
    "Hybrid worker start", "Hybrid worker stop", "Hybrid auto-setup check",
    "Hybrid auto-setup check failed; will retry", "Hybrid auto-pair waiting",
    "Hybrid auto-pair skipped", "Hybrid auto-pair succeeded",
    "Hybrid auto-pair candidate failed", "Hybrid worker discovery failed",
    "Hybrid worker setup waiting", "Hybrid worker auto-setup launched with Windows approval prompt",
    "Hybrid worker auto-setup could not launch", "Hybrid route selected",
    "Hybrid worker unavailable; using local fallback", "Hybrid local model discovery failed",
    "Hybrid worker generation failed; falling back locally", "Ollama runtime model discovery",
    "Mobile server not started", "Hybrid worker not started",
    "Chat timing", "LLM timing", "Worker timing", "Hybrid attempt",
}
_TIMING_EVENTS = {"Chat timing", "LLM timing", "Worker timing", "Hybrid attempt"}
_NETWORK_ERRORS = {
    "none", "http", "tls_verification", "tls", "dns", "timeout",
    "refused", "reset", "aborted", "unreachable", "connection", "model_error",
}
_TIMING_NUMBERS = {
    "elapsed_ms", "load_ms", "prompt_ms", "generation_ms", "total_ms",
    "discovery_ms", "queue_ms", "prompt_tokens", "generated_tokens",
    "thinking_chars", "tool_calls", "chat_id",
}
_CHAT_PHASES = {
    "route", "prepared", "research", "answer", "retry", "visible_reply",
    "source_review", "specialist_prepare", "specialist_review", "memory", "complete", "failed",
}
_REASONS = {
    "Tailscale executable unavailable", "No central-host Serve route detected",
    "Tailscale identity unavailable", "No online Tailscale peers",
    "No reachable Qwen workers", "Local Ollama has no reachable Qwen model",
}
_ERROR_TYPES = {
    "HTTPError", "URLError", "TimeoutError", "ConnectionError", "OSError",
    "ValueError", "TypeError", "RuntimeError", "OllamaError", "SSLError",
    "JSONDecodeError", "FileNotFoundError", "PermissionError",
}
_LOG_HEADER = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) \| "
    r"(DEBUG|INFO|WARNING|ERROR|CRITICAL) \| personal_ai \| (.*)$"
)


def _iso(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="seconds")


def _root(root) -> Path:
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Installation folder is unavailable.")
    return root


def _safe_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not 0 < len(relative) <= 512 or "\\" in relative or ":" in relative:
        raise ValueError("File is outside the support allowlist.")
    parts = PurePosixPath(relative).parts
    if relative.startswith("/") or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("File is outside the support allowlist.")
    if str(PurePosixPath(relative)) != relative:
        raise ValueError("File is outside the support allowlist.")
    target = root
    for part in parts:
        target = target / part
        if target.is_symlink():
            raise ValueError("Support access does not follow symbolic links.")
    if not target.resolve().is_relative_to(root):
        raise ValueError("File is outside the installation folder.")
    return target


def _read_bytes(path: Path, limit: int = MAX_FILE_BYTES) -> bytes:
    if not path.is_file() or path.stat().st_size > limit:
        raise ValueError("Support file is unavailable or too large.")
    with path.open("rb") as handle:
        value = handle.read(limit + 1)
    if len(value) > limit:
        raise ValueError("Support file is too large.")
    return value


def _log_tail(path: Path) -> bytes:
    """Read at most the last MiB, dropping an incomplete first record."""
    if not path.is_file():
        raise ValueError("Support log is unavailable.")
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        offset = max(0, handle.tell() - MAX_FILE_BYTES)
        handle.seek(offset)
        raw = handle.read(MAX_FILE_BYTES)
    if offset:
        _, separator, raw = raw.partition(b"\n")
        if not separator:
            raw = b""
    return raw


def _json_file(root: Path, relative: str, limit: int = MAX_FILE_BYTES) -> dict:
    try:
        value = json.loads(_read_bytes(_safe_path(root, relative), limit))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def _state(root: Path) -> dict:
    value = _json_file(root, "data/support_access.json", 4096)
    digest, expiry = value.get("token_sha256"), value.get("expires_at")
    if (not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
            or not isinstance(expiry, (float, int)) or isinstance(expiry, bool)
            or not time.time() < expiry <= time.time() + ACCESS_SECONDS + 60):
        return {}
    return value


def status(root) -> dict:
    with _LOCK:
        state = _state(_root(root))
        return {"enabled": bool(state), "expires_at": _iso(state["expires_at"]) if state else None}


def enable(root) -> dict:
    """Create a new 24-hour token, invalidating any previous token."""
    with _LOCK:
        root = _root(root)
        path = _safe_path(root, "data/support_access.json")
        path.parent.mkdir(exist_ok=True)
        token = secrets.token_urlsafe(32)
        expiry = time.time() + ACCESS_SECONDS
        payload = {"token_sha256": hashlib.sha256(token.encode("ascii")).hexdigest(), "expires_at": expiry}
        temporary = None
        try:
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
                temporary = Path(handle.name)
                os.chmod(temporary, 0o600)
                json.dump(payload, handle)
            os.replace(temporary, path)
            os.chmod(path, 0o600)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return {"enabled": True, "expires_at": _iso(expiry), "token": token}


def disable(root) -> dict:
    with _LOCK:
        _safe_path(_root(root), "data/support_access.json").unlink(missing_ok=True)
        return {"enabled": False, "expires_at": None}


def authorized(root, token: str) -> bool:
    if not isinstance(token, str) or not 20 <= len(token) <= 128 or not token.isascii():
        return False
    with _LOCK:
        state = _state(_root(root))
        supplied = hashlib.sha256(token.encode("ascii")).hexdigest()
        return bool(state) and secrets.compare_digest(state["token_sha256"], supplied)


def _safe_label(value, *, length: int = 128) -> str | None:
    if isinstance(value, str) and len(value) <= length and re.fullmatch(r"[A-Za-z0-9_.:/-]+", value):
        return value
    return None


def _safe_url(value) -> str:
    """Keep scheme/host/port only; credentials, paths and queries are excluded."""
    if not isinstance(value, str):
        return ""
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        if parsed.scheme not in {"http", "https"} or not re.fullmatch(r"[A-Za-z0-9.:-]+", host):
            return ""
        port = parsed.port
        host = f"[{host}]" if ":" in host else host
        return urlunsplit((parsed.scheme, host + (f":{port}" if port else ""), "", "", ""))
    except ValueError:
        return ""


def safe_config(root) -> dict:
    config = _json_file(_root(root), "config.json")
    safe = {}
    for key in _CONFIG_BOOLS:
        if isinstance(config.get(key), bool):
            safe[key] = config[key]
    for key in _CONFIG_NUMBERS:
        value = config.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value <= 86400:
            safe[key] = value
    for key in _CONFIG_MODELS:
        value = _safe_label(config.get(key))
        if value is not None:
            safe[key] = value
    for key in _CONFIG_URLS:
        if key in config:
            safe[key] = _safe_url(config[key])
    if isinstance(config.get("hybrid_routing_mode"), str) and config["hybrid_routing_mode"] in {"prefer_worker", "local_only", "worker_only"}:
        safe["hybrid_routing_mode"] = config["hybrid_routing_mode"]
    host = _safe_label(config.get("mobile_server_host"))
    if host is not None:
        safe["mobile_server_host"] = host
    return safe


def structured_log(text: str) -> list[dict]:
    """Extract typed events only; never emit raw log text or error bodies."""
    entries = []
    for line in text.splitlines():
        match = _LOG_HEADER.fullmatch(line)
        if not match:
            continue
        timestamp, level, message = match.groups()
        segments = message.split(" | ")
        event = segments[0]
        if event not in _EVENTS:
            continue
        entry = {"timestamp": timestamp, "level": level, "event": event}
        reached_error = False
        for segment in segments[1:]:
            # Existing event templates use space-separated key=value fields.
            # Error bodies are untrusted; do not parse apparent fields inside them.
            if segment.startswith("error="):
                fields = [segment]
            else:
                prefix, marker, error = segment.partition(" error=")
                fields = re.split(r" (?=[a-z_]+=)", prefix)
                if marker:
                    fields.append("error=" + error)
            for field in fields:
                key, sep, value = field.partition("=")
                if not sep:
                    continue
                if key == "reason" and value in _REASONS:
                    entry[key] = value
                elif key == "role" and value in {"host", "worker", "worker-or-waiting"}:
                    entry[key] = value
                elif key in {"version", "model", "fallback", "source", "compute"}:
                    label = _safe_label(value)
                    if label is not None:
                        entry[key] = label
                elif key in {"peers", "port", "pid"} and re.fullmatch(r"\d{1,8}", value):
                    entry[key] = int(value)
                elif key == "error":
                    reached_error = True
                    error_type = re.match(r"<?([A-Za-z]+)(?:\(| |$)", value)
                    if error_type and error_type[1] in _ERROR_TYPES:
                        entry["error_type"] = error_type[1]
                    code = re.search(r"(?:HTTP(?:Error| Error)?\s+|HTTP\s+)([1-5]\d{2})\b", value)
                    if code:
                        entry["http_status"] = int(code[1])
                elif event in _TIMING_EVENTS:
                    if key in _TIMING_NUMBERS and re.fullmatch(r"-?\d{1,12}", value) and int(value) >= -1:
                        entry[key] = int(value)
                    elif key == "turn_id" and (value == "none" or re.fullmatch(r"[a-f0-9]{16}", value)):
                        entry[key] = value
                    elif event == "Hybrid attempt" and key == "stage" and value in {"worker_health", "worker_chat", "specialist", "teacher_review"}:
                        entry[key] = value
                    elif event == "Hybrid attempt" and key == "error_category" and value in _NETWORK_ERRORS:
                        entry[key] = value
                    elif event == "Hybrid attempt" and key == "http_status" and re.fullmatch(r"-?\d{1,3}", value) and (int(value) == -1 or 100 <= int(value) <= 599):
                        entry[key] = int(value)
                    elif event == "Hybrid attempt" and key in {"errno", "winerror"} and re.fullmatch(r"-?\d{1,10}", value) and -(2 ** 31) <= int(value) < 2 ** 31:
                        entry[key] = int(value)
                    elif key == "phase" and value in _CHAT_PHASES:
                        entry[key] = value
                    elif key == "success" and value in {"True", "False"}:
                        entry[key] = value == "True"
                    elif key == "provider" and value in {"ollama", "ollama-local", "xemai-worker", "worker-local-ollama", "xemai-hybrid"}:
                        entry[key] = value
            if reached_error:
                break
        entries.append(entry)
    return entries[-200:]


def _kind(relative: str) -> str | None:
    if relative == "config.json":
        return "safe_config"
    if re.fullmatch(r"logs/personal_ai\.log(?:\.[1-5])?", relative):
        return "structured_log"
    if relative in _ROOT_SOURCES or relative in _MOBILE_SOURCES:
        return "source"
    if re.fullmatch(r"app/[A-Za-z_][A-Za-z0-9_]*\.py", relative):
        return "source"
    return None


def read_file(root, path: str) -> dict:
    root = _root(root)
    kind = _kind(path) if isinstance(path, str) and 0 < len(path) <= 512 else None
    if kind is None:
        raise ValueError("File is outside the support allowlist.")
    target = _safe_path(root, path)
    raw = _log_tail(target) if kind == "structured_log" else _read_bytes(target)
    if kind == "safe_config":
        content = json.dumps(safe_config(root), indent=2, sort_keys=True)
    elif kind == "structured_log":
        content = json.dumps({"entries": structured_log(raw.decode("utf-8", errors="replace"))}, indent=2)
    else:
        content = raw.decode("utf-8")
    encoded = content.encode("utf-8")
    return {
        "path": path, "kind": kind, "size_bytes": len(encoded),
        "file_size_bytes": target.stat().st_size,
        "modified_at": _iso(target.stat().st_mtime),
        "sha256": hashlib.sha256(encoded).hexdigest(), "content": content,
    }


def list_files(root) -> list[dict]:
    root = _root(root)
    paths = set(_ROOT_SOURCES) | _MOBILE_SOURCES | {"config.json"}
    paths.update(f"logs/personal_ai.log{suffix}" for suffix in ["", ".1", ".2", ".3", ".4", ".5"])
    app_dir = _safe_path(root, "app")
    if app_dir.is_dir():
        paths.update(f"app/{path.name}" for path in app_dir.glob("*.py"))
    files = []
    for path in sorted(paths):
        try:
            item = read_file(root, path)
            files.append({key: item[key] for key in ("path", "kind", "size_bytes", "file_size_bytes", "modified_at")})
        except (OSError, ValueError, UnicodeError):
            continue
    return files


def get_report(root) -> dict:
    root = _root(root)
    disk_version = None
    try:
        tree = ast.parse(_read_bytes(_safe_path(root, "app/version.py")).decode("utf-8"))
        for statement in tree.body:
            if isinstance(statement, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "VERSION" for target in statement.targets):
                disk_version = _safe_label(ast.literal_eval(statement.value))
                break
    except (OSError, ValueError, SyntaxError, UnicodeError):
        pass
    secret = _json_file(root, "data/secrets.json")
    bindings = {
        "worker_client_token_present": bool(os.environ.get("XEMAI_WORKER_TOKEN") or secret.get("hybrid_worker_client_token")),
        "worker_server_token_present": bool(os.environ.get("XEMAI_WORKER_SERVER_TOKEN") or secret.get("hybrid_worker_server_token")),
        "paired_host_present": bool(secret.get("hybrid_worker_paired_host_id")),
        "host_identity_present": bool(secret.get("hybrid_host_id")),
        "pairing_pending": bool(secret.get("hybrid_worker_pending_token")),
        "worker_token_override_present": bool(os.environ.get("XEMAI_WORKER_TOKEN")),
        "worker_server_token_override_present": bool(os.environ.get("XEMAI_WORKER_SERVER_TOKEN")),
    }
    files = list_files(root)
    logs = []
    for item in files:
        if item["kind"] == "structured_log":
            try:
                logs.append({"path": item["path"], "modified_at": item["modified_at"], **json.loads(read_file(root, item["path"])["content"])})
            except (OSError, ValueError):
                continue
    return {
        "generated_at": _iso(time.time()), "installation_path": str(root),
        "loaded_version": VERSION, "disk_version": disk_version,
        "config": safe_config(root), "hybrid_bindings": bindings,
        "files": files, "logs": logs,
    }
