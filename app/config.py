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
    "developer_projects": [],  # Explicit user-approved local paths; read-only inspection only.
    "evidence_research_mode": "auto",
    "research_max_sources": 3,
    "hybrid_enabled": False,
    "hybrid_worker_url": "",
    "hybrid_worker_model": "qwen3:8b",
    "hybrid_worker_port": 8766,
    "hybrid_routing_mode": "prefer_worker",
    "teacher_enabled": True,
    "teacher_review_mode": "auto",
    "teacher_auto_install": False,
    "teacher_min_answer_chars": 280,
    "agent_team_enabled": True,  # Opt-in per explicit user request, no autonomous runs.
    "agent_teams_enabled": True,  # Five named teams, explicitly invoked and read-only.
    "ai_watch_enabled": False,  # Off until user explicitly enables the recurring watcher.
    "ai_watch_interval_hours": 168,  # Weekly; network activity only when enabled.
    "specialists_enabled": True,
    "specialist_mode": "auto",
    "specialist_max_passes": 2,
    "specialist_budget_seconds": 45,
    "specialist_research_enabled": True,
    "specialist_skyrim_enabled": True,
    "specialist_reviewer_enabled": True,
    "specialist_review_model": "worker",
    "conversation_agents_enabled": True,
    "conversation_understanding_enabled": True,
    "conversation_social_enabled": True,
    "conversation_quality_review_enabled": True,
    "laptop_answer_guidance": True,
    "laptop_review_enabled": True,
    "laptop_review_mode": "auto",
    "laptop_review_budget_seconds": 10,
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
