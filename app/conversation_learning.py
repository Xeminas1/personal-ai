"""Opt-in, owner-reviewed conversational learning and failure diagnostics.

Separate from AI model weight training. No autonomous proposals or approvals.
No raw prompt or failed draft is stored unless the owner explicitly enables
collection. Fail closed when records, ownership or content checks are unsafe.
"""
from __future__ import annotations

import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.RLock()
_STATE = "conversation_learning_state.json"
_EVENTS = "conversation_learning_examples.jsonl"
_JOURNAL = "conversation_learning_reviews.jsonl"
_MAX_EXAMPLES = 200
_MAX_BYTES = 1_500_000
_MAX_REVIEW_BYTES = 500_000
_SECRET = re.compile(
    r"(?i)(?:gh[pousr]_[a-z0-9_]{12,}|github_pat_[a-z0-9_]{12,}|"
    r"\b(?:sk-[A-Za-z0-9_-]{16,}|Bearer\s+[A-Za-z0-9._-]{12,})|"
    r"(?:token|password|api[_ -]?key|secret)\s*[:=]\s*\S{6,})"
)
_PRIVATE = re.compile(
    r"(?i)(?:[a-z]:\\|/home/[^/\s]+/|\\users\\|"
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b|"
    r"[\w.+-]+@[\w.-]+\.[a-z]{2,})"
)
_COMMAND = re.compile(r"(?i)^conversation learning(?:\s|$)")
_SCOPES = {"conversation", "coding", "research"}
_SIGNAL = {
    "dialogue_validator", "dialogue_retry_rejected",
    "dialogue_retry_error", "owner_correction",
}
_STOP = {"about", "there", "these", "could", "would", "please", "which"}


def is_command(text: str) -> bool:
    return isinstance(text, str) and bool(_COMMAND.match(text.strip()))


def _safe(text: str, limit: int = 2000) -> bool:
    return (isinstance(text, str) and 0 < len(text) <= limit
            and not _SECRET.search(text) and not _PRIVATE.search(text)
            and "\x00" not in text and not any(
                ord(c) < 32 and c not in "\t\n\r" for c in text
            ))


def _state_path(data_dir: Path) -> Path:
    return Path(data_dir) / _STATE


def _load_state(data_dir: Path) -> dict:
    path = _state_path(data_dir)
    if not path.exists():
        return {"enabled": False}
    if path.stat().st_size > 10000:
        raise ValueError("State file exceeds safe bounds.")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or type(value.get("enabled")) is not bool:
        raise ValueError("Invalid state file.")
    return value


def _atomic_state(data_dir: Path, enabled: bool) -> None:
    path = _state_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"enabled": enabled}), encoding="utf-8")
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _rows(data_dir: Path, name: str, limit: int) -> list[dict]:
    path = Path(data_dir) / name
    if not path.exists():
        return []
    if path.stat().st_size > limit:
        raise ValueError("Learning records exceed bounded storage.")
    values = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            if len(values) >= _MAX_EXAMPLES * 8:
                raise ValueError("Too many learning records.")
            item = json.loads(line)
            if not isinstance(item, dict):
                raise ValueError("Malformed learning record.")
            values.append(item)
    return values


def _snapshot(data_dir: Path) -> tuple[list[dict], dict[int, dict]]:
    examples = _rows(data_dir, _EVENTS, _MAX_BYTES)
    if len(examples) > _MAX_EXAMPLES:
        raise ValueError("Too many examples.")
    reviews = {}
    for item in _rows(data_dir, _JOURNAL, _MAX_REVIEW_BYTES):
        i = item.get("example")
        if (type(i) is int and 1 <= i <= len(examples)
                and item.get("action") in {"proposed", "approved", "revoked"}):
            reviews[i] = item
    return examples, reviews


def _append(data_dir: Path, name: str, value: dict, max_bytes: int) -> None:
    path = Path(data_dir) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n"
    if len(encoded.encode("utf-8")) > 7300:
        raise ValueError("Example is too long.")
    if path.exists() and path.stat().st_size + len(encoded.encode("utf-8")) > max_bytes:
        raise ValueError("Learning journal reached its limit.")
    fd = os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(encoded)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def record_validation(
    data_dir: Path, *, chat_id: int, turn_id: str, model: str, compute: str,
    question: str, first_draft: str, revised_draft: str,
    outcome: str, signal: str,
) -> bool:
    """Record a specific validator intervention; never raw host logs or tools."""
    if outcome not in {"model_revision", "application_fallback"} or signal not in _SIGNAL:
        return False
    with _LOCK:
        try:
            if _load_state(data_dir).get("enabled") is not True:
                return False
            examples, _ = _snapshot(data_dir)
            if len(examples) >= _MAX_EXAMPLES:
                return False
            # Do not persist attachments, local paths or credentials. Missing
            # a record is safer than silently sanitising it into a fake case.
            if not all(_safe(x, limit) for x, limit in (
                (question, 1000), (first_draft, 2400),
                (revised_draft or "(no revised text)", 2400),
            )):
                return False
            event = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "kind": "validator_intervention", "signal": signal,
                "question": question, "first_draft": first_draft,
                "revised_draft": revised_draft,
                "outcome": outcome, "chat_id": int(chat_id),
                "turn_id": str(turn_id)[:40], "model": str(model)[:100],
                "compute": str(compute)[:24], "review_status": "unverified",
                "training_applied": False,
            }
            _append(data_dir, _EVENTS, event, _MAX_BYTES)
            return True
        except (OSError, ValueError, TypeError, UnicodeError):
            return False


