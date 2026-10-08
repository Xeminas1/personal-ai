from __future__ import annotations

import json
import os
import secrets
from pathlib import Path


def _secrets_path(data_dir: Path) -> Path:
    return data_dir / "secrets.json"


def _load_secret_data(data_dir: Path) -> dict:
    path = _secrets_path(data_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _save_secret_data(data_dir: Path, payload: dict) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = _secrets_path(data_dir)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def load_ollama_api_key(data_dir: Path) -> str:
    env_key = os.environ.get("OLLAMA_API_KEY", "").strip()
    if env_key:
        return env_key
    return str(_load_secret_data(data_dir).get("ollama_api_key", "")).strip()


def save_ollama_api_key(data_dir: Path, key: str) -> None:
    payload = _load_secret_data(data_dir)
    payload["ollama_api_key"] = key.strip()
    _save_secret_data(data_dir, payload)


def clear_ollama_api_key(data_dir: Path) -> None:
    payload = _load_secret_data(data_dir)
    payload.pop("ollama_api_key", None)
    _save_secret_data(data_dir, payload)


def load_hybrid_worker_client_token(data_dir: Path) -> str:
    env_key = os.environ.get("XEMAI_WORKER_TOKEN", "").strip()
    if env_key:
        return env_key
    return str(
        _load_secret_data(data_dir).get("hybrid_worker_client_token", "")
    ).strip()


def save_hybrid_worker_client_token(data_dir: Path, token: str) -> None:
    payload = _load_secret_data(data_dir)
    payload["hybrid_worker_client_token"] = token.strip()
    _save_secret_data(data_dir, payload)


def load_hybrid_worker_server_token(data_dir: Path) -> str:
    env_key = os.environ.get("XEMAI_WORKER_SERVER_TOKEN", "").strip()
    if env_key:
        return env_key
    return str(
        _load_secret_data(data_dir).get("hybrid_worker_server_token", "")
    ).strip()


def ensure_hybrid_worker_server_token(data_dir: Path) -> str:
    token = load_hybrid_worker_server_token(data_dir)
    if token:
        return token
    token = secrets.token_urlsafe(32)
    payload = _load_secret_data(data_dir)
    payload["hybrid_worker_server_token"] = token
    _save_secret_data(data_dir, payload)
    return token
