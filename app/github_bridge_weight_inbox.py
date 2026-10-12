"""Opt-in PRIVATE GitHub proposal inbox for reviewed bridge weight examples.

Untrusted issue comments are inert JSON data, not model instructions.
Synchronising records proposals *only*: it never approves a lesson,
changes user memory, trains neural weights, uploads files or executes tools.

Activation is a literal local owner command, disabled by default. The inbox
uses the existing bridge repo and credential, and requires that repo to
remain private on each read. A separate explicit owner adoption code is
required before a proposal enters the future local SFT dataset.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from .github_bridge import _LOCK, _get_client, load_state, save_state, valid_repo
from .github_bridge_review import _snapshot
from .github_bridge_weight import (
    BridgeWeightRejected, _append, _canonical, _events, _hash,
    _safe_components, _source_hash, _valid_text,
)

_MARKER = "XEMAI_BRIDGE_WEIGHT_PROPOSAL_V1\n"
_SCHEMA = "xemai.bridge_weight_proposal.v1"
_FILE = "github_bridge_weight_proposals.jsonl"
_MAX_ROWS = 500
_MAX_SIZE = 2_000_000
_MAX_SINGLE = 4_000
_MAX_SCAN = 40
_MIN_TICK_SECONDS = 300


def _path(data_dir: Path) -> Path:
    return Path(data_dir) / _FILE


def _read(data_dir: Path) -> list[dict]:
    path = _path(data_dir)
    _safe_components(path)
    if not path.exists():
        return []
    if not path.is_file() or path.stat().st_size > _MAX_SIZE:
        raise BridgeWeightRejected("Private proposal inbox exceeded its safety limits.")
    rows = []
    seen = set()
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if len(rows) >= _MAX_ROWS or len(line) > _MAX_SINGLE:
                raise BridgeWeightRejected("Private proposal inbox reached its safe limit.")
            try:
                row = json.loads(line)
            except (ValueError, UnicodeError) as exc:
                raise BridgeWeightRejected("Private proposal inbox was not valid JSON.") from exc
            if (not isinstance(row, dict)
                    or type(row.get("comment_id")) is not int
                    or row["comment_id"] <= 0
                    or type(row.get("candidate")) is not int
                    or row["candidate"] <= 0
                    or not re.fullmatch(r"[0-9a-f]{64}", str(row.get("source_sha256", "")))
                    or not _valid_text(row.get("prompt"))
                    or not _valid_text(row.get("answer"))
                    or not _valid_text(row.get("rationale"), maximum=360)
                    or row["comment_id"] in seen):
                raise BridgeWeightRejected("Private proposal inbox contains a malformed row.")
            seen.add(row["comment_id"])
            rows.append(row)
    return rows


def _append_inbox(data_dir: Path, row: dict) -> None:
    path = _path(data_dir)
    _safe_components(path)
    raw = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
    if len(raw.encode("utf-8")) > _MAX_SINGLE - 1:
        raise BridgeWeightRejected("A proposed training example exceeded inbox limits.")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT |
                 getattr(os, "O_NOFOLLOW", 0), 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as stream:
        stream.write(raw + "\n")
    if os.name != "nt":
        os.chmod(path, 0o600)


def _parse(body: object) -> dict | None:
    """Accept only the exact, tightly bounded data interchange envelope."""
    if (not isinstance(body, str) or len(body) > _MAX_SINGLE
            or not body.startswith(_MARKER)):
        return None
    try:
        record = json.loads(body[len(_MARKER):])
    except (ValueError, UnicodeError):
        return None
    if not isinstance(record, dict) or set(record) != {
        "schema", "source_comment_id", "prompt", "answer", "rationale",
    }:
        return None
    if record["schema"] != _SCHEMA:
        return None
    if type(record["source_comment_id"]) is not int or record["source_comment_id"] <= 0:
        return None
    if (not _valid_text(record["prompt"]) or not _valid_text(record["answer"])
            or not _valid_text(record["rationale"], maximum=360)
            or _canonical(record["prompt"]) == _canonical(record["answer"])):
        return None
    return record


def _approval_code(row: dict) -> str:
    return _hash({
        "comment_id": row["comment_id"],
        "candidate": row["candidate"],
        "source_sha256": row["source_sha256"],
        "prompt": row["prompt"],
        "answer": row["answer"],
    })[:8]


def _sync(data_dir: Path, *, client=None) -> dict:
    with _LOCK:
        state = load_state(data_dir)
        repo = state.get("repo")
        issue = state.get("weight_inbox_issue")
        if (state.get("weight_inbox_enabled") is not True
                or not valid_repo(repo) or type(issue) is not int or issue < 1):
            return {"status": "disabled"}
        # Read-only external fetch occurs outside the app's state lock.
        last = int(state.get("weight_inbox_cursor") or 0)
    api = _get_client(data_dir, client)
    api.verify_private(repo)
    comments = api.comments(repo, issue)
    if not isinstance(comments, list):
        return {"status": "invalid_remote_data"}
    with _LOCK:
        check = load_state(data_dir)
        if (check.get("weight_inbox_enabled") is not True
                or check.get("weight_inbox_issue") != issue
                or check.get("repo") != repo):
            return {"status": "disabled_before_write"}
        archive, _ = _snapshot(data_dir)
        existing = _read(data_dir)
        seen = {row["comment_id"] for row in existing}
        new = sorted((item for item in comments
                      if isinstance(item, dict) and type(item.get("id")) is int
                      and item["id"] > last), key=lambda item: item["id"])
        scanned = imported = 0
        latest = last
        for item in new[:_MAX_SCAN]:
            cid = item["id"]
            scanned += 1
            latest = max(latest, cid)
            if cid in seen or len(existing) + imported >= _MAX_ROWS:
                continue
            record = _parse(item.get("body"))
            if record is None:
                continue
            matches = [(idx, source) for idx, source in enumerate(archive, 1)
                       if isinstance(source, dict)
                       and source.get("comment_id") == record["source_comment_id"]]
            if len(matches) != 1:
                # Never guess a missing/out-of-order local archive index.
                continue
            idx, source = matches[0]
            row = {
                "comment_id": cid,
                "candidate": idx,
                "source_sha256": _source_hash(source),
                "prompt": record["prompt"].strip(),
                "answer": record["answer"].strip(),
                "rationale": record["rationale"].strip(),
            }
            _append_inbox(data_dir, row)
            seen.add(cid)
            imported += 1
        if latest > last:
            check["weight_inbox_cursor"] = latest
            save_state(data_dir, check)
        return {
            "status": "ok", "new_proposals": imported, "scanned": scanned,
            "stored": len(existing) + imported,
            "more_possible": len(new) > _MAX_SCAN,
        }


def tick(data_dir: Path, *, logger=None, client=None, now=None) -> dict:
    """Five-minute read-only poll inside existing 15-second bridge host loop."""
    instant = float(now if now is not None else time.time())
    with _LOCK:
        state = load_state(data_dir)
        if state.get("weight_inbox_enabled") is not True:
            return {"status": "disabled"}
        if instant - float(state.get("weight_inbox_last_poll") or 0) < _MIN_TICK_SECONDS:
            return {"status": "not_due"}
        state["weight_inbox_last_poll"] = instant
        save_state(data_dir, state)
    try:
        return _sync(data_dir, client=client)
    except (OSError, ValueError, TypeError) as exc:
        if logger:
            logger.warning("Private bridge weight inbox read failed | type=%s",
                           type(exc).__name__)
        return {"status": "read_failed"}


def command(data_dir: Path, query: str, *, client=None) -> str:
    """Direct human-entered controls; remote comments can never invoke these."""
    q = str(query or "").strip()
    try:
        with _LOCK:
            state = load_state(data_dir)
            rows = _read(data_dir)
            archive, _ = _snapshot(data_dir)
            if q.lower() in {"bridge weight inbox", "bridge weight inbox status"}:
                issue = state.get("weight_inbox_issue")
                return (
                    f"Private bridge correction inbox: "
                    f"{'ON' if state.get('weight_inbox_enabled') else 'OFF'}. "
                    f"Staged untrusted proposals: {len(rows)}. "
                    f"Separate issue configured: {'yes' if type(issue) is int and issue > 0 else 'no'}. "
                    "Nothing owner-approved, trained, or uploaded by this inbox. "
                    "Commands: bridge weight inbox on ISSUE; off; sync; list; show N; approve N CODE."
                )
            if q.lower() == "bridge weight inbox off":
                state["weight_inbox_enabled"] = False
                save_state(data_dir, state)
                return "Private proposal inbox OFF. Existing local proposals retained; no model changes."
            match = re.fullmatch(r"(?i)bridge weight inbox on\s+([1-9]\d{0,5})", q)
            if match:
                issue = int(match.group(1))
                repo = state.get("repo")
                if not valid_repo(repo):
                    return "First configure the existing private GitHub bridge."
                # Enable only after verifying that the same repository is
                # private and the separate private issue can be read.
                api = _get_client(data_dir, client)
                api.verify_private(repo)
                api.comments(repo, issue)
                state = load_state(data_dir)
                if state.get("repo") != repo:
                    return "Bridge destination changed; inbox activation cancelled."
                state["weight_inbox_enabled"] = True
                state["weight_inbox_issue"] = issue
                state["weight_inbox_cursor"] = 0
                state["weight_inbox_last_poll"] = 0
                save_state(data_dir, state)
                return (
                    "Private proposal inbox ON for the chosen separate issue. "
                    "Only untrusted owner-review proposals may be staged. "
                    "No automatic approval, training, model or memory updates. "
                    "Use 'bridge weight inbox sync' to check immediately."
                )
            if q.lower() == "bridge weight inbox sync":
                # Network operations happen outside any nested logic; the
                # shared RLock supports the short pre/post-read state checks.
                result = _sync(data_dir, client=client)
                if result.get("status") != "ok":
                    return "Private proposal sync did not complete. No approvals or training."
                return (
                    f"Private proposal sync: {result['new_proposals']} new; "
                    f"{result['stored']} staged. None approved or trained. "
                    "Use 'bridge weight inbox list' to inspect."
                )
            if q.lower() == "bridge weight inbox list":
                if not rows:
                    return "No private correction proposals staged. Nothing approved or trained."
                return (
                    f"Untrusted private bridge proposals ({len(rows)} staged):\n" +
                    "\n".join(
                        f"#{i} -> existing candidate #{row['candidate']}: "
                        f"{row['prompt'][:95]}"
                        for i, row in enumerate(rows[:8], 1)
                    ) + "\nUse 'bridge weight inbox show N' to inspect and approve individually."
                )
            match = re.fullmatch(r"(?i)bridge weight inbox (show|approve)\s+([1-9]\d{0,3})(?:\s+([a-f0-9]{8}))?", q)
            if match:
                action, idx = match.group(1).lower(), int(match.group(2))
                if idx > len(rows):
                    return "Unknown staged proposal number. Use 'bridge weight inbox list'."
                row = rows[idx - 1]
                cidx = row["candidate"]
                if cidx > len(archive) or not isinstance(archive[cidx - 1], dict):
                    return "Source learning candidate missing; proposal cannot be adopted."
                if _source_hash(archive[cidx - 1]) != row["source_sha256"]:
                    return "The original archived source changed; proposal cannot be adopted."
                if action == "show":
                    return (
                        f"UNTRUSTED PRIVATE TRAINING PROPOSAL #{idx} — PREVIEW ONLY\n"
                        f"Archive candidate #{cidx}; owner approval NOT recorded.\n"
                        f"STANDALONE proposed question:\n{row['prompt']}\n"
                        f"Proposed corrected answer:\n{row['answer']}\n"
                        f"Rationale (unverified):\n{row['rationale']}\n"
                        "Examine accuracy, source attribution, private data, and your "
                        "permission to train on the example. Nothing is independently fact-checked.\n"
                        f"To adopt this EXACT training pair for a future LOCAL dataset, "
                        f"type: bridge weight inbox approve {idx} {_approval_code(row)}\n"
                        "No neural weights, chat memory or GitHub content will be changed."
                    )
                if match.group(3) != _approval_code(row):
                    return "Approval refused: missing or mismatched proposal confirmation code."
                current = _events(data_dir).get(cidx, {})
                if current.get("action") == "approved":
                    return (
                        f"Candidate #{cidx} already has an approved correction. "
                        "To replace it, explicitly revoke the old correction first. "
                        "The existing approval remains unchanged."
                    )
                # The owner adopts an external DRAFT, not automatically trusted
                # as a reviewed factual truth. A local exact-code click is
                # explicit dataset consent, separate from training consent.
                _append(data_dir, {
                    "candidate": cidx, "action": "approved",
                    "source_sha256": row["source_sha256"],
                    "owner_prompt": row["prompt"],
                    "target": row["answer"],
                    "consent": "local_sft_dataset_only",
                    "origin": "owner_adopted_private_bridge_proposal",
                    "proposal_comment_id": row["comment_id"],
                })
                return (
                    f"Private proposal #{idx} adopted for future LOCAL dataset "
                    f"as candidate #{cidx}. Not independently verified. "
                    "No actual training, upload or deployment; use "
                    f"'bridge weight revoke {cidx}' to exclude it from future exports."
                )
            return (
                "Commands: bridge weight inbox status; on ISSUE; off; sync; "
                "list; show N; approve N CODE."
            )
    except (OSError, ValueError, TypeError, AttributeError):
        return "Private bridge proposal operation stopped safely. No training or approval occurred."
