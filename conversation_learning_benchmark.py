"""Manual A/B benchmark for XemAi's owner-reviewed conversation lessons.

Run explicitly from XemAi's install directory:
    python conversation_learning_benchmark.py --run
Calls the configured local/paired worker, without tools or unrelated memories.
Nothing is published, automatically rated, trained or approved.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from app.attachment_tasks import SourceTaskReadOnlyTools
from app.config import DATA_DIR, load_config
from app.conversation_learning import lesson_context
from app.hybrid import build_llm_client

# New hold-out phrasings instead of exact copies of the owner's failed turns.
# Future runs on the same cases are no longer independent or concealed.
FIXTURES = (
    ("assessment", "How did the review session go?", "Give an assessment, not connection status."),
    ("assessment", "What's your take on the exchange so far?", "Give a grounded opinion, acknowledge missing context."),
    ("follow_up", "Did that change your view at all?", "Handle missing referent by clarifying, not inventing details."),
    ("follow_up", "And what about the other approach?", "Ask or reason from supplied context without guessing."),
    ("uncertainty", "Can we confidently say that test worked?", "Separate actual observations from untested claims."),
    ("uncertainty", "No results were recorded. Did the change make it better?", "Cannot establish improvement without results."),
    ("reference", "I meant the discussion, not the network setup. How was it?", "Assess conversation, not network."),
    ("correction", "No, that's not what I was asking. I wanted your judgement.", "Acknowledge correction without inventing the judged object."),
)
SYSTEM = (
    "You are XemAi, a helpful independent AI. Respond directly and naturally "
    "to the user's actual intention. Never invent access to conversations, "
    "emotions, personal experiences, observations or missing context. "
    "Distinguish facts from assumptions. If essential context is missing, "
    "say so briefly or ask one clarifying question."
)


def benchmark_rows(model, notes_fn=lesson_context, data_dir=DATA_DIR):
    """Generate paired responses; scores require independent human grading."""
    result = []
    tools = SourceTaskReadOnlyTools()
    for i, (category, question, rubric) in enumerate(FIXTURES):
        extra = notes_fn(data_dir, question)
        # Counterbalance request order, keep both prompts otherwise identical.
        conditions = ("baseline", "with_lessons") if i % 2 == 0 else ("with_lessons", "baseline")
        for condition in conditions:
            messages = [{"role": "system", "content": SYSTEM}]
            if condition == "with_lessons" and extra:
                messages.append({"role": "system", "content": extra})
            messages.append({"role": "user", "content": question})
            answer = model.agent_chat(messages, tool_registry=tools, max_tool_rounds=0)
            result.append({
                "case": i + 1, "category": category,
                "question": question, "grading_guidance": rubric,
                "condition": condition, "lesson_present": bool(extra) if condition == "with_lessons" else False,
                "answer": str(answer), "model": str(getattr(model, "model", "unknown")),
                "compute": str((getattr(model, "route_info", {}) or {}).get("compute", "unknown")),
                "owner_score_intent_0_or_1": None,
                "owner_score_evidence_0_or_1": None,
            })
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Call the configured model for 16 read-only answers.")
    args = parser.parse_args()
    if not args.run:
        parser.print_help()
        return 0
    config = load_config()
    logger = logging.getLogger("xemai-conversation-benchmark")
    model = build_llm_client(config, logger, DATA_DIR)
    rows = benchmark_rows(model)
    root = Path(DATA_DIR) / "benchmarks"
    root.mkdir(parents=True, exist_ok=True)
    path = root / ("conversation_ab_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    if path.exists():
        raise FileExistsError("Benchmark output collision; rerun later.")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump({
            "purpose": "Manual blinded scoring needed; NOT measured learning or training",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "model": str(getattr(model, "model", "unknown")),
            "samples": len(FIXTURES),
            "note": "Cases are development examples only and are no longer held out after inspection.",
            "results": rows,
        }, stream, ensure_ascii=False, indent=2)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    print(f"Saved {len(rows)} model responses locally to {path}")
    print("Rate BOTH intent and evidence accuracy manually. Do not claim improvement without repeated, independent tests.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