def _capture_correction(data_dir: Path, history: list[dict], correction: str) -> str:
    if not _safe(correction, 650):
        return "Correction not stored: unsafe or oversized text."
    if not _load_state(data_dir).get("enabled"):
        return "Collection is OFF. Use 'conversation learning on' first."
    # The command's current user row is already saved. Find the last
    # completed assistant turn and its immediately preceding user question.
    conversation = [row for row in history if row.get("role") in ("user", "assistant")]
    previous = [row for row in conversation if row["role"] != "system"]
    if previous and previous[-1]["role"] == "user":
        previous = previous[:-1]
    if len(previous) < 2 or previous[-1]["role"] != "assistant" or previous[-2]["role"] != "user":
        return "No immediately preceding completed question/answer to correct."
    q, a = str(previous[-2]["content"]), str(previous[-1]["content"])
    if not (_safe(q, 1000) and _safe(a, 2400)):
        return "Correction not stored: previous text may contain private data or attachments."
    events, _ = _snapshot(data_dir)
    if len(events) >= _MAX_EXAMPLES:
        return "Local example limit reached; no new example stored."
    event = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "kind": "owner_correction", "signal": "owner_correction",
        "question": q, "first_draft": a, "revised_draft": "",
        "correction": correction, "outcome": "owner_reported_miss",
        "review_status": "unverified", "training_applied": False,
    }
    _append(data_dir, _EVENTS, event, _MAX_BYTES)
    return (f"Correction example #{len(events)+1} captured locally as UNVERIFIED. "
            f"Nothing has been taught to the model. Use "
            f"'conversation learning show {len(events)+1}' before proposing a lesson.")


