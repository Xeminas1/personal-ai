"""Conservative conversational-agent routing, not a diagnosis of emotions.

Only ordinary same-thread conversations with an actual preceding exchange are
eligible. Classification doesn't grant actions, remember private data, or
claim that a social interpretation is certainly right.
"""
from __future__ import annotations

import json
import re


_SOCIAL = re.compile(
    r"\b(?:frustrat\w*|annoy\w*|fed up|rubbish day|awful day|"
    r"had a (?:bad|rough|terrible) day|disappoint\w*|exhausted|"
    r"hate (?:this|that)|keeps? crashing|crashed again|"
    r"brilliant.{0,65}(?:crash|fail|error|broken)|"
    r"great.{0,65}(?:crash|fail|error|broken))\b",
    re.I,
)
_FOLLOWUP = re.compile(
    r"^(?:yes\b|yeah\b|yep\b|sure\b|no\b|nope\b|"
    r"actually\b|but\b|wait\b|and (?:what|how|why|if)\b|"
    r"what about\b|how about\b|why (?:would|did|does)\b|"
    r"is that\b|are you sure\b|i meant\b|"
    r"that's not\b|that is not\b|you (?:said|told me)\b|"
    r"the (?:first|second|other) (?:option|one)\b|"
    r"(?:that|this|it|those|they)\b)",
    re.I,
)
_SIMPLE_ACK = re.compile(
    r"^(?:thanks?|thank you|cheers|perfect|brilliant|great|nice|ok(?:ay)?|"
    r"got it|sounds good)[!.\s]*$", re.I,
)


def conversation_role(question: str, history_context: str, *, enabled: bool = True) -> str:
    """Return a specialist role for a meaningful same-chat ambiguity.

    The trigger is intentionally a lower bound, not a claim the model missed
    intent or that the user's emotional state is known.
    """
    if enabled is not True or not isinstance(question, str) or len(question) > 1200:
        return ""
    q = " ".join(question.replace("’", "'").split()).strip()
    if not q or _SIMPLE_ACK.fullmatch(q):
        return ""
    if not isinstance(history_context, str) or len(history_context) > 5000:
        return ""
    try:
        history = json.loads(history_context)
    except (TypeError, ValueError, RecursionError):
        return ""
    if not isinstance(history, list) or len(history) > 12:
        return ""
    roles = [
        item.get("role")
        for item in history
        if isinstance(item, dict) and item.get("role") in {"user", "assistant"}
        and isinstance(item.get("content"), str) and item["content"].strip()
    ]
    if len(roles) < 2 or roles[-1] != "assistant" or "user" not in roles[:-1]:
        return ""
    if _SOCIAL.search(q):
        return "social"
    if _FOLLOWUP.search(q) and len(q) <= 260:
        return "conversation"
    return ""
