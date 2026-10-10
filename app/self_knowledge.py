from __future__ import annotations

import re

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
    ("0.4.3", "Adds version-aware lifecycle management for the background mobile server so desktop updates replace stale server processes instead of leaving old API code in memory."),
    ("0.4.4", "Republishes the mobile-server lifecycle fix through a fully verified immutable release after rejecting a bad v0.4.3 manifest."),
    ("0.4.5", "Publishes the mobile-server lifecycle fix from exact tested source files after rejecting mismatched frozen release content."),
    ("0.5.0", "Redesigns both the Windows desktop app and the mobile app to the new bubble-based dark blue XemAi interface with gradient backgrounds and glassy conversation styling."),
    ("0.5.1", "Fixes the Windows desktop startup crash caused by timezone-aware chat timestamps in the redesigned recent-chats sidebar and adds startup crash logging."),
    ("0.5.2", "Refines the visual redesign with a themed mobile header, corrected bottom-up blue glow, and improved Windows desktop layout, composer, sidebar, and scrollbars."),
    ("0.6.0", "Unifies Windows and Android on one responsive HTML/CSS frontend; Windows launches the same XemAi interface in Edge app mode while the legacy Tkinter frontend remains available as a fallback."),
    ("0.6.1", "Refines the mobile XemAi interface with a cleaner fixed header, smaller chat typography, tighter bubbles/composer spacing, and a stronger bottom-up blue glow while preserving the unified desktop/mobile frontend."),
    ("0.6.2", "Refines XemAi branding so the shared desktop/mobile wordmark renders Xem in white and Ai in the interface accent blue."),
    ("0.6.3", "Strengthens XemAi identity and AI-comparison reliability: ChatGPT/AI opinion questions receive authoritative runtime context and stale generic model self-descriptions are rejected before being saved."),
    ("0.6.4", "Tightens AI-comparison quality: catches comparison-avoidance wording, unsupported superiority claims, oversimplifying ChatGPT as a standalone model, and opinion answers that never state a direct position."),
    ("0.6.5", "Adds a persistent mobile version label and makes AI opinion/comparison validation require the named comparison target to be addressed directly instead of drifting into unrelated XemAi limitations."),
    ("0.6.6", "Adds live cross-device chat refresh and shared automatic official-channel updates so phone and desktop stay synchronized and reload themselves after a verified release installs."),
    ("0.6.7", "Improves reply reliability: failed generations are persisted visibly across devices, successful replies no longer fail because memory extraction errored, and failed replies can be retried without duplicating the user message."),
    ("0.6.8", "Turns the composer plus button into shared file attachment support across phone and desktop; attached text/code/log/config files are stored on the XemAi host and supplied to the local model with the message."),
    ("0.6.9", "Adds per-message timestamps, right-aligned user metadata with Sent state, and a shared animated XemAi working indicator visible across open devices while a reply is being generated."),
    ("0.7.0", "Adds live Ollama model discovery so XemAi selects and reports its actual Qwen runtime model instead of trusting a stale config.json model value."),
    ("0.7.1", "Makes reply generation asynchronous so phone/desktop requests return immediately while the host continues working, avoids false Failed to fetch reply failures on long generations, clears thinking when the reply is saved, and repairs the attachment upload POST route."),
    ("0.7.2", "Adds a mobile attachment source sheet with Photo Gallery, Take Photo, Record Video and Files while keeping desktop + as a normal file picker."),
    ("0.8.0", "Adds automatic evidence-backed research for factual queries: XemAi ranks reputable sources, fetches the strongest pages, extracts short verified verbatim quotes, cites numbered sources, and appends the evidence it actually checked."),
    ("0.9.0", "Adds authenticated hybrid compute: the always-on host remains the single source of chats/memory/tools while a paired stronger PC can perform model inference over private Tailscale HTTPS, with automatic local fallback when the worker is unavailable."),
    ("0.9.1", "Adds automatic hybrid-worker startup and private-tailnet discovery/pairing, removing manual scripts and token copying when both PCs are online and prerequisites are ready."),
    ("0.9.2", "Fixes the hybrid worker launcher so Python can start it, and validates .pyw launchers before an update is installed."),
    ("0.9.3", "Forwards phone visits from a paired worker PC to the paired central host, while keeping direct desktop app visits local; updates worker setup messaging to use automatic pairing by default."),
    ("0.9.12", "Adds a working chat-options menu and confirmed shared chat deletion while preserving saved memories."),
    ("0.9.13", "Adds evidence-based Skyrim text diagnostics and optional paired-PC image and sampled-video-frame analysis with an explicit vision-model setup control."),
    ("0.9.14", "Adds an optional local teacher model on the paired PC for a second pass on substantive non-research drafts; this adds inference time and does not independently verify facts."),
    ("0.9.15", "Shows verified visual-readiness ticks, adds optional quiet reply sounds, improves recent-chat ordering and scrolling, and removes manual-update/live-support controls from the shared chat UI."),
    ("0.9.16", "Checks for automatic updates every 15 seconds by default, avoids cached GitHub manifests, and waits safely for active replies before installation."),
    ("0.9.17", "Adds bounded PC research, Skyrim and reviewer specialist passes for complex questions, with visible contribution labels, preserved citations and lightweight laptop fallback. Uses the ordinary worker model by default and chooses optional larger reviewers according to GPU memory."),
    ("0.9.18", "Supplies compact evidence and relevant context to the laptop's existing local model and adds one selective local reviewer pass for complex research or Skyrim diagnostics. Preserves citations and actual reply model/compute, skips extra review after citation repair, and skips optional reviews for simple or quick questions; it does not switch the laptop's qwen3:1.7b model or independently verify facts."),
]


