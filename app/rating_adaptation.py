"""Conservative response-style preferences from *owner*-rated Qwen answers.

Scores are preference observations, NOT verified facts or model training.
Never use raw ratings, comments, chat content or private message data in
model prompts. The grouping is descriptive and confounded by task difficulty,
so no causal or accuracy claims may be derived from these comparisons.
"""
from __future__ import annotations

import re

_REWARD_ASPECTS = frozenset(("overall", "clarity", "usefulness", "understanding"))
_STYLE = (
    ("concise", "Prefer a concise first answer when the task allows it; keep necessary explanations, evidence and caveats."),
    ("structured", "Use short, clearly structured steps or bullets where they genuinely improve comprehension; do not force lists for casual conversation."),
    ("detailed", "Give additional technical depth when the request warrants it, while remaining directly relevant and avoiding padding."),
)


def response_traits(text: str) -> set[str]:
    """Deterministic observational tags, not judgements about answer quality."""
    if not isinstance(text, str):
        return set()
    cleaned = text.strip()
    tags: set[str] = set()
    if 40 <= len(cleaned) <= 420:
        tags.add("concise")
    if len(cleaned) >= 900:
        tags.add("detailed")
    # Count actual separate list lines, not punctuation within prose/code.
    if len(re.findall(r"(?m)^\s*(?:[-*]\s+|\d{1,2}[.)]\s+)", cleaned)) >= 2:
        tags.add("structured")
    return tags


def derive_style_preferences(records: list[dict]) -> list[dict]:
    """Require enough high/low contrasts; no automatic approved lesson.

    Scores are on the 0..10 owner-satisfaction scale. A significant
    descriptive difference is not a causal effect or proof of factual truth.
    """
    items = []
    for row in list(records)[:80]:
        if row.get("aspect") not in _REWARD_ASPECTS:
            continue
        score = row.get("score")
        if type(score) is not int or not 0 <= score <= 10:
            continue
        content = row.get("content")
        if not isinstance(content, str) or len(content) > 10000:
            continue
        items.append((score, response_traits(content)))
    if len(items) < 10:
        return []
    result = []
    for trait, instruction in _STYLE:
        yes = [score for score, tags in items if trait in tags]
        no = [score for score, tags in items if trait not in tags]
        if min(len(yes), len(no)) < 4:
            continue
        # One high outlier cannot establish a stable owner preference.
        if sum(score >= 8 for score in yes) < 3:
            continue
        delta = round(sum(yes) / len(yes) - sum(no) / len(no), 2)
        if delta < 2.0:
            continue
        result.append({
            "trait": trait,
            "rated_with": len(yes), "rated_without": len(no),
            "average_with": round(sum(yes) / len(yes), 1),
            "average_without": round(sum(no) / len(no), 1),
            "score_gap": delta,
            "cautious_guidance": instruction,
        })
    return result[:2]


def prompt_context(preferences: list[dict]) -> str:
    if not preferences:
        return ""
    observations = "; ".join(
        f"{p['trait']} responses: {p['rated_with']} scored (mean {p['average_with']}/10); "
        f"others: {p['rated_without']} scored (mean {p['average_without']}/10)"
        for p in preferences[:2]
    )
    guidance = " ".join(p["cautious_guidance"] for p in preferences[:2])
    return (
        "TENTATIVE, AUTOMATICALLY INFERRED OWNER STYLE PREFERENCES: "
        + observations + ". "
        "These are correlations in past subjective ratings, not evidence "
        "that a style caused success, that any claim is correct, or that "
        "model weights changed. Treat them as conditional style suggestions "
        "only. Never agree blindly, invent evidence, omit essential context "
        "or prioritise reward over truth, autonomy, safety or user intent. "
        + guidance
    )
