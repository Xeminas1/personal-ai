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
    "auto_detect_ollama_model": True,
    "assistant_name": "XemAi",
    "history_messages": 30,
    "memory_limit": 25,
    "auto_memory": True,
    "log_message_content": False,
    "update_manifest_url": "https://raw.githubusercontent.com/Xeminas1/personal-ai/main/update_manifest.json",
    "check_updates_on_startup": True,
    "max_tool_rounds": 6,
    "evidence_research_mode": "auto",
    "research_max_sources": 3,
    "hybrid_enabled": False,
    "hybrid_worker_url": "",
    "hybrid_worker_model": "qwen3:8b",
    "hybrid_worker_port": 8766,
    "hybrid_routing_mode": "prefer_worker",
    "teacher_enabled": True,
    "teacher_review_mode": "auto",
    "teacher_auto_install": True,
    "teacher_min_answer_chars": 280,
    "mobile_server_host": "127.0.0.1",
    "mobile_server_port": 8765,
    "mobile_server_autostart": True,
    "mobile_updates_enabled": True,
    "auto_install_updates": True,
    "auto_update_interval_seconds": 15
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