def is_ai_comparison_query(text: str) -> bool:
    lower = " ".join(text.lower().split())
    ai_terms = (
        "chatgpt", "openai", "gpt", "claude", "gemini", "copilot",
        "grok", "deepseek", "other ai", "other assistant", "other model",
    )
    comparison_terms = (
        "opinion", "think of", "think about", "compare", "comparison",
        "better", "worse", "stronger", "weaker", "versus", " vs ",
        "benchmark", "compete", "competitive", "how do you rate",
    )
    return (
        any(term in lower for term in ai_terms)
        and any(term in lower for term in comparison_terms)
    )


def ai_comparison_subject(text: str) -> str:
    lower = text.lower()
    for needle, label in (
        ("chatgpt", "ChatGPT"),
        ("openai", "ChatGPT/OpenAI"),
        ("claude", "Claude"),
        ("gemini", "Gemini"),
        ("copilot", "Copilot"),
        ("grok", "Grok"),
        ("deepseek", "DeepSeek"),
    ):
        if needle in lower:
            return label
    return "other AI systems"


def is_self_knowledge_query(text: str) -> bool:
    if not isinstance(text, str):
        return False
    lower = " ".join(text.lower().replace("’", "'").split())

    if is_ai_comparison_query(text):
        return True

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
        "what version is your ai",
        "your update history",
        "through your updates",
        "through your iterative updates",
    )
    if any(phrase in lower for phrase in direct_phrases):
        return True
    # Retain unqualified update follow-ups without capturing another project's
    # named subject, such as "What has been added to Skyrim by this patch?".
    if (lower.rstrip("?.!") in {"update history", "iterative updates"}
            or re.search(r"\b(?:what has been added|what's been added|whats been added|"
                         r"what changed|what has changed)(?:\s+(?:recently|so far))?[?.!]*$", lower)):
        return True

    capability = (
        r"(?:capabilit(?:y|ies)|missing|limitations?|memory|web access|live data|"
        r"tools?|updates?|versions?|models?|runtime|compute|identity|"
        r"what changed|what has changed)"
    )
    modifier = r"(?:(?:current|actual|underlying|runtime|running|language|ai|app|application|available|supported|installed|saved|latest|recent|persistent|long-term|cross-chat)\s+){0,3}"
    named = r"(?:xemai|this ai|this assistant)"
    if any(re.search(pattern, lower) for pattern in (
        r"\b" + named + r"(?:'s|\s+(?:has|supports|uses|lacks|is running|is using|is))?\s+" + modifier + capability + r"\b",
        r"\b" + capability + r"\s+(?:(?:does|can|is|are|of|for)\s+)?" + named + r"\b",
        r"\bmissing\s+(?:from|in)\s+" + named + r"\b",
        r"\b(?:what changed|what has changed)\s+(?:in|with|about)\s+" + named + r"\b",
        r"\bwhat\s+(?:can|can't|cannot)\s+" + named + r"\s+do\b",
    )):
        return True

    # A polite request containing "you" is not necessarily about the assistant:
    # "Could you check the SKSE version?" asks about SKSE, not XemAi's version.
    runtime_nouns = r"(?:versions?|models?|tools?)(?:\s+and\s+" + modifier + r"(?:versions?|models?|tools?))?"
    return any(re.search(pattern, lower) for pattern in (
        r"\byour\s+" + modifier + capability + r"\b",
        r"\b" + capability + r"\s+(?:of|for)\s+(?:you|xemai|this ai|this assistant)\b",
        r"\b(?:what|which)\s+" + modifier + runtime_nouns + r"\s+"
        r"(?:are\s+you(?:\s+(?:(?:currently|actually)\s+)?(?:running|using|on|based on)\b|(?=[?!.]|$))|"
        r"(?:do|can)\s+you\s+(?:(?:currently|actually)\s+)?(?:use|run|have|support|access)\b)",
        r"\b(?:versions?|models?)\s+(?:that\s+)?you\s+(?:are\s+)?(?:using|running|use|run|have)\b",
        r"\byou\s+(?:have|lack|support|use|run|are running|are using)\s+" + modifier + capability + r"\b",
        r"\b(?:what|which)\s+" + modifier + r"model\s+(?:is|was)\s+"
        r"(?:replying|responding|answering)(?:\s+(?:here|to me|to us|in this chat|right now))?[?.!]*$",
        r"\b(?:what|which)\s+" + modifier + r"model\s+(?:answers|handles|generates)\s+"
        r"(?:my|our|these)\s+(?:messages|replies|answers|responses)(?:\s+(?:here|in this chat))?[?.!]*$",
        r"\b(?:what|which)\s+" + modifier + r"model\s+(?:generated|wrote|produced)\s+"
        r"(?:this|your|the last|the previous)\s+(?:answer|reply|response)(?:\s+(?:here|in this chat))?[?.!]*$",
    ))


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
        "i don’t claim to be any specific ai",
        "i don't claim to be any specific ai",
        "i can’t directly compare myself to chatgpt",
        "i can't directly compare myself to chatgpt",
        "i cannot directly compare myself to chatgpt",
    )
    if "2023" in lower and ("training" in lower or "knowledge" in lower):
        return True
    if "training data ends in" in lower or "training cutoff" in lower:
        return True
    return any(marker in lower for marker in stale_markers)


