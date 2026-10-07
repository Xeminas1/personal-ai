from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
CONFIG_PATH = BASE_DIR / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "ollama_url": "http://localhost:11434",
    "model": "qwen3:8b",
    "assistant_name": "XemAi",
    "history_messages": 30,
    "memory_limit": 25,
    "auto_memory": True,
    "log_message_content": False,
    "update_manifest_url": "https://raw.githubusercontent.com/Xeminas1/personal-ai/main/update_manifest.json",
    "check_updates_on_startup": True,
    "max_tool_rounds": 6,
    "mobile_server_host": "127.0.0.1",
    "mobile_server_port": 8765,
    "mobile_server_autostart": True,
    "mobile_updates_enabled": True
}


def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict[str, Any]:
    ensure_directories()
    if not CONFIG_PATH.exists():
        save_config(DEFAULT_CONFIG.copy())
        return DEFAULT_CONFIG.copy()

    with CONFIG_PATH.open("r", encoding="utf-8") as f:
        user_config = json.load(f)

    config = DEFAULT_CONFIG.copy()
    config.update(user_config)
    return config


def save_config(config: dict[str, Any]) -> None:
    ensure_directories()
    with CONFIG_PATH.open("w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)
