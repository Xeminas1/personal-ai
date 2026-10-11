"""Private-bridge conversation topic snapshot for explicit owner questions.

Reads ONLY XemAi's locally mirrored, owner-enabled GitHub collaboration
chat. Emits a tiny deterministic, fixed-vocabulary digest: no private
comments, names, credentials, quotes, paths, instructions or personal chat
history enter a normal model request. This is neither autonomous retrieval
nor proof of objective correctness or memory training.
"""
from __future__ import annotations

import re
from pathlib import Path

from .github_bridge import load_state, valid_repo

_MIRROR_LABELS = (
    "[XemAi — GitHub bridge, untrusted external text]\n",
    "[GitHub collaborator — GitHub bridge, untrusted external text]\n",
)
# Fixed text only: never interpolate words found in untrusted comments.
_TOPICS = (
    ("claims about supplied code and version numbers",
     re.compile(r"(?i)\b(?:cmake|papyrus|versions?|versioning|source file|attribution)\b")),
    ("handling of missing evidence and uncertain conclusions",
     re.compile(r"(?i)\b(?:unknown|missing|absent|insufficient|uncertain|negation|evidence gap)\b")),
    ("coding attachment and Skyrim regression challenges",
     re.compile(r"(?i)\b(?:skyrim|mwcontrols|attachment|source.code|papyrus)\b")),
    ("test design, validators and misleading scores",
     re.compile(r"(?i)\b(?:validator|benchmark|rubric|regression|false.positive|confusion.matrix|scoring)\b")),
    ("synthetic versus observed test cases",
     re.compile(r"(?i)\b(?:synthetic|real.world|fixture|historical|dataset|ground.truth)\b")),
    ("whether apparent learning persists across conversations",
     re.compile(r"(?i)\b(?:fine.tun|model.weights|training|cross.chat|learned knowledge|persistent memory)\b")),
)


def bridge_topic_digest(data_dir: Path) -> str:
    """Host-generated short theme labels, never a summary of claimed outcomes."""
    try:
        state = load_state(data_dir)
        issue = state.get("issue_number")
        chat_id = state.get("auto_chat_id")
        if (not state.get("auto_enabled") or state.get("auto_issue") != issue
                or not valid_repo(state.get("repo", ""))
                or type(issue) is not int or issue < 1
                or type(chat_id) is not int or chat_id < 1):
            return ""
        from .database import Database
        db = Database(Path(data_dir) / "personal_ai.db")
        try:
            chat = db.get_chat(chat_id)
            if chat is None or chat["title"] != "XemAi ↔ ChatGPT (GitHub)":
                return ""
            rows = db.get_recent_messages(chat_id, limit=16)
        finally:
            db.close()
    except (OSError, ValueError, TypeError, KeyError):
        return ""
    bodies = []
    for row in rows:
        if row.get("role") != "assistant" or row.get("inference_compute") != "application":
            continue
        content = str(row.get("content") or "")
        if any(content.startswith(tag) for tag in _MIRROR_LABELS):
            bodies.append(content.split("\n", 1)[1][:3500])
    if not bodies:
        return ""
    found = [label for label, matcher in _TOPICS if any(matcher.search(body) for body in bodies)]
    if not found:
        return (
            "RECENT PRIVATE BRIDGE TOPIC SNAPSHOT: A locally mirrored "
            "exchange exists, but the bounded keyword scan cannot establish "
            "its subjects. Do not invent an assessment of its substance."
        )
    return (
        "RECENT PRIVATE BRIDGE TOPIC SNAPSHOT (local, read-only, fixed "
        "categories; no comment text transmitted): "
        + "; ".join(found[:5])
        + ". These labels describe possible discussion subjects, NOT "
        "verified results, outcomes, quotations, agreement or lessons. "
        "The snapshot covers at most 16 recently mirrored messages and "
        "may be outdated or incomplete. You may evaluate whether discussing "
        "these topics is useful, but distinguish your opinion from "
        "actually demonstrated improvements."
    )