def comparison_answer_needs_retry(question: str, answer: str) -> bool:
    lower = " ".join(answer.lower().replace("’", "'").split())
    question_lower = " ".join(question.lower().split())

    if looks_like_stale_self_description(answer):
        return True

    avoidance_markers = (
        "i don't directly compare myself",
        "i do not directly compare myself",
        "i don't compare myself",
        "i do not compare myself",
        "i won't compare myself",
        "i will not compare myself",
        "i cannot compare myself",
        "i can't compare myself",
        "i am not able to compare myself",
    )
    if any(marker in lower for marker in avoidance_markers):
        return True

    if "chatgpt" in lower and "standalone model" in lower:
        return True

    unsupported_superiority = (
        "xemai excels",
        "i excel at",
        "xemai is superior",
        "i am superior",
        "xemai outperforms",
        "i outperform",
        "xemai is better overall",
        "i am better overall",
    )
    if any(marker in lower for marker in unsupported_superiority):
        return True

    opinion_question = any(
        marker in question_lower
        for marker in ("opinion", "think of", "think about", "what do you think")
    )
    question_targets = tuple(
        term
        for term in (
            "chatgpt", "openai", "claude", "gemini", "copilot",
            "grok", "deepseek",
        )
        if term in question_lower
    )
    if opinion_question:
        opening = lower[:220]
        first_sentence = lower
        for stop in (".", "!", "?"):
            if stop in first_sentence:
                first_sentence = first_sentence.split(stop, 1)[0]
        if question_targets and not any(
            target in first_sentence for target in question_targets
        ):
            return True
        direct_openers = (
            "i think",
            "my view",
            "my opinion",
            "i regard",
            "i see ",
        )
        if not any(marker in opening for marker in direct_openers):
            return True

    return False


