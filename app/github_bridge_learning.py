"""Local, opt-in dataset candidates from the PRIVATE GitHub discussion.

This is NOT model fine-tuning or trusted memory. Each candidate is unverified
until a separate benchmark or human review validates its claims. Raw source,
local files, credentials and unrelated user chats are not collected.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from .github_bridge import _LOCK, _SECRET, load_state, save_state

MAX_RECORDS = 2000
MAX_INPUT = 1800
MAX_OUTPUT = 1450
_FILE = "github_bridge_training_candidates.jsonl"


def archive_path(data_dir: Path) -> Path:
    return Path(data_dir) / _FILE


def _count(data_dir: Path) -> int:
    path = archive_path(data_dir)
    if not path.exists():
        return 0
    try:
        with path.open(encoding="utf-8") as stream:
            return sum(1 for _ in stream)
    except OSError:
        return 0


def command(data_dir: Path, cmd: str) -> str:
    with _LOCK:
        state = load_state(data_dir)
        if cmd == "bridge learning on":
            state["learning_enabled"] = True
            save_state(data_dir, state)
            return (
                "Learning-candidate collection ENABLED for future GitHub bridge "
                "exchanges only. XemAi stores unverified question/answer examples "
                "locally, not on GitHub. They are NOT added to trusted memory, "
                "used to update model weights, or automatically accepted as true. "
                "Use 'bridge learning off' to stop future collection."
            )
        if cmd == "bridge learning off":
            state["learning_enabled"] = False
            save_state(data_dir, state)
            return (
                "Learning-candidate collection DISABLED. Existing local "
                "candidates are retained for manual review; no model was trained."
            )
        count = _count(data_dir)
        # Review metadata is a separate, local, append-only journal.
        try:
            from .github_bridge_review import review_counts
            review = review_counts(data_dir)
            review_label = (
                f" Owner-reviewed lessons: {review['approved']}; "
                f"drafts awaiting approval: {review['proposed']}. "
            )
        except (OSError, ValueError, UnicodeError):
            review_label = " Review journal unavailable. "
        return (
            f"Learning-candidate collection: "
            f"{'ON' if state.get('learning_enabled') is True else 'OFF'}. "
            f"Locally archived candidates: {count}/{MAX_RECORDS}. "
            + review_label
            + "Examples are UNVERIFIED until personally reviewed. An approved "
            "lesson is owner-reviewed, not independently fact-checked; nothing "
            "alters model weights or personal memory automatically. "
            "Use 'bridge learning review' to inspect candidates."
        )


def append_candidate(
    data_dir: Path, *, repo: str, issue: int, comment_id: int,
    question: str, answer: str, provenance: dict,
    timestamp: datetime,
) -> bool:
    """Write one pending, reviewable example. Never modify model weights."""
    with _LOCK:
        if load_state(data_dir).get("learning_enabled") is not True:
            return False
        if _count(data_dir) >= MAX_RECORDS:
            return False
        # Do not persist credentials accidentally quoted in a GitHub reply.
        if _SECRET.search(question) or _SECRET.search(answer):
            return False
        safe = {
            "created_at": timestamp.isoformat(),
            "source": "private_github_issue",
            "issue": int(issue),
            "comment_id": int(comment_id),
            "input_excerpt": str(question)[:MAX_INPUT],
            "input_was_truncated": len(str(question)) > MAX_INPUT,
            "model_response": str(answer)[:MAX_OUTPUT],
            "model": str(provenance.get("model") or "unknown")[:84],
            "compute": str(provenance.get("compute") or "unknown")[:20],
            "discussion_mode": str(provenance.get("mode") or "unknown")[:40],
            "review_status": "unverified",
            "training_applied": False,
        }
        # Keep the repository identifier out of the dataset; issue number
        # and comment ID suffice for manual reconciliation.
        path = archive_path(data_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        try:
            fd = os.open(path, flags, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as stream:
                stream.write(json.dumps(safe, ensure_ascii=False) + "\n")
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
        except OSError:
            raise
        return True
