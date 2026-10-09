from __future__ import annotations


def build_capability_status(
    config,
    tool_registry,
    runtime_model_info: dict | None = None,
) -> list[str]:
    runtime_model_info = runtime_model_info or {}
    runtime_model = str(
        runtime_model_info.get("model")
        or config.get("model", "unknown")
    )
    model_source = str(
        runtime_model_info.get("source")
        or "configured_fallback"
    )
    installed_qwen = [
        str(name)
        for name in runtime_model_info.get("installed_qwen", [])
        if str(name).strip()
    ]

    web_disabled_for_turn = getattr(tool_registry, "web_allowed", True) is False
    web_state = "disabled for this reply at the user's request" if web_disabled_for_turn else (
        "configured; use the Web Test control to verify the saved Ollama key"
        if tool_registry.web_search_enabled
        else "not configured"
    )
    return [
        f"Identity: {config.get('assistant_name', 'XemAi')}",
        "Persistent local user profile: enabled",
        "Persistent chat history across restarts: enabled",
        "Cross-chat long-term memory: enabled",
        (
            "Automatic memory extraction: enabled"
            if config.get("auto_memory", True)
            else "Automatic memory extraction: disabled"
        ),
        "Recent 0-10 feedback is available as a future-response optimisation signal",
        f"Live web search: {web_state}",
        (
            "Evidence-backed reputable-source research: disabled for this reply at the user's request"
            if web_disabled_for_turn else
            "Evidence-backed reputable-source research: enabled with ranked sources, "
            "verbatim quote extraction and source URLs"
            if tool_registry.web_search_enabled
            else "Evidence-backed reputable-source research: unavailable until web search is configured"
        ),
        (
            "Direct HTTP/HTTPS webpage fetching: disabled for this reply at the user's request"
            if web_disabled_for_turn else "Direct HTTP/HTTPS webpage fetching: enabled"
        ),
        "Calculator: enabled",
        "Current date/time lookup: enabled",
        "Sandboxed local workspace file listing/reading/writing: enabled",
        f"Underlying local model actually selected at runtime: {runtime_model}",
        f"Model selection source: {model_source}",
        (
            "Hybrid compute route: "
            + (
                f"strong PC worker ({runtime_model_info.get('compute_name', 'Powerful PC')})"
                if runtime_model_info.get("compute") == "remote_worker"
                else "always-on host local fallback"
            )
            if config.get("hybrid_enabled", False)
            else "Hybrid compute route: disabled"
        ),
        (
            "Hybrid worker availability: online"
            if runtime_model_info.get("worker_available")
            else (
                "Hybrid worker availability: offline/unpaired; local fallback active"
                if config.get("hybrid_enabled", False)
                else "Hybrid worker availability: not configured"
            )
        ),
        (
            "Qwen models detected by Ollama: " + ", ".join(installed_qwen)
            if installed_qwen
            else "Qwen models detected by Ollama: none reported"
        ),
        "Arbitrary shell/command execution: disabled",
        "Unrestricted filesystem access: disabled",
        "Unrestricted computer/desktop control: disabled",
        "Image analysis: implemented through optional qwen2.5vl:7b on the paired PC; requires enabling PC visual analysis and an awake, reachable worker",
        "Video visual evidence: up to four timestamped still frames sampled in the browser; optional PC vision model interprets those frames only",
        "Audio and continuous full-motion video analysis: not implemented",
        "Skyrim SE modding diagnostics: uploaded Vortex plugins/loadorder files and recognised crash logs are summarised with line evidence; no direct Vortex/game-folder or binary plugin inspection",
        "Shared Android/mobile web client: enabled through the local XemAi mobile server",
        "PC and phone share the same chats, memories, feedback and database",
        "Cross-device live chat refresh: enabled while clients are open",
        "Shared file attachments: enabled for phone and desktop; text/code/log/config contents can be supplied to the local model",
        (
            "Automatic official-channel updates: enabled"
            if config.get("auto_install_updates", True)
            else "Automatic official-channel updates: disabled"
        ),
        "Private remote phone access can be routed through Tailscale Serve",
        "Mobile update checks/install: enabled for the official configured XemAi update channel",
        "Desktop and mobile visual redesign: enabled with bubble-based chat UI",
        "General external API/app integrations: not yet implemented beyond configured tools",
    ]