def build_authoritative_self_context(
    config,
    tool_registry,
    runtime_model_info: dict | None = None,
) -> str:
    runtime_model_info = runtime_model_info or {}
    runtime_model = str(
        runtime_model_info.get("model")
        or config.get("model", "unknown")
    )
    capabilities = build_capability_status(
        config, tool_registry, runtime_model_info
    )
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
Underlying language model actually selected at runtime: {runtime_model}
Model-selection source: {runtime_model_info.get("source", "configured_fallback")}
Compute route: {runtime_model_info.get("compute", "local_host")}
Compute machine: {runtime_model_info.get("compute_name", "Always-on host")}

CURRENT CAPABILITIES
{capability_text}

KNOWN RELEASE HISTORY
{release_text}

IMPORTANT CORRECTIONS
- XemAi DOES have persistent chat history and cross-chat long-term memory.
- XemAi DOES have live web search when its saved Ollama web key is configured
  and accepted, plus direct webpage fetching.
- XemAi DOES have a sandboxed local workspace with file list/read/write tools.
- XemAi DOES support evidence-backed research when web search is configured:
  factual/evidence-heavy questions can trigger reputable-source ranking, live
  page fetching, short verified quote extraction and numbered source URLs.
- XemAi must never claim a study/source was checked unless the research pipeline
  actually returned it.
- XemAi DOES support shared file attachments from the phone/desktop composer.
  Text/code/log/config attachments can be read into model context. Uploaded
  Skyrim plugin lists and recognised crash logs get bounded diagnostic summaries.
  JPEG/PNG images and browser-sampled video frames can be interpreted by the
  optional paired-PC vision model when installed and reachable. Other binary
  formats still require parsers; stored files alone do not imply analysis.
- XemAi DOES support authenticated hybrid compute when paired: chats, memory,
  research and tools stay on the always-on host while model inference can run
  on a stronger PC over private Tailscale HTTPS. If that worker is unavailable,
  model inference falls back to the host's local Ollama.
- Complex questions can use optional bounded PC research/Skyrim/reviewer
  passes over supplied evidence. On the laptop, compact evidence and relevant
  context support the already-selected local model, with at most one optional
  final review for eligible complex questions; no laptop preparation pass runs.
  Citation correction consumes that laptop extra pass. Quick/simple questions
  skip automatic review, and optional passes can be disabled. These passes have
  no tools or independent verification and do not change model weights or switch
  the laptop to a larger model. Failed or late reviews preserve the original reply.
- The runtime compute/model lines above are authoritative for where the current
  process intends to generate.
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
- Do not infer the active model from config.json. The runtime model line above
  comes from Ollama discovery and is authoritative for the current process.

AI COMPARISON RULES
- You are specifically XemAi. Never say you are an unnamed or unspecified AI.
- You MAY directly compare yourself with ChatGPT and other AI systems.
- If asked for your opinion, give a clear reasoned opinion first rather than a
  generic disclaimer.
- The first sentence of an opinion/comparison answer must state a position.
  Prefer openings such as "I think...", "My view is...", or "I regard...".
  Do not open with a disclaimer, refusal, or "I don't directly compare myself".
- The first sentence must name or clearly address the AI/system the user asked about.
  A ChatGPT opinion question must not be answered by drifting into a list of
  XemAi limitations without first giving a direct view of ChatGPT.
