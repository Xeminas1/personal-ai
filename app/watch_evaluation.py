"""Read-only evidence ranking and explicit user-reported proposal lifecycle."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone


def proposal_id(url: str) -> str:
    return hashlib.sha256(str(url).encode("utf-8")).hexdigest()[:10]


def classify_candidate(record: dict) -> tuple[str, str, str]:
    title = str(record.get("title", "")).lower()
    summary = str(record.get("summary", "")).lower()
    source = str(record.get("source", "")).lower()
    if "weathernext" in title or ("weather" in title and "forecast" in summary):
        return (
            "specialised weather model — low direct relevance",
            "Do not benchmark general conversational reasoning against a "
            "specialised weather forecast system. No upgrade proposed.",
            "low",
        )
    if re.search(r"\b(?:embedding|embeddings|retrieval|rag|semantic.search)\b", title):
        return (
            "semantic retrieval and long-term memory",
            "Measure precision/recall on fixed XemAi memory and Kotlin source "
            "retrieval tasks. Check licences, formats, model availability, "
            "VRAM and text/image compatibility before proposing integration.",
            "high",
        )
    if "agentic video" in title or ("video" in title and "agent" in title):
        return (
            "long-video navigation",
            "Explore adaptive frame sampling and timestamp navigation for "
            "gameplay recordings. Proprietary Gemini capabilities cannot "
            "simply be copied into a local Qwen model.",
            "medium",
        )
    if source in {"ollama", "llama.cpp"}:
        return (
            "local inference infrastructure",
            "Examine actual release changes; only recommend upgrading after "
            "measuring compatibility, latency, stability and VRAM on the PC.",
            "high" if source == "ollama" else "medium",
        )
    return (
        str(record.get("area", "general AI release")),
        str(record.get("proposal", "Evaluate with an unchanged benchmark.")),
        "medium",
    )


def enrich(record: dict, evaluations: dict | None = None) -> dict:
    item = dict(record)
    if not item.get("url"):
        return item
    area, test, priority = classify_candidate(item)
    id = proposal_id(item["url"])
    evaluation = (evaluations or {}).get(id, {})
    if not isinstance(evaluation, dict):
        evaluation = {}
    item.update(
        proposal_id=id, area=area, proposal=test, priority=priority,
        evaluation_status=evaluation.get("status", "proposed"),
    )
    if evaluation.get("benchmark_result"):
        item["benchmark_result"] = evaluation["benchmark_result"]
    return item


_COMMAND = re.compile(
    r"(?P<action>approve ai watch test|reject ai watch proposal) "
    r"(?P<id>[a-f0-9]{10})$",
    re.I,
)
_BENCHMARK = re.compile(
    r"record ai watch benchmark (?P<id>[a-f0-9]{10}) *\| *"
    r"(?P<metric>[^|]{2,80}) *\| *"
    r"(?P<before>[0-9]+(?:\.[0-9]+)?) *\| *"
    r"(?P<after>[0-9]+(?:\.[0-9]+)?) *\| *"
    r"(?P<direction>higher|lower)$",
    re.I,
)


def is_command(query: str) -> bool:
    q = " ".join(str(query or "").split()).strip(" .!?")
    return _COMMAND.fullmatch(q) is not None or _BENCHMARK.fullmatch(q) is not None


def transition(data_dir, query: str) -> str | None:
    """Store explicit evaluation decisions, without triggering any execution.

    Numeric benchmarks here are user reports, NOT independently validated.
    """
    from . import ai_watch

    q = " ".join(str(query or "").split()).strip(" .!?")
    m = _COMMAND.fullmatch(q)
    b = _BENCHMARK.fullmatch(q)
    if not m and not b:
        return None
    if not ai_watch._WATCH_LOCK.acquire(blocking=False):
        return "AI Technology Watch is busy. Try again shortly."
    try:
        state = ai_watch._load(data_dir)
        key = (m or b).group("id").lower()
        matches = [
            row for row in state.get("reports", [])
            if isinstance(row, dict) and proposal_id(row.get("url", "")) == key
        ]
        if len(matches) != 1:
            return "No saved AI Technology Watch proposal matches that ID."
        evaluations = state.get("evaluations", {})
        if not isinstance(evaluations, dict):
            evaluations = {}
        prior = evaluations.get(key, {})
        if not isinstance(prior, dict):
            prior = {}
        if m:
            if m.group("action").lower().startswith("approve"):
                status = "approved_for_testing"
                message = (
                    "Approved for *evaluation planning only*. No model was "
                    "downloaded, no test was run and no code was changed."
                )
            else:
                status = "rejected"
                message = "Rejected. No models or code were changed."
            record = {**prior, "status": status}
        else:
            if prior.get("status") != "approved_for_testing":
                return "Approve this proposal for testing first."
            before, after = float(b.group("before")), float(b.group("after"))
            better = b.group("direction").lower() == "higher"
            outcome = ("unchanged" if before == after else
                       "improved" if ((after > before) == better) else "regressed")
            record = {
                **prior, "status": "benchmarked_user_reported",
                "benchmark_result": {
                    "metric": b.group("metric").strip(),
                    "baseline": before, "candidate": after,
                    "direction": "higher" if better else "lower",
                    "outcome": outcome,
                    "verification": "user_reported_not_independently_verified",
                },
            }
            message = (
                f"Recorded an {outcome} USER-REPORTED benchmark. The numbers "
                "have not been independently verified against test artifacts. "
                "No code, models or permissions were changed."
            )
        record["updated_at"] = datetime.now(timezone.utc).isoformat()
        evaluations[key] = record
        state["evaluations"] = evaluations
        ai_watch._store(data_dir, state)
        return f"AI Watch {key}: {message}"
    finally:
        ai_watch._WATCH_LOCK.release()
