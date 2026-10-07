from __future__ import annotations

import json
import os
from pathlib import Path


def _secrets_path(data_dir: Path) -> Path:
    return data_dir / "secrets.json"


def load_ollama_api_key(data_dir: Path) -> str:
    env_key = os.environ.get("OLLAMA_API_KEY", "").strip()
    if env_key:
        return env_key

    path = _secrets_path(data_dir)
    if not path.exists():
        return ""

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return ""

    return str(data.get("ollama_api_key", "")).strip()


def save_ollama_api_key(data_dir: Path, key: str) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    path = _secrets_path(data_dir)
    payload = {"ollama_api_key": key.strip()}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def clear_ollama_api_key(data_dir: Path) -> None:
    path = _secrets_path(data_dir)
    if path.exists():
        path.unlink()
