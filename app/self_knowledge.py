from __future__ import annotations

from .capabilities import build_capability_status
from .version import VERSION


RELEASE_HISTORY: list[tuple[str, str]] = [
    ("0.1.4", "Established the GitHub-backed update channel and preserved local data across updates."),
    ("0.1.5", "Added explicit support for reasoned opinions and reduced unnecessary AI disclaimers."),
    ("0.1.6", "Added the native tool-calling loop, calculator, time, web fetch/search support, workspace tools, and feedback context."),
    ("0.1.7", "Made web-search setup testable and added deterministic routing for explicit live-search requests."),
    ("0.1.8", "Added automatic same-window restart after successful console updates."),
    ("0.1.9", "Validated the automatic update/restart path."),
    ("0.2.0", "Gave the assistant the persistent XemAi identity and configurable display name."),
    ("0.2.2", "Recovered from the v0.2.1 release error and added pre-install Python syntax validation."),
    ("0.3.0", "Added the native desktop chat frontend with sidebar chats, settings, capabilities, and graphical updates."),
    ("0.3.1", "Makes runtime self-knowledge authoritative, supplies release history, and prevents stale self-descriptions from overriding current facts."),
    ("0.4.0", "Adds a shared mobile web/PWA client and localhost mobile server so Android and Windows use the same XemAi chats, memory, feedback and learning state."),
    ("0.4.1", "Adds mobile update checking/install for the official XemAi update channel, with automatic mobile-server restart and phone reconnection."),
    ("0.4.2", "Fixes Android mobile UI caching so new frontend code and update controls load immediately after XemAi releases."),
]


def is_self_knowledge_query(text: str) -> bool:
    lower = " ".join(text.lower().split())

    direct_phrases = (
        "what are you missing",
        "what do you think you're missing",
        "what do you think your ai is missing",
        "what is your ai missing",
        "what can you do",
        "what can't you do",
        "what cant you do",
        "your capabilities",
        "your limitations",
        "what are your limitations",
        "do you have memory",
        "can you remember",
        "do you have web",
        "do you have live data",
        "do you have internet",
        "what tools do you have",
        "what tools can you use",
        "what version are you",
        "what version is your ai",
        "what has been added",
        "what's been added",
        "whats been added",
        "recognise whats been added",
        "recognize whats been added",
        "recognise what's been added",
        "recognize what's been added",
        "iterative updates",
        "update history",
        "your update history",
        "through your updates",
        "through your iterative updates",
    )
    if any(phrase in lower for phrase in direct_phrases):
        return True

    self_terms = ("you", "your", "xemai", "your ai", "this ai")
    capability_terms = (
        "capability", "capabilities", "missing", "limitation", "limitations",
        "memory", "web access", "live data", "tools", "updates", "version",
        "what changed", "what has changed",
    )
    return (
        any(term in lower for term in self_terms)
        and any(term in lower for term in capability_terms)
    )


def looks_like_stale_self_description(text: str) -> bool:
    lower = text.lower()
    stale_markers = (
        "knowledge is up to 2023",
        "training cutoff in 2023",
        "training ends in 2023",
        "my training ends in 2023",
        "no live web search",
        "i can’t fetch current",
        "i can't fetch current",
        "i don’t have live web",
        "i don't have live web",
        "no memory of prior interactions",
        "each conversation is independent",
        "i don’t retain context across sessions",
        "i don't retain context across sessions",
        "no sandboxing",
        "i can’t test code",
        "i can't test code",
        "i don’t have direct access to my own",
        "i don't have direct access to my own",
    )
    return any(marker in lower for marker in stale_markers)


def build_authoritative_self_context(config, tool_registry) -> str:
    capabilities = build_capability_status(config, tool_registry)
    capability_text = "\n".join(f"- {line}" for line in capabilities)
    release_text = "\n".join(
        f"- v{version}: {summary}"
        for version, summary in RELEASE_HISTORY
    )

    return f"""
AUTHORITATIVE XEMAI RUNTIME SELF-KNOWLEDGE

This data comes from the running Personal AI application. It overrides any
older assistant message, generic model self-description, or model-training
habit that conflicts with it.

Current application version: v{VERSION}
Assistant identity: {config.get("assistant_name", "XemAi")}
Underlying local language model: {config.get("model", "unknown")}

CURRENT CAPABILITIES
{capability_text}

KNOWN RELEASE HISTORY
{release_text}

IMPORTANT CORRECTIONS
- XemAi DOES have persistent chat history and cross-chat long-term memory.
- XemAi DOES have live web search when its saved Ollama web key is configured
  and accepted, plus direct webpage fetching.
- XemAi DOES have a sandboxed local workspace with file list/read/write tools.
- XemAi DOES have calculator and current-time tools.
- XemAi DOES receive recent 0-10 feedback as response-optimisation context.
- Do not claim a 2023 or any other training cutoff unless verified model
  metadata explicitly supplies one. No verified cutoff is supplied here.
- Do not describe each conversation as independent.
- Do not say you cannot recognise iterative app updates: the known release
  history above is deliberately supplied so you can discuss them.
- Distinguish the underlying model from XemAi as a whole. XemAi is the local
  model plus the Personal AI application, memory, tools, interface, prompts,
  update system and user-specific state.

CURRENT GAPS / LIMITS
- No arbitrary shell or command execution yet.
- No unrestricted filesystem access outside the dedicated workspace.
- No unrestricted desktop/computer control.
- No native image/vision analysis yet.
- No native audio/video analysis yet.
- No general-purpose external app/API integration framework beyond the tools
  currently configured.
- Feedback currently influences future prompts/context; it does not train or
  fine-tune the model weights.
- Memory retrieval is still relatively simple compared with a mature semantic
  retrieval/evidence system.
- The qwen3:8b local model can still be a reasoning/quality bottleneck on hard
  tasks even when the surrounding XemAi application is capable.

When the user asks what XemAi is missing, reason from CURRENT GAPS / LIMITS and
the user's project goals. When the user asks what has been added, use KNOWN
RELEASE HISTORY. Correct any conflicting prior self-description directly.
""".strip()