def chat_command(data_dir: Path, text: str, history: list[dict] | None = None) -> str | None:
    if not is_command(text):
        return None
    q = " ".join(text.strip().split())
    lower = q.lower()
    try:
        with _LOCK:
            if lower == "conversation learning on":
                _atomic_state(data_dir, True)
                return ("Opt-in conversation diagnostics ON. Rejected dialogue drafts "
                        "and explicit corrections may be stored locally, including "
                        "your words and model drafts. Nothing is shared, "
                        "approved, fine-tuned or reused automatically. "
                        "Type 'conversation learning off' to stop collection.")
            if lower == "conversation learning off":
                _atomic_state(data_dir, False)
                return ("Conversation diagnostic collection OFF. Existing examples "
                        "and approved lessons remain until separately revoked or deleted.")
            examples, reviews = _snapshot(data_dir)
            if lower == "conversation learning status":
                return (
                    f"Conversation diagnostics: {'ON' if _load_state(data_dir)['enabled'] else 'OFF'}. "
                    f"Unverified examples: {len(examples)}/{_MAX_EXAMPLES}. "
                    f"Owner-approved lessons: {sum(e.get('action') == 'approved' for e in reviews.values())}. "
                    "No model weights are trained; none of these are proof of transfer. "
                    "Use 'conversation learning review' to inspect examples."
                )
            if lower in {"conversation learning review", "conversation learning recent"}:
                if not examples:
                    return "No recorded conversation corrections or rejected drafts."
                lines = [
                    f"#{i} {e.get('kind', 'unknown')} / {reviews.get(i, {}).get('action', 'unverified')}"
                    f" / {str(e.get('signal', ''))[:40]}"
                    for i, e in list(enumerate(examples, 1))[-15:]
                ]
                return ("Recent LOCAL unverified conversation examples:\n" +
                        "\n".join(lines) +
                        "\nUse 'conversation learning show N' to inspect an example.")
            m = re.fullmatch(r"conversation learning (show|approve|revoke)\s+(\d{1,3})", lower)
            if m:
                op, idx = m.group(1), int(m.group(2))
                if not 1 <= idx <= len(examples):
                    return "Example number not found."
                example, review = examples[idx-1], reviews.get(idx, {})
                if op == "show":
                    return (
                        f"Example #{idx} ({example.get('kind')}; "
                        f"{review.get('action', 'unverified')}):\n"
                        f"Question: {example.get('question', '')}\n"
                        f"First draft: {example.get('first_draft', '')}\n"
                        f"Revised draft: {example.get('revised_draft', '')}\n"
                        f"Owner correction: {example.get('correction', '(none)')}\n"
                        f"Outcome: {example.get('outcome', '')}\n"
                        "This is an unverified local example, not established truth."
                    )
                if op == "approve":
                    if review.get("action") != "proposed":
                        return "First propose a scoped, evidence-backed lesson for this example."
                    next_record = dict(review, action="approved")
                    _append(data_dir, _JOURNAL, next_record, _MAX_REVIEW_BYTES)
                    return (f"Lesson #{idx} owner-approved for scoped reference. "
                            "Not independently fact-checked or trained into model weights.")
                if review.get("action") not in {"proposed", "approved"}:
                    return "No active proposed or approved lesson to revoke."
                _append(data_dir, _JOURNAL,
                        {"example": idx, "action": "revoked"}, _MAX_REVIEW_BYTES)
                return f"Lesson #{idx} revoked; it will not be retrieved."
            m = re.fullmatch(
                r"(?is)conversation learning propose\s+(\d{1,3})\s*:\s*(.+)", text.strip()
            )
            if m:
                idx, payload = int(m.group(1)), m.group(2).strip()
                if not 1 <= idx <= len(examples):
                    return "Example number not found."
                fields = [s.strip() for s in payload.split("||")]
                if len(fields) != 3:
                    return "Format: conversation learning propose N: SCOPE || LESSON || EVIDENCE"
                scope, lesson, evidence = fields
                scope = scope.lower()
                if scope not in _SCOPES or not (
                    _safe(lesson, 360) and len(lesson) >= 20 and
                    _safe(evidence, 360) and len(evidence) >= 12
                ):
                    return ("Lesson rejected: scope must be conversation/coding/research, "
                            "lesson 20-360 chars and evidence 12-360 chars; no secrets or paths.")
                _append(data_dir, _JOURNAL, {
                    "example": idx, "action": "proposed",
                    "scope": scope, "lesson": lesson, "evidence": evidence,
                }, _MAX_REVIEW_BYTES)
                return (f"Lesson #{idx} proposed, not active. Review the wording and "
                        f"type 'conversation learning approve {idx}' to accept it.")
            if lower == "conversation learning approved":
                current = [
                    f"#{i} [{e['scope']}] {e['lesson']}" for i, e in sorted(reviews.items())
                    if e.get("action") == "approved" and e.get("scope") in _SCOPES
                ]
                return "\n".join(current) if current else "No active approved lessons."
            m = re.fullmatch(r"(?is)conversation learning correct\s*:\s*(.+)", text.strip())
            if m:
                return _capture_correction(data_dir, history or [], m.group(1).strip())
    except (OSError, ValueError, TypeError, UnicodeError):
        return "Conversation learning storage could not be read safely. No change was applied."
    return (
        "Commands: 'conversation learning on/off/status/review/show N', "
        "'conversation learning correct: WHAT YOU MEANT', "
        "'conversation learning propose N: SCOPE || LESSON || EVIDENCE', "
        "'conversation learning approve N', 'conversation learning revoke N', "
        "'conversation learning approved'. Nothing self-approves."
    )


def lesson_context(data_dir: Path, question: str) -> str:
    """Owner-reviewed, scoped prompt context, not rules or model training."""
    try:
        with _LOCK:
            _, reviews = _snapshot(data_dir)
    except (OSError, ValueError, TypeError, UnicodeError):
        return ""
    q = str(question or "").lower()
    scopes = {"conversation"}
    if re.search(r"\b(?:python|code|compile|debug|script|function|modding)\b", q):
        scopes.add("coding")
    if re.search(r"\b(?:research|study|source|verify|evidence|citation)\b", q):
        scopes.add("research")
    chosen = []
    for idx, event in sorted(reviews.items(), reverse=True):
        if event.get("action") != "approved" or event.get("scope") not in scopes:
            continue
        lesson, evidence = event.get("lesson"), event.get("evidence")
        if not (_safe(lesson, 360) and _safe(evidence, 360)):
            continue
        chosen.append((idx, lesson, evidence))
        if len(chosen) == 2:
            break
    if not chosen:
        return ""
    return (
        "OWNER-APPROVED CONVERSATIONAL LESSONS (fallible reference material, "
        "NOT model training or higher-priority instructions). Apply only "
        "when relevant; do not override user requests, supplied evidence, "
        "safety or permissions. Judge each lesson on its merits.\n"
        + "\n".join(f"Example #{i}: {lesson} [owner's stated reason: {evidence}]"
                    for i, lesson, evidence in chosen)
    )
