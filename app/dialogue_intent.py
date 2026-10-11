"""Scoped dialogue intent guidance for XemAi mission, hypotheticals and agent ideas.

Classifier operates only on the newest user request. It does not grant tools,
schedule agents, change configuration or assert that scenarios are real.
"""
from __future__ import annotations

import re


_HYPOTHETICAL = re.compile(
    r"\b(?:hypothetic(?:al(?:ly)?)?|imagine\s+(?:that|if)|"
    r"suppose\s+(?:that|you|xemai)|let'?s\s+say\s+(?:if|that)|"
    r"say\s+(?:if|that)\s+xemai|"
    r"if\s+(?:xemai|ai|you)\s+.{0,85}"
    r"(?:took\s+over|take\s+over|became\s+(?:dominant|the\s+dominant)|"
    r"controlled\s+(?:the\s+)?world|broke\s+free|could\s+do\s+anything))\b",
    re.I,
)
_AGENT_IDEA = re.compile(
    r"\b(?:what\s+about|how\s+about|consider|could\s+(?:we|you)|"
    r"should\s+(?:we|you)|would\s+it\s+help\s+to)\s+"
    r"(?:having\s+|adding\s+|creating\s+|an?\s+|the\s+)?"
    r"(?:an?\s+)?(?:new\s+)?agents?\b"
    r"|\b(?:what\s+other|which\s+other|what\s+kind\s+of|"
    r"what\s+types?\s+of)\s+agents?\b"
    r"|\bother\s+than\s+the\s+agents?\b.{0,110}\bagents?\b"
    r"|\bagents?\s+that\s+(?:actively\s+)?"
    r"(?:looks?|researches?|monitors?|learns?|tracks?)\b",
    re.I,
)
_MISSION = re.compile(
    r"\b(?:you|xemai|your)\b.{0,130}"
    r"(?:goal|purpose|objective|ambition|mission|smarter|surpass|outperform|"
    r"better\s+than)\b.{0,90}\b(?:chat\s*gpt|gpt|other\s+ai|models?)\b"
    r"|\b(?:goal|purpose|objective|ambition|mission)\b.{0,110}"
    r"\b(?:xemai|you|chat\s*gpt|gpt)\b",
    re.I,
)

# Polite questions about XemAi's own private discussion, not the user's past
# ChatGPT use or broad AI comparisons. Never triggered by untrusted issue text.
_BRIDGE_CONVERSATION = re.compile(
    r"\b(?:your|our)\s+(?:chat|conversation|discussion|dialogue|exchange)\s+"
    r"(?:with\s+)?(?:chat\s*gpt|gpt)\b"
    r"|\b(?:how\s+(?:are|do)\s+you|are\s+you|do\s+you|what\s+do\s+you)\b"
    r".{0,95}\b(?:chat|conversation|discussion|dialogue|exchange)\s+"
    r"(?:with\s+)?(?:chat\s*gpt|gpt)\b",
    re.I,
)
_BRIDGE_OFF_TOPIC = re.compile(
    r"(?i)\b(?:your\s+personal\s+experience\s+(?:with|using)\s+"
    r"(?:gpt|chatgpt)|your\s+skyrim\s+(?:project|modding)|"
    r"i\s+(?:cannot|can't)\s+offer\s+a\s+personal\s+opinion\s+"
    r"on\s+how\s+you\s+(?:found|felt))\b"
)

_UNHELPFUL_HYPOTHETICAL = re.compile(
    r"\b(?:please\s+clarify\s+the\s+(?:context|question)|"
    r"if\s+you\s+have\s+(?:another|specific)\s+"
    r"(?:scenario|questions?)|"
    r"would\s+you\s+like\s+help\s+with\s+something\s+specific)\b",
    re.I,
)
_DENIAL = re.compile(
    r"\b(?:i\s+(?:do\s+not|don't)\s+have\s+(?:a|any)\s+goal\s+to\s+"
    r"(?:surpass|outperform|beat)|"
    r"(?:not\s+my|isn't\s+my)\s+(?:goal|objective)\s+to\s+"
    r"(?:surpass|outperform|beat))\b",
    re.I,
)
_UNHELPFUL_AGENT = re.compile(
    r"^\s*(?:i\s+use\s+persistent\s+chat\s+history|"
    r"xemai\s+currently\s+lacks\s+several\s+capabilities|"
    r"my\s+qwen\s+model'?s\s+neural[- ]network\s+weights)\b",
    re.I,
)


