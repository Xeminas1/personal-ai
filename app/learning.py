from __future__ import annotations

import json
from typing import Any

from .prompts import MEMORY_EXTRACTOR_SYSTEM, build_memory_extraction_prompt


def extract_and_store_memories(
    *,
    llm,
    db,
    user_id: int,
    chat_id: int,
    user_message: str,
    logger,
) -> list[int]:
    """
    "Always learning" v0.1:
    - learns durable user/project/preferences into structured memory
    - does NOT alter model weights or rewrite its own source code
    - memories remain inspectable/deletable
    """
    messages = [
        {"role": "system", "content": MEMORY_EXTRACTOR_SYSTEM},
        {"role": "user", "content": build_memory_extraction_prompt(user_message)},
    ]

    try:
        raw = llm.chat(messages, json_mode=True)
        parsed: dict[str, Any] = json.loads(raw)
    except Exception as e:
        logger.warning("Memory extraction failed: %r", e)
        return []

    stored_ids: list[int] = []
    items = parsed.get("memories", [])
    if not isinstance(items, list):
        return []

    for item in items[:4]:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind", "user_belief")).strip()
        content = str(item.get("content", "")).strip()
        explicit = bool(item.get("explicit", False))

        if kind not in {"preference", "project", "profile", "user_belief"}:
            kind = "user_belief"

        if not content:
            continue

        confidence_map = {
            "preference": 1.00 if explicit else 0.75,
            "project": 0.98 if explicit else 0.75,
            "profile": 0.95 if explicit else 0.70,
            "user_belief": 0.85 if explicit else 0.60,
        }
        confidence = confidence_map[kind]

        memory_id = db.add_memory(
            user_id=user_id,
            source_chat_id=chat_id,
            kind=kind,
            content=content,
            confidence=confidence,
        )
        if memory_id is not None:
            stored_ids.append(memory_id)

    if stored_ids:
        logger.info(
            "Memory update | chat_id=%s count=%d ids=%s",
            chat_id, len(stored_ids), stored_ids
        )
    return stored_ids
