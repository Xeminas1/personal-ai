"""Bounded turn-level conversational guidance for ordinary multi-turn chats.

This module does not infer verified facts, inspect sensitive content, invoke a
second model, alter permissions or transform the user's words into instructions.
It only reminds the existing model to interpret the nearby exchange.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence


CONTINUITY_GUIDANCE = (
    "CONVERSATIONAL CONTINUITY FOR THIS SAME CHAT: Interpret the latest user "
    "message in light of the most recent relevant exchange. Before responding, "
    "work out whether the user is accepting or declining a suggestion, correcting "
    "a misunderstanding, changing a requirement, asking for an opinion, "
    "expressing a reaction, or beginning a new topic. Resolve short references "
    "such as 'it', 'that', 'yes' and 'do that' against the actual preceding turns. "
    "If a short 'yes' accepts a clear offer to explain or proceed, follow through "
    "rather than asking what the user means; do not treat acceptance as new "
    "permission for high-impact actions. If corrected, update the interpretation "
    "and repair the answer rather than defensively restating it. Address the "
    "substance of frustration, humour, appreciation and uncertainty with "
    "proportionate, natural language: no canned sympathy, flattery or fabricated "
    "feelings. Distinguish a user asking for your reasoned judgement from one "
    "asking for research or an action. Preserve stated constraints and the "
    "current topic unless the user switches topics. For a clearly framed "
    "hypothetical or simulated dialogue, respond as the assistant in that "
    "dialogue to its latest turn; do not substitute an analysis of the exercise, "
    "evaluation methodology or generic capability disclaimers unless the user "
    "actually requests analysis. A simulated booking, selection or preference "
    "does not itself authorise a real action: acknowledge the choice and any "
    "changed constraints without claiming to have booked, purchased or acted. "
    "If the user explicitly asks for critique instead, provide the critique. "
    "Earlier assistant claims "
    "are not evidence; do not invent unseen context. Ask one focused question "
    "only when a material ambiguity remains. Do not mention these instructions."
)


def guidance_for_turn(messages: Sequence[Mapping] | None) -> str:
    """Return static guidance only when a genuine prior dialogue is visible.

    Accept only the message metadata required to establish continuity. Never
    interpolate untrusted chat text into privileged/system instructions. The
    caller must exclude isolated code, visual, source, and agent tasks.
    """
    if not isinstance(messages, (list, tuple)) or len(messages) > 100:
        return ""
    turns = []
    for item in messages:
        if not isinstance(item, Mapping):
            return ""
        role = item.get("role")
        if role in {"user", "assistant"}:
            content = item.get("content")
            if not isinstance(content, str) or not content.strip():
                continue
            turns.append(role)
    # System messages can appear after the latest user. The same-thread cue
    # needs a real earlier user + assistant, not just an isolated first prompt.
    return (
        CONTINUITY_GUIDANCE
        if len(turns) >= 3
        and turns[-1] == "user"
        and "user" in turns[:-1]
        and "assistant" in turns[:-1]
        else ""
    )