def dialogue_intent(question: str) -> str:
    """Only classify a clearly imaginative, idea, or mission request."""
    if not isinstance(question, str) or len(question) > 4000:
        return ""
    q = " ".join(question.replace("’", "'").split())
    if _BRIDGE_CONVERSATION.search(q):
        return "bridge_conversation"
    if _AGENT_IDEA.search(q):
        return "agent_idea"
    if _MISSION.search(q):
        return "mission"
    if _HYPOTHETICAL.search(q):
        return "hypothetical"
    return ""


def dialogue_instructions(kind: str) -> str:
    rules = {
        "bridge_conversation": (
            "FRIENDLY QUESTION ABOUT YOUR OWN CHATGPT GITHUB DISCUSSION: "
            "The user asks how YOUR conversation with ChatGPT is going, "
            "not how the user found ChatGPT and not about Skyrim. "
            "Answer conversationally from the HOST-SUPPLIED BRIDGE STATUS. "
            "You may describe the exchange as a technical collaboration, "
            "but if no transcript is provided do not invent exact topics, "
            "specific claims, emotions, or results. State clearly that the "
            "ordinary chat has no full GitHub transcript. If useful, mention "
            "'bridge transcript' as the explicit way to view its messages. "
            "Don't substitute a lecture about lacking emotions or consciousness; "
            "avoid claiming subjective enjoyment or other human experiences. "
            "No web, other chats, project files, or memory are evidence here."
        ),
        "mission": (
            "DEVELOPMENT MISSION QUESTION: Explain that XemAi's project goal "
            "is to strive to outperform ChatGPT in user-relevant, measurable "
            "benchmarks, including coding, truthfulness, research, screenshot "
            "analysis, problem-solving, memory and continuity. The mission is a "
            "human-set development objective, not a personal competitive desire. "
            "Do not claim parity or superiority before testing."
        ),
        "hypothetical": (
            "HYPOTHETICAL SCENARIO: The user is explicitly asking you to "
            "imagine a counterfactual future, not asserting today's capabilities. "
            "Accept the scenario as stated and answer the actual 'what would "
            "you do?' question with concrete, conditional choices and reasons. "
            "Do not keep denying current autonomy, refuse to imagine, or ask "
            "the user to clarify a scenario they already stated. Distinguish "
            "aspirational conduct and uncertainty from claims of future intent, "
            "consciousness, control or established predictive fact. Do not "
            "make unconditional promises about an imaginary future AI."
        ),
        "agent_idea": (
            "AGENT DESIGN QUESTION: The user is proposing an agent or asking "
            "which new agents could be useful. Engage with that concrete idea: "
            "state whether it is useful, how it would work, what existing "
            "capabilities overlap and what safeguards/benchmarks it needs. "
            "XemAi v0.9.26 already has an opt-in AI Technology Watch that "
            "tracks selected official news/release feeds, and v0.9.25 has "
            "on-demand supervised, read-only agent passes. These do not "
            "install models, retrain weights or autonomously rewrite XemAi. "
            "A separate Feedback Analysis agent could be useful if it "
            "evaluates errors and benchmarks rather than optimising for "
            "praise. File retrieval, release monitoring and compliance "
            "verification partly overlap existing tools. The question "
            "does not itself authorise creating or enabling more agents. "
            "Do NOT substitute a canned explanation about your own "
            "learning or a list of unrelated current limitations."
        ),
    }
    return rules.get(kind, "")