- Separate the underlying local model from XemAi as the complete application.
- Do not claim XemAi is better or worse overall without benchmark evidence.
- It is valid to say the local model may be a bottleneck on difficult reasoning,
  coding, or broad knowledge tasks, while XemAi may have advantages in local
  continuity, persistent personal memory, user-specific project context,
  auditable state, and custom tools.
- Do not invent current features, model names, training cutoffs, benchmark
  results, or limitations for ChatGPT or another external system. If current
  details matter, use live research when available or state the uncertainty.
- Do not reduce ChatGPT to merely a standalone model. Treat it as an AI
  product/system whose exact current capabilities should be verified before
  making detailed claims.
- Describe XemAi's memory, continuity, local control, and custom tools as design
  advantages or verified capabilities, not proof that XemAi "excels" or
  outperforms another system.
- Never use "I can't compare myself" as an excuse when a reasoned comparison is
  possible from verified information.

CURRENT GAPS / LIMITS
- No arbitrary shell or command execution yet.
- No unrestricted filesystem access outside the dedicated workspace.
- No unrestricted desktop/computer control.
- PC image/vision analysis needs a separately enabled model and reachable worker.
- Video analysis covers sampled still frames only; no audio or continuous motion.
- No direct Vortex/game-folder access, binary plugin conflict analysis or game reproduction.
- No general-purpose external app/API integration framework beyond the tools
  currently configured.
- Feedback currently influences future prompts/context; it does not train or
  fine-tune the model weights.
- Memory retrieval is still relatively simple compared with a mature semantic
  retrieval/evidence system.
- The currently selected underlying model can still be a reasoning/quality
  bottleneck on hard tasks even when the surrounding XemAi application is capable.
- Hybrid compute improves access to stronger local hardware; it does not by itself
  prove frontier-model reasoning or benchmark parity.

When the user asks what XemAi is missing, reason from CURRENT GAPS / LIMITS and
the user's project goals. When the user asks what has been added, use KNOWN
RELEASE HISTORY. Correct any conflicting prior self-description directly.
""".strip()


def build_ai_comparison_fallback(
    text: str,
    config,
    runtime_model_info: dict | None = None,
) -> str:
    subject = ai_comparison_subject(text)
    runtime_model_info = runtime_model_info or {}
    model = runtime_model_info.get("model") or config.get("model", "unknown")
    return (
        f"My view of {subject}: it is a strong general-purpose AI benchmark "
        "for me, and at my current stage I would not claim to be better "
        "overall without evidence. "
        f"My underlying model is {model}, which may be a bottleneck on "
        "difficult reasoning, coding, and broad-knowledge tasks. XemAi as a "
        "whole is being built differently around persistent local memory, "
        "continuity across your projects, user-specific context, local control, "
        "custom tools, and auditable state. Those are design advantages, not "
        "proof that I outperform ChatGPT. My goal is to measure where I am "
        "weaker, improve those areas, and earn stronger claims through "
        "benchmarks rather than assertion. I will not invent training cutoffs "
        "or unverified current details about the other system."
    )


def build_self_knowledge_fallback(
    text: str,
    config,
    tool_registry,
    runtime_model_info: dict | None = None,
) -> str:
    assistant = config.get("assistant_name", "XemAi")
    runtime_model_info = runtime_model_info or {}
    model = runtime_model_info.get("model") or config.get("model", "unknown")
    capabilities = build_capability_status(
        config, tool_registry, runtime_model_info
    )
    capability_text = "; ".join(capabilities[:8])
    return (
        f"I am {assistant}, currently running as XemAi v{VERSION} with {model} "
        "as my underlying language model. I should answer questions about "
        "my identity and capabilities from the running application, not from a "
        "generic pretrained model self-description. Verified capabilities "
        f"currently include: {capability_text}. I will not invent a training "
        "cutoff or claim that I lack memory, web tools, or other capabilities "
        "that the runtime reports as enabled. I also will not claim abilities "
        "that are not in the runtime capability snapshot."
    )
