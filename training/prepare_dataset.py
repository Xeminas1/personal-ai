"""Offline, owner-gated preparation of human-reviewed conversational SFT examples.

Never imports XemAi memory, bridge, chats, reviews or ratings; requires an explicit
absolute owner-selected JSONL input file. Outputs remain in gitignored data/.
Stdlib only, safe to test on Windows and Linux without a GPU.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
import uuid
from pathlib import Path

MAX_SOURCE_BYTES = 2_000_000
MAX_EXAMPLES = 1000
MAX_TURNS = 12
MAX_CONTENT = 2500
MIN_EXAMPLES = 10
PRIVATE_PATTERN = re.compile(
    r"(?i)(?:https?://|[\w.+-]+@[\w.-]+\.[a-z]{2,}|"
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b|"
    r"\b(?:\+?\d[\d ().-]{8,}\d)\b|"
    r"(?:[a-z]:\\(?:users|windows)\\|/home/[^/\s]+/|\\\\users\\)|"
    r"(?:gh[pousr]_[a-z0-9_]{12,}|github_pat_[a-z0-9_]{12,}|"
    r"sk-[a-z0-9_-]{16,}|bearer\s+[a-z0-9._-]{12,})|"
    r"(?:password|token|api[_ -]?key|secret)\s*[:=]\s*\S+)"
)
LABEL = re.compile(r"[a-z][a-z0-9_-]{0,35}$")
_REPO_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_OUTPUT = _REPO_ROOT / "data" / "weight_training"


class DatasetRejected(ValueError):
    """Fail closed without echoing sample text or local paths."""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _safe_path(path: Path, *, file: bool = False) -> Path:
    """Reject symlinks even at existing parent components."""
    raw = Path(path).absolute()
    for piece in (raw, *raw.parents):
        if piece.is_symlink():
            raise DatasetRejected("Symlink paths are not allowed.")
    # Collapse '..' before checking whether output is inside the public tree.
    path = Path(os.path.normpath(str(raw)))
    for piece in (path, *path.parents):
        if piece.is_symlink():
            raise DatasetRejected("Symlink paths are not allowed.")
    if file and (not path.is_file() or not stat.S_ISREG(path.stat().st_mode)):
        raise DatasetRejected("Input must be an existing regular file.")
    return path


def _private_output(path: Path) -> Path:
    path = _safe_path(path)
    if not path.is_absolute():
        raise DatasetRejected("Output directory must be absolute.")
    try:
        relative = path.relative_to(_REPO_ROOT)
    except ValueError:
        pass  # An owner-selected path outside the public repository is permitted.
    else:
        if not relative.parts or relative.parts[0] != "data":
            raise DatasetRejected("Output inside the public repository must be under gitignored data/.")
    return path


def _content(value: object) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > MAX_CONTENT:
        raise DatasetRejected("Invalid or oversized message content.")
    if any(ord(ch) < 32 and ch not in "\n\t" for ch in value):
        raise DatasetRejected("Control characters in training text.")
    if PRIVATE_PATTERN.search(value):
        raise DatasetRejected("Potentially sensitive text: manually redact before retrying.")
    return value.strip()


def validate_example(raw: object) -> dict:
    if not isinstance(raw, dict) or set(raw) != {"reviewed", "consent", "source", "messages"}:
        raise DatasetRejected("Unexpected fields or missing consent fields.")
    if raw["reviewed"] is not True or raw["consent"] is not True:
        raise DatasetRejected("Every record requires explicit review and consent.")
    if raw["source"] not in ("synthetic", "owner_consented"):
        raise DatasetRejected("Unapproved dataset source.")
    messages = raw["messages"]
    if not isinstance(messages, list) or not 2 <= len(messages) <= MAX_TURNS or len(messages) % 2:
        raise DatasetRejected("Expect 2-12 alternating user/assistant messages.")
    clean = []
    for i, msg in enumerate(messages):
        required_role = "user" if i % 2 == 0 else "assistant"
        if not isinstance(msg, dict) or set(msg) != {"role", "content"} or msg["role"] != required_role:
            raise DatasetRejected("Malformed or out-of-order conversation roles.")
        clean.append({"role": required_role, "content": _content(msg["content"])})
    return {"messages": clean}


def _read_input(path: Path) -> tuple[list[dict], str]:
    path = _safe_path(path, file=True)
    if path.stat().st_size > MAX_SOURCE_BYTES:
        raise DatasetRejected("Input exceeds approved local size limit.")
    source = path.read_bytes()
    try:
        lines = source.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise DatasetRejected("Input must be UTF-8 JSONL.") from exc
    if not MIN_EXAMPLES <= len(lines) <= MAX_EXAMPLES:
        raise DatasetRejected("Need 10-1000 individually reviewed examples.")
    examples, seen = [], set()
    for line in lines:
        if len(line) > MAX_TURNS * MAX_CONTENT * 2 or not line.strip():
            raise DatasetRejected("Blank or oversized JSONL record.")
        try:
            item = validate_example(json.loads(line))
        except (ValueError, TypeError) as exc:
            raise DatasetRejected("Invalid or unreviewed training record.") from exc
        # Same visible prompt must not appear in train and holdout with merely
        # altered casing/punctuation or a different claimed correct answer.
        prompt = item["messages"][:-1]
        normalized = [
            {"role": m["role"], "content": re.sub(r"\W+", " ", m["content"].casefold()).strip()}
            for m in prompt
        ]
        fingerprint = _digest(_json(normalized))
        if fingerprint in seen:
            raise DatasetRejected("Repeated training prompt; fix train/evaluation leakage risk.")
        seen.add(fingerprint)
        examples.append(item)
    return examples, _digest(source)


def _create_private(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
    if os.name != "nt":
        os.chmod(path, 0o600)


def _lines(rows: list[dict]) -> bytes:
    return b"".join(_json(row) + b"\n" for row in rows)


def prepare(source: Path, out_root: Path = _DEFAULT_OUTPUT, *, seed: str, label: str) -> Path:
    """No subprocesses, model calls, network requests or automatic data gathering."""
    if not isinstance(seed, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{4,64}", seed):
        raise DatasetRejected("Invalid deterministic split seed.")
    if not LABEL.fullmatch(label):
        raise DatasetRejected("Invalid safe run label.")
    source = _safe_path(source, file=True)
    out_root = _private_output(out_root)
    if source.parent == out_root or source == out_root:
        raise DatasetRejected("Source must not be overwritten.")
    records, original_hash = _read_input(source)
    # Deterministic order independent of input file order.
    records.sort(key=lambda row: _digest((seed + _digest(_json(row))).encode("ascii")))
    count_eval = max(2, min(len(records) - 2, math.ceil(len(records) * 0.2)))
    evaluation, training = records[:count_eval], records[count_eval:]
    out_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    run = out_root / ("run_" + label + "_" + uuid.uuid4().hex)
    run.mkdir(mode=0o700, exist_ok=False)
    train_bytes, evaluation_bytes = _lines(training), _lines(evaluation)
    _create_private(run / "train.jsonl", train_bytes)
    _create_private(run / "heldout.jsonl", evaluation_bytes)
    manifest = {
        "schema": 1, "approved_for_automatic_training": False,
        "dataset_status": "owner_supplied_review_claim_unverified",
        "training_applied": False, "model_changed": False,
        "seed_sha256": _digest(seed.encode("ascii")),
        "source_sha256": original_hash,
        "train_sha256": _digest(train_bytes), "heldout_sha256": _digest(evaluation_bytes),
        "train_count": len(training), "heldout_count": len(evaluation),
        "privacy": "local_only_no_public_artifacts",
    }
    _create_private(run / "manifest.json", _json(manifest) + b"\n")
    return run


def verify(run: Path) -> dict:
    """Verify both prepared files and recheck the consent-free message schema."""
    run = _safe_path(run)
    if not run.is_dir():
        raise DatasetRejected("Missing local prepared dataset directory.")
    manifest_path = _safe_path(run / "manifest.json", file=True)
    if manifest_path.stat().st_size > 8192:
        raise DatasetRejected("Invalid manifest size.")
    try:
        meta = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise DatasetRejected("Invalid manifest.") from exc
    if meta.get("schema") != 1 or meta.get("training_applied") is not False:
        raise DatasetRejected("Unexpected manifest schema or training state.")
    all_fingerprints = set()
    for name, prefix in (("train.jsonl", "train"), ("heldout.jsonl", "heldout")):
        path = _safe_path(run / name, file=True)
        if path.stat().st_size > MAX_SOURCE_BYTES or _digest(path.read_bytes()) != meta.get(prefix + "_sha256"):
            raise DatasetRejected("Prepared dataset changed since review.")
        rows = path.read_text(encoding="utf-8").splitlines()
        if len(rows) != meta.get(prefix + "_count") or len(rows) < 2:
            raise DatasetRejected("Invalid train/holdout counts.")
        for line in rows:
            try:
                row = json.loads(line)
                if set(row) != {"messages"}:
                    raise DatasetRejected("Unexpected prepared example metadata.")
                restored = validate_example({
                    "reviewed": True, "consent": True,
                    "source": "synthetic", "messages": row["messages"],
                })
            except (ValueError, TypeError) as exc:
                raise DatasetRejected("Prepared record failed validation.") from exc
            fingerprint = _digest(_json(restored))
            if fingerprint in all_fingerprints:
                raise DatasetRejected("Train/holdout duplicate detected.")
            all_fingerprints.add(fingerprint)
    return meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare", help="Validate and split an explicitly selected private local JSONL dataset.")
    prep.add_argument("--input", required=True, type=Path)
    prep.add_argument("--output-dir", type=Path, default=_DEFAULT_OUTPUT)
    prep.add_argument("--label", default="pilot")
    prep.add_argument("--seed", default="xemai-training-pilot-v1")
    prep.add_argument("--reviewed-and-consented", action="store_true")
    check = commands.add_parser("verify", help="Read-only integrity check without printing examples.")
    check.add_argument("--run", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            if not args.reviewed_and_consented:
                raise DatasetRejected("Review examples and provide explicit consent flag before preparation.")
            run = prepare(args.input, args.output_dir, seed=args.seed, label=args.label)
            print("Prepared locally (NOT trained):", run)
            print("Train/holdout integrity: OK; content was not printed.")
        else:
            meta = verify(args.run)
            print("Prepared dataset verified; train:", meta["train_count"], "holdout:", meta["heldout_count"])
            print("Model weights changed: NO.")
        return 0
    except (DatasetRejected, OSError, UnicodeError) as exc:
        print("Preparation stopped safely:", exc.__class__.__name__)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