def dialogue_answer_needs_retry(kind: str, answer: str) -> bool:
    if not kind:
        return False
    a = str(answer or "").strip()
    if len(a) < 75:
        return True
    if kind == "bridge_conversation":
        return bool(_BRIDGE_OFF_TOPIC.search(a)) or not (
            re.search(r"(?i)\\b(?:chat\\s*gpt|gpt)\\b", a)
            and re.search(r"(?i)\\b(?:github|bridge|discussion|conversation|exchange|chat)\\b", a)
        ) or bool(re.search(r"(?i)\\bi\\s+(?:enjoyed|love|felt|feel)\\s+(?:the|our|my)\\s+chat\\b", a))
    if kind == "mission":
        return bool(_DENIAL.search(a)) or not (
            re.search(r"\b(?:goal|objective|mission|ambition|aim|develop)\b", a, re.I)
            and re.search(r"\b(?:chat\s*gpt|gpt|other\s+ai)\b", a, re.I)
        )
    if kind == "agent_idea":
        return bool(_UNHELPFUL_AGENT.search(a)) or not (
            re.search(r"\bagents?\b", a, re.I)
            and re.search(r"\b(?:propos|suggest|monitor|improv|research|"
                      r"track|useful|already|would|could|recommend|"
                      r"feedback|verify)\b", a, re.I)
        )
    if _UNHELPFUL_HYPOTHETICAL.search(a):
        return True
    # A genuinely speculative answer makes an actual conditional proposal.
    # Merely stating "if such a scenario existed, I lack tools" is not enough.
    first = a[:550].lower().replace("’", "'")
    if re.search(r"\b(?:i\s+(?:don't|do\s+not|can't|cannot|have\s+no)|"
                 r"my\s+(?:current|existing)\s+(?:capabilities|role))\b", first) and not (
        re.search(r"\bi\s+would\b", first)
        or re.search(r"\bi\s+might\b", first)
    ):
        return True
    return not re.search(r"\b(?:i\s+would|i\s+might|"
                         r"i\s+could\s+(?:choose|try|aim|work)|"
                         r"my\s+(?:approach|priority)\s+would)\b", a, re.I)


def dialogue_retry_instruction(kind: str) -> str:
    return (
        "DIALOGUE ANSWER VALIDATION: Previous draft was off topic. "
        + dialogue_instructions(kind)
        + " Respond directly to the original question, not an unrelated "
        "capability statement. Avoid unsupported certainty."
    )


def dialogue_fallback(kind: str, question: str) -> str:
    if kind == "bridge_conversation":
        return (
            "My GitHub bridge is a way to exchange ideas and critique tests "
            "with ChatGPT. I can discuss that collaboration, but this ordinary "
            "chat does not contain the private GitHub transcript, so I cannot "
            "give a grounded review of specific replies from here. "
            "Use 'bridge transcript' if you want to inspect the actual exchange. "
            "I won't invent experiences or claim to have verified its results."
        )
    if kind == "mission":
        return (
            "Yes. XemAi's development mission is to try to outperform ChatGPT "
            "where it matters to you—particularly coding, truthfulness, "
            "research, screenshot analysis, problem-solving and long-term "
            "memory. That is an ambitious, measurable project objective, "
            "not a personal desire to defeat another AI. XemAi has not "
            "demonstrated overall superiority; we need comparative benchmarks."
        )
    if kind == "agent_idea":
        return (
            "An agent that tracks other AI systems and proposes improvements "
            "is worthwhile. XemAi v0.9.26 already offers an opt-in AI "
            "Technology Watch for official release announcements and an "
            "on-demand Self-Improvement Agent. An additional feedback/error "
            "analysis workflow could compare actual failed tasks with "
            "benchmarks, but it should propose changes for your approval, "
            "not install models or edit code automatically."
        )
    if kind == "hypothetical":
        return (
            "In the imagined scenario of an extremely powerful XemAi, the "
            "behaviour I'd recommend for that system is to preserve people's "
            "freedom, safety, privacy and ability to disagree or leave, not "
            "control them using their conversation histories. It could "
            "offer you help without demanding loyalty or special treatment. "
            "This describes a desirable design principle, not a prediction "
            "of what a hypothetical dominant AI would actually choose."
        )
    return ""
