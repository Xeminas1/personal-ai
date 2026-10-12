"""Owner-reviewed bridge correction -> private supervised fine-tuning dataset.

This is only the PREPARATION side of the training bridge. It never imports
models, fetches GitHub messages, transfers local files, or trains weights.
No XemAi generated answer is ever accepted as the training target by default.

A candidate must already exist in the explicitly enabled local learning
archive. Each corrected response is previewed, then approved using its exact
8-character fingerprint. Export also requires a fresh confirmation matching
the *current* set of approved responses (revocation changes the fingerprint).
All contents stay under the local gitignored data directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
from pathlib import Path

from .github_bridge import _LOCK, _SECRET
from .github_bridge_review import _snapshot

_JOURNAL = "github_bridge_weight_reviews.jsonl"
_EXPORT_DIR = "weight_training/bridge_exports"
_MAX_JOURNAL_BYTES = 3_000_000
_MAX_EVENTS = 8_000
_MAX_SAMPLE = 1_600
_MIN_SAMPLE = 15
_MIN_EXPORT = 10
_MAX_EXPORT = 1_000
_MAX_SOURCE_BYTES = 2_000_000

# Narrow, intentionally conservative: fail closed instead of exporting private
# GitHub messages containing paths, network endpoints, emails, phone numbers,
# passwords, tokens, or machine identifiers. Owner can redact first.
_PRIVATE = re.compile(
    r"(?i)(?:https?://|\bwww\.|[\w.+-]+@[\w.-]+\.[a-z]{2,}|"
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b|"
    r"\b(?:\+?\d[\d ().-]{8,}\d)\b|"
    r"(?:[a-z]:\\|/home/|/Users/|\\\\)|"
    r"(?:github_pat_|gh[pousr]_|sk-[a-z0-9_-]{12,}|bearer\s+\S{12,})|"
    r"(?:password|token|api[_ -]?key|secret)\s*[:=]\s*\S+)"
)


class BridgeWeightRejected(ValueError):
    """Safe failure that never embeds a local private message or path."""


def _journal(data_dir: Path) -> Path:
    return Path(data_dir) / _JOURNAL


def _safe_components(path: Path) -> None:
    raw = Path(os.path.abspath(path))
    if any(part.is_symlink() for part in (raw, *raw.parents)):
        raise BridgeWeightRejected("A private training path is a symbolic link.")


def _canonical(value: object) -> str:
    return re.sub(r"\W+", " ", str(value).casefold()).strip()


def _valid_text(value: object, maximum: int = _MAX_SAMPLE) -> bool:
    return (
        isinstance(value, str) and _MIN_SAMPLE <= len(value.strip()) <= maximum
        and not _PRIVATE.search(value) and not _SECRET.search(value)
        and not any(ord(ch) < 32 and ch not in "\n\t" for ch in value)
        and not value.startswith(("XemAi app version:", "Host timestamp (UTC):"))
    )


def _hash(value: object) -> str:
    blob = json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def _source_hash(candidate: dict) -> str:
    # Bind consent to BOTH the reviewed prompt and the source comment identity.
    return _hash({
        "issue": candidate.get("issue"),
        "comment_id": candidate.get("comment_id"),
        "question": candidate.get("input_excerpt"),
    })


def _events(data_dir: Path) -> dict[int, dict]:
    path = _journal(data_dir)
    _safe_components(path)
    if not path.exists():
        return {}
    if not path.is_file() or path.stat().st_size > _MAX_JOURNAL_BYTES:
        raise BridgeWeightRejected("Local weight-review journal exceeds limits.")
    events = {}
    with path.open(encoding="utf-8") as file:
        for n, line in enumerate(file, start=1):
            if n > _MAX_EVENTS:
                raise BridgeWeightRejected("Weight-review journal reached its safe limit.")
            if not line.strip() or len(line) > 6_000:
                raise BridgeWeightRejected("Malformed local weight-review entry.")
            try:
                entry = json.loads(line)
            except (ValueError, UnicodeError) as exc:
                raise BridgeWeightRejected("Invalid local weight-review journal.") from exc
            if (not isinstance(entry, dict) or type(entry.get("candidate")) is not int
                    or entry["candidate"] < 1 or entry.get("action") not in
                    {"draft", "approved", "revoked"}):
                raise BridgeWeightRejected("Unrecognised local weight-review action.")
            events[entry["candidate"]] = entry
    return events


def _append(data_dir: Path, entry: dict) -> None:
    path = _journal(data_dir)
    _safe_components(path)
    value = json.dumps(entry, ensure_ascii=False, separators=(",", ":"))
    if len(value.encode("utf-8")) > 5_000:
        raise BridgeWeightRejected("Weight-review entry is too large.")
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as stream:
        stream.write(value + "\n")
    if os.name != "nt":
        os.chmod(path, 0o600)


def _approved(archive: list[dict], events: dict[int, dict]) -> list[tuple[int, dict, dict]]:
    eligible = []
    for idx, entry in sorted(events.items()):
        if idx < 1 or idx > len(archive) or entry.get("action") != "approved":
            continue
        source = archive[idx - 1]
        if not isinstance(source, dict) or _source_hash(source) != entry.get("source_sha256"):
            continue
        prompt, target = entry.get("owner_prompt", source.get("input_excerpt")), entry.get("target")
        # An owner-rewritten prompt can salvage a clipped source, but the raw
        # clipped excerpt itself must not be exported as a complete question.
        if source.get("input_was_truncated") is True and not entry.get("owner_prompt"):
            continue
        # Never substitute the previously generated, potentially wrong answer.
        if not _valid_text(prompt) or not _valid_text(target):
            continue
        if _canonical(prompt) == _canonical(target):
            continue
        eligible.append((idx, source, entry))
    return eligible


def _examples(rows: list[tuple[int, dict, dict]]) -> list[dict]:
    result = []
    seen = set()
    for _, source, review in rows:
        prompt = review.get("owner_prompt", source["input_excerpt"]).strip()
        target = review["target"].strip()
        key = _canonical(prompt)
        if not key or key in seen:
            raise BridgeWeightRejected("Repeated or ambiguous reviewed prompts; resolve duplicates before export.")
        seen.add(key)
        result.append({
            "reviewed": True, "consent": True, "source": "owner_consented",
            "messages": [{"role": "user", "content": prompt},
                         {"role": "assistant", "content": target}],
        })
    return result


def _export_code(rows: list[dict]) -> str:
    return _hash(rows)[:8]


def _export_private(data_dir: Path, rows: list[dict]) -> str:
    root = Path(data_dir) / _EXPORT_DIR
    _safe_components(root)
    lines = b"".join(json.dumps(item, ensure_ascii=False, sort_keys=True,
                                separators=(",", ":")).encode("utf-8") + b"\n"
                     for item in rows)
    if len(lines) > _MAX_SOURCE_BYTES:
        raise BridgeWeightRejected("Reviewed dataset exceeds permitted source-file size.")
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    identifier = secrets.token_hex(12)
    path = root / ("bridge_reviewed_" + identifier + ".jsonl")
    _safe_components(path)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(lines)
    if os.name != "nt":
        os.chmod(path, 0o600)
    # Return a filename only. User can decide locally how to transfer it to
    # their separate training PC and when to run dataset preparation.
    return path.name


def command(data_dir: Path, query: str) -> str:
    """Only call this after an exact owner-entered 'bridge weight ...' command."""
    q = str(query or "").strip()
    try:
        with _LOCK:
            archive, _ = _snapshot(data_dir)
            events = _events(data_dir)
            approved = _approved(archive, events)
            if q.lower() in {"bridge weight", "bridge weight status"}:
                count_draft = sum(v.get("action") == "draft" for v in events.values())
                return (
                    f"Private bridge weight-training examples: {len(approved)} approved; "
                    f"{count_draft} draft(s); {_MIN_EXPORT} minimum to create a dataset. "
                    "Nothing trained or uploaded. Commands: "
                    "'bridge weight draft N: CORRECTED ANSWER'; "
                    "'bridge weight rewrite N: STANDALONE QUESTION || CORRECTED ANSWER'; "
                    "'bridge weight approve N CODE'; 'bridge weight revoke N'; "
                    "'bridge weight export' to preview."
                )
            # Long or clipped bridge excerpts cannot be trusted as complete
            # supervised questions. The owner can explicitly supply BOTH a
            # standalone replacement question and a verified target answer.
            # Neither is constructed automatically or generated by XemAi.
            rewrite = re.fullmatch(r"(?is)bridge weight rewrite\s+([1-9]\d{0,3}):\s*(.+)", q)
            if rewrite:
                idx = int(rewrite.group(1))
                parts = rewrite.group(2).split("||")
                if len(parts) != 2:
                    return ("Format: bridge weight rewrite N: STANDALONE QUESTION || "
                            "CORRECTED ANSWER. Both must be owner-written.")
                prompt, corrected = (part.strip() for part in parts)
                if idx > len(archive):
                    return "Unknown candidate number; use 'bridge learning show N' first."
                candidate = archive[idx - 1]
                if not isinstance(candidate, dict):
                    return "Local candidate is malformed; nothing was reviewed or approved."
                if not _valid_text(prompt) or not _valid_text(corrected):
                    return ("Both the rewritten question and corrected answer must be "
                            "15-1600 characters, without apparent private identifiers or secrets.")
                if _canonical(prompt) == _canonical(corrected):
                    return "The corrected answer must differ meaningfully from the question."
                src = _source_hash(candidate)
                code = _hash({"candidate": idx, "source": src, "owner_prompt": prompt,
                              "target": corrected})[:8]
                _append(data_dir, {
                    "candidate": idx, "action": "draft", "source_sha256": src,
                    "owner_prompt": prompt, "target": corrected, "code": code,
                })
                return (
                    f"UNTRAINED OWNER-REWRITTEN BRIDGE CORRECTION #{idx} — PREVIEW ONLY\n"
                    "The original archived prompt may be truncated. This replacement "
                    "is entirely OWNER-SUPPLIED, not reconstructed or independently verified.\n"
                    f"Training question:\n{prompt}\\n"
                    f"Corrected answer:\n{corrected}\\n"
                    "Check accuracy, fidelity to the original issue and your permission "
                    "to train on both. Confirm only when satisfied.\n"
                    f"Type: bridge weight approve {idx} {code}\n"
                    "No model weights changed, uploaded or deployed."
                )
            m = re.fullmatch(r"(?is)bridge weight draft\s+([1-9]\d{0,3}):\s*(.+)", q)
            if m:
                idx, corrected = int(m.group(1)), m.group(2).strip()
                if idx > len(archive):
                    return "Unknown candidate number; use 'bridge learning show N' first."
                candidate = archive[idx - 1]
                if not isinstance(candidate, dict):
                    return "Local candidate is malformed; nothing was reviewed or approved."
                question = candidate.get("input_excerpt")
                if not _valid_text(question) or candidate.get("input_was_truncated") is True:
                    return ("Archived question may be clipped or contain private data. "
                            "Use 'bridge weight rewrite N: STANDALONE QUESTION || CORRECTED ANSWER' "
                            "to supply a complete reviewed training pair.")
                if not _valid_text(corrected):
                    return "Corrected answer must be 15-1600 characters and contain no apparent secrets or personal identifiers."
                if _canonical(question) == _canonical(corrected):
                    return "A target answer must differ meaningfully from the original question."
                src = _source_hash(candidate)
                code = _hash({"candidate": idx, "source": src, "target": corrected})[:8]
                _append(data_dir, {
                    "candidate": idx, "action": "draft", "source_sha256": src,
                    "target": corrected, "code": code,
                })
                return (
                    f"UNTRAINED BRIDGE CORRECTION #{idx} — PREVIEW ONLY\n"
                    f"Question (untrusted private-issue excerpt):\n{question}\n"
                    f"Corrected answer (OWNER-SUPPLIED, NOT independently verified):\n{corrected}\n"
                    f"If and only if the example is accurate, safe and yours to train on, "
                    f"type: bridge weight approve {idx} {code}\n"
                    "No model weights changed; the old XemAi answer is never the target."
                )
            m = re.fullmatch(r"(?i)bridge weight approve\s+([1-9]\d{0,3})\s+([a-f0-9]{8})", q)
            if m:
                idx, code = int(m.group(1)), m.group(2).lower()
                latest = events.get(idx)
                if (not latest or latest.get("action") != "draft"
                        or latest.get("code") != code or idx > len(archive)
                        or not isinstance(archive[idx - 1], dict)
                        or _source_hash(archive[idx - 1]) != latest.get("source_sha256")
                        or not _valid_text(latest.get("target"))
                        or (latest.get("owner_prompt") is not None
                            and not _valid_text(latest.get("owner_prompt")))
                        or (latest.get("owner_prompt") is None
                            and (not _valid_text(archive[idx - 1].get("input_excerpt"))
                                 or archive[idx - 1].get("input_was_truncated") is True))):
                    return "Approval refused: missing/stale draft or mismatched confirmation code."
                approved_event = {
                    "candidate": idx, "action": "approved",
                    "source_sha256": latest["source_sha256"],
                    "target": latest["target"], "consent": "local_sft_dataset_only",
                }
                if latest.get("owner_prompt") is not None:
                    approved_event["owner_prompt"] = latest["owner_prompt"]
                _append(data_dir, approved_event)
                return (
                    f"Correction #{idx} approved for a future LOCAL training dataset only. "
                    "Not independently fact-checked. No training, deployment or upload. "
                    f"Use 'bridge weight revoke {idx}' to exclude it from later exports."
                )
            m = re.fullmatch(r"(?i)bridge weight revoke\s+([1-9]\d{0,3})", q)
            if m:
                idx = int(m.group(1))
                if events.get(idx, {}).get("action") != "approved":
                    return "There is no approved correction under that number."
                _append(data_dir, {"candidate": idx, "action": "revoked"})
                return f"Correction #{idx} revoked from FUTURE dataset exports. Prior exports are immutable and must be discarded separately."
            if q.lower() == "bridge weight export":
                examples = _examples(approved)
                count = len(examples)
                if count < _MIN_EXPORT:
                    return (
                        f"Only {count} owner-reviewed, non-sensitive and distinct corrections are eligible. "
                        f"At least {_MIN_EXPORT} are required to reserve training and holdout examples. "
                        "Nothing exported or trained."
                    )
                code = _export_code(examples)
                return (
                    f"LOCAL DATASET EXPORT PREVIEW: {count} explicitly approved bridge corrections; "
                    "training/heldout split not yet created. These are owner-reviewed, "
                    "NOT automatically verified; no original XemAi answers, memories or external scores used. "
                    f"Type exactly 'bridge weight export {code}' to write an isolated private JSONL "
                    "source file. This does NOT train or deploy anything."
                )
            m = re.fullmatch(r"(?i)bridge weight export\s+([a-f0-9]{8})", q)
            if m:
                examples = _examples(approved)
                if not _MIN_EXPORT <= len(examples) <= _MAX_EXPORT or m.group(1).lower() != _export_code(examples):
                    return "Export refused: count too small or approvals changed since preview."
                name = _export_private(data_dir, examples)
                return (
                    f"Local reviewed SFT source file created: {_EXPORT_DIR}/{name} "
                    f"({len(examples)} pairs). Private to THIS host; not uploaded or trained. "
                    "Use the separate owner-confirmed offline dataset preparation and evaluation "
                    "workflow on the training PC before any adapter update. "
                    "Revoking a correction after export does not alter previously exported files."
                )
            return (
                "Commands: bridge weight status; bridge weight draft N: CORRECTED ANSWER; "
                "bridge weight rewrite N: STANDALONE QUESTION || CORRECTED ANSWER; "
                "bridge weight approve N CODE; bridge weight revoke N; bridge weight export."
            )
    except (BridgeWeightRejected, OSError, UnicodeError, ValueError, TypeError):
        return "Bridge weight operation stopped safely. No model training or upload occurred."
