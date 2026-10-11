"""Developer Mode source-followthrough regression tests.

A user's explicit source inspection request must result in real, bounded
dev_read evidence even if a model does not plan a second tool call.
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from app.developer_guidance import source_context_for_request
from app.developer_projects import DeveloperProjects
from app.evidence import TurnEvidenceTools
from app.tools import ToolRegistry


class Logger:
    def __init__(self):
        self.calls = []

    def info(self, *args, **kwargs):
        if args and args[0] == "Tool call | name=%s":
            self.calls.append(args[1])

    def warning(self, *args, **kwargs):
        pass


def run():
    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp) / "XemAi"
        base.mkdir()
        data = base / "data"
        data.mkdir()
        project = Path(temp) / "XemTV"
        source = project / "android-app" / "app" / "src" / "main" / "java" / "com" / "xemtv" / "app"
        source.mkdir(parents=True)
        content = (
            "class SidebarEdgeGlow {\n"
            "    fun selectAt(y: Float) { invalidate() }\n"
            "    override fun onDraw(canvas: Canvas) { canvas.drawLine(0f, 0f, 1f, 1f, paint) }\n"
            "}\n"
        )
        (source / "SidebarEdgeGlow.kt").write_text(content, encoding="utf-8")
        (source / "HomeFocusPolicy.kt").write_text(
            "class HomeFocusPolicy { fun focusHome() {} }\n", encoding="utf-8"
        )
        (source / "SidebarGlowGeometry.kt").write_text(
            "class SidebarGlowGeometry { fun glow() {} }\n", encoding="utf-8"
        )
        (source / "SecretToken.kt").write_text("NOT_ALLOWED", encoding="utf-8")
        (source / ".env").write_text("SECRET_PASSWORD=test", encoding="utf-8")
        (project / ".git").mkdir()
        (project / ".git" / "SidebarEdgeGlow.kt").write_text(
            "DO_NOT_READ_GIT", encoding="utf-8"
        )
        (project / "data").mkdir()
        (project / "data" / "SidebarEdgeGlow.kt").write_text(
            "DO_NOT_READ_DATA", encoding="utf-8"
        )
        logger = Logger()
        registry = ToolRegistry(base, data, logger)
        registry.developer = DeveloperProjects(
            [{"id": "xemtv", "path": str(project)}],
            workspace=registry.workspace,
        )
        tools = TurnEvidenceTools(registry, "XemTV code analysis")
        question = (
            "Use your Developer Mode tools to inspect XemTV. First use dev_list. "
            "Then use dev_read to open SidebarEdgeGlow.kt and explain selectAt and onDraw."
        )
        context = source_context_for_request(question, tools)
        assert context.startswith("VERIFIED READ-ONLY DEVELOPMENT FILE CONTENTS")
        assert "selectAt" in context and "onDraw" in context
        assert "SidebarEdgeGlow.kt" in context
        assert "DO_NOT_READ_GIT" not in context
        assert "DO_NOT_READ_DATA" not in context
        assert "NOT_ALLOWED" not in context
        assert logger.calls == ["dev_read"], logger.calls
        assert (source / "SidebarEdgeGlow.kt").read_text(encoding="utf-8") == content

        # Broad source question should select relevant file names without
        # requiring the model to first call dev_list.
        logger.calls.clear()
        context = source_context_for_request(
            "Inspect the XemTV home sidebar focus and glow Kotlin code. Explain how it works.",
            tools,
        )
        assert context
        assert "SidebarGlowGeometry.kt" in context or "SidebarEdgeGlow.kt" in context
        assert "dev_read" in logger.calls
        assert all(name in {"dev_read", "dev_trace"} for name in logger.calls)

        # No developer request must not trigger private source reads.
        logger.calls.clear()
        assert source_context_for_request("Do you think XemTV is a good name?", tools) == ""
        assert not logger.calls

        # A secret filename is not a candidate or readable via this preflight.
        logger.calls.clear()
        assert source_context_for_request(
            "Inspect XemTV source file SecretToken.kt", tools
        ) == ""
        assert not logger.calls

        # Scope protects other projects and previously configured workspaces.
        registry.developer = DeveloperProjects([], workspace=registry.workspace)
        assert source_context_for_request(question, tools) == ""


if __name__ == "__main__":
    run()
    print("Developer source preflight tests passed.")
