"""External ChatGPT/GitHub conversation scores, recorded for owner review ONLY.

A score in a GitHub comment is untrusted even in a private issue: it is
not proof of ChatGPT origin, task correctness or model learning. It is never
fed into XemAi's regular prompt or promoted into approved lessons.
"""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

_LOCK = threading.RLock()
_FILE = "bridge_external_review_scores.jsonl"
_MAX_ROWS = 250
_MAX_BYTES = 220_000
_LINE = re.compile(
    r"(?im)^XemAi review score \(external, unverified\): "
    r"target=(\d{1,16}); score=(10|[0-9]); "
    r"aspect=(reasoning|evidence|accuracy|usefulness); "
    r"reason=([^\r\n]{12,180})$"
)
_UNSAFE = re.compile(
    r"(?i)(?:github_pat_|gh[pousr]_|sk-[a-z0-9_-]{12,}|"
    r"[a-z]:\\|/home/[^/\s]+/|\\users\\|"
    r"[\w.+-]+@[\w.-]+\.[a-z]{2,}|"
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b|(?:password|token|secret)\s*[:=])"
)


def _load(path: Path) -> list[dict]:
    if not path.exists():
        return []
    if path.stat().st_size > _MAX_BYTES:
        raise ValueError("External review journal too large.")
    records = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            if not line.strip():
                continue
            if len(records) >= _MAX_ROWS:
                raise ValueError("External review limit reached.")
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("Invalid external review.")
            records.append(row)
    return records


def ingest_reviews(data_dir: Path, *, issue: int, comments: list[dict]) -> int:
    """Only accept a bounded syntax targeting a REAL preceding XemAi comment."""
    if type(issue) is not int or issue <= 0 or not isinstance(comments, list):
        return 0
    from .github_bridge_auto import _self_comment
    path = Path(data_dir) / _FILE
    with _LOCK:
        try:
            rows = _load(path)
            seen = {(x.get("issue"), x.get("source_comment_id")) for x in rows}
            self_ids = {
                r["id"] for r in comments
                if isinstance(r, dict) and type(r.get("id")) is int
                and isinstance(r.get("body"), str) and _self_comment(r["body"])
            }
            new = 0
            for item in sorted(comments, key=lambda r: r.get("id", 0) if isinstance(r, dict) else 0):
                if len(rows) >= _MAX_ROWS:
                    break
                if not isinstance(item, dict) or type(item.get("id")) is not int:
                    continue
                cid, body = item["id"], item.get("body")
                if not isinstance(body, str) or len(body) > 7000 or _self_comment(body):
                    continue
                if (issue, cid) in seen:
                    continue
                matches = list(_LINE.finditer(body))
                if len(matches) != 1:
                    continue
                match = matches[0]
                target, score, aspect, reason = match.groups()
                target = int(target)
                reason = reason.strip()
                if (target not in self_ids or target >= cid or
                        _UNSAFE.search(reason) or any(ord(c) < 32 for c in reason)):
                    continue
                record = {
                    "issue": issue, "source_comment_id": cid,
                    "target_comment_id": target, "score": int(score),
                    "aspect": aspect, "reason": reason,
                    "source": "github_external_unverified", "owner_approved": False,
                    "training_applied": False,
                }
                encoded = json.dumps(record, ensure_ascii=False) + "\n"
                if path.exists() and path.stat().st_size + len(encoded.encode("utf-8")) > _MAX_BYTES:
                    break
                path.parent.mkdir(parents=True, exist_ok=True)
                fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "a", encoding="utf-8") as stream:
                    stream.write(encoded)
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass
                rows.append(record)
                seen.add((issue, cid))
                new += 1
            return new
        except (OSError, UnicodeError, ValueError, TypeError):
            return 0


def review_scores(data_dir: Path, *, issue: int, show: int | None = None) -> str:
    with _LOCK:
        try:
            rows = [r for r in _load(Path(data_dir) / _FILE) if r.get("issue") == issue]
        except (OSError, UnicodeError, ValueError, TypeError):
            return "External bridge ratings unavailable; no trusted lessons affected."
    if not rows:
        return "No external GPT discussion scores are archived for the current issue."
    if show is not None:
        if not 1 <= show <= len(rows):
            return "No external rating with that index."
        item = rows[show - 1]
        return (
            f"External review #{show}, unverified:\n"
            f"XemAi GitHub comment #{item['target_comment_id']}\n"
            f"Scored {item['score']}/10 for {item['aspect']}\n"
            f"Reason: {item['reason']}\n"
            "This is external feedback, not owner-approved knowledge, an "
            "authenticated GPT judgment, or measured model learning."
        )
    return (
        "GitHub external review scores (UNVERIFIED, not model rewards):\n"
        + "\n".join(
            f"#{i}: XemAi comment {r['target_comment_id']} — {r['score']}/10 "
            f"({r['aspect']})"
            for i, r in list(enumerate(rows, 1))[-10:]
        )
        + "\nUse 'bridge review show N' for the short reason. "
        "Use your own judgment before creating a separate reviewed lesson."
    )
