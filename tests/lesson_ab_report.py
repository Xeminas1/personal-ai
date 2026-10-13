"""Aggregate *manually graded* local XemAi lesson A/B benchmark results.

Input: JSON from conversation_learning_benchmark.py --run, with owner-filled
0/1 rubric fields. Never publishes model answers or private conversation data.
This tool neither grades automatically nor establishes a causal learning effect.
"""
from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from pathlib import Path

SCORE_KEYS = ("owner_score_intent_0_or_1", "owner_score_evidence_0_or_1")
CONDITIONS = frozenset(("baseline", "with_lessons"))
LIMIT_BYTES = 6_000_000


def _score(row: dict, key: str) -> int | None:
    value = row.get(key)
    if value is None:
        return None
    if type(value) is not int or value not in (0, 1):
        raise ValueError(f"{key} must be 0, 1 or null (manual grading)")
    return value


def analyse(document: dict) -> dict:
    """Return only aggregate score counts; never echo input questions/answers."""
    if not isinstance(document, dict) or not isinstance(document.get("results"), list):
        raise ValueError("Expected benchmark JSON with a results list")
    rows = document["results"]
    if not rows or len(rows) > 2000 or len(rows) % 2:
        raise ValueError("Expected a nonempty, even number of paired rows")
    if type(document.get("samples")) is not int or document["samples"] != len(rows) // 2:
        raise ValueError("Benchmark samples must match the number of pairs")

    pairs: dict[int, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        if not isinstance(row, dict) or type(row.get("case")) is not int or row["case"] < 1:
            raise ValueError("Each row needs a positive integer case number")
        case, condition = row["case"], row.get("condition")
        if condition not in CONDITIONS or condition in pairs[case]:
            raise ValueError("Duplicate or unknown A/B condition")
        if type(row.get("lesson_present")) is not bool:
            raise ValueError("Each row requires a boolean lesson_present flag")
        if condition == "baseline" and row["lesson_present"]:
            raise ValueError("Baseline cannot contain lesson context")
        for key in SCORE_KEYS:
            _score(row, key)
        pairs[case][condition] = row

    if set(pairs) != set(range(1, document["samples"] + 1)):
        raise ValueError("Cases must be complete and sequential")
    sums = {condition: {key: 0 for key in SCORE_KEYS} for condition in CONDITIONS}
    eligible = pending = without_lessons = 0
    for pair in pairs.values():
        if set(pair) != CONDITIONS:
            raise ValueError("Each case must have baseline and with_lessons")
        baseline, candidate = pair["baseline"], pair["with_lessons"]
        for key in ("question", "category", "model", "compute"):
            if baseline.get(key) != candidate.get(key):
                raise ValueError(f"A/B pair differs in {key}; not comparable")
        if not candidate["lesson_present"]:
            without_lessons += 1
            continue
        eligible += 1
        values = [_score(row, key) for row in (baseline, candidate) for key in SCORE_KEYS]
        if any(value is None for value in values):
            pending += 1
            continue
        for key in SCORE_KEYS:
            sums["baseline"][key] += baseline[key]
            sums["with_lessons"][key] += candidate[key]

    scored = eligible - pending
    metrics = {}
    for key in SCORE_KEYS:
        b, w = sums["baseline"][key], sums["with_lessons"][key]
        metrics[key.removeprefix("owner_score_").removesuffix("_0_or_1")] = {
            "baseline_correct": b,
            "with_lessons_correct": w,
            "paired_cases_scored": scored,
            "delta_correct": w - b,
            "delta_rate": round((w - b) / scored, 4) if scored else None,
        }
    return {
        "purpose": "Descriptive, owner-scored paired comparison; not proof of learning or causal benefit",
        "total_pairs": len(pairs),
        "pairs_with_lesson_context": eligible,
        "pairs_without_lesson_context": without_lessons,
        "paired_cases_scored": scored,
        "pairs_awaiting_manual_scores": pending,
        "metrics": metrics,
        "interpretation": (
            "Counts reflect only paired, same-route cases with approved lesson "
            "context inserted and both answers manually graded. No evidence "
            "of model weight changes, independent holdouts or causal impact."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Local private benchmark JSON")
    parser.add_argument("--output", type=Path, help="Optional private summary JSON; never overwrites")
    args = parser.parse_args()
    if args.input.stat().st_size > LIMIT_BYTES:
        parser.error("Input exceeds 6 MB safety limit")
    report = analyse(json.loads(args.input.read_text(encoding="utf-8")))
    formatted = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.output is None:
        print(formatted, end="")
    else:
        if args.input.resolve() == args.output.resolve():
            parser.error("Output cannot replace the original benchmark")
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(formatted)
        try:
            os.chmod(args.output, 0o600)
        except OSError:
            pass
        print("Saved local aggregate report (no model answers included).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
