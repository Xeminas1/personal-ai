from __future__ import annotations


def build_capability_status(config, tool_registry) -> list[str]:
    web_state = (
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
        "Direct HTTP/HTTPS webpage fetching: enabled",
        "Calculator: enabled",
        "Current date/time lookup: enabled",
        "Sandboxed local workspace file listing/reading/writing: enabled",
        f"Underlying local model: {config.get('model', 'unknown')}",
        "Arbitrary shell/command execution: disabled",
        "Unrestricted filesystem access: disabled",
        "Unrestricted computer/desktop control: disabled",
        "Native image/vision analysis: not yet implemented",
        "Native audio/video analysis: not yet implemented",
        "Shared Android/mobile web client: enabled through the local XemAi mobile server",
        "PC and phone share the same chats, memories, feedback and database",
        "Private remote phone access can be routed through Tailscale Serve",
        "Mobile update checks/install: enabled for the official configured XemAi update channel",
        "General external API/app integrations: not yet implemented beyond configured tools",
    ]
