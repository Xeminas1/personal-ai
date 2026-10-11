"""Regression checks for read-only multi-file Kotlin investigations."""
from __future__ import annotations

import tempfile
from pathlib import Path

from app.developer_guidance import (
    inspected_source_paths,
    prefer_local_project_sources,
    source_answer_needs_retry,
    source_context_for_request,
    source_failure_report,
)
from app.developer_projects import DeveloperProjects
from app.evidence import TurnEvidenceTools
from app.tools import ToolRegistry


class NoopLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


QUESTION = (
    "Using your Developer Mode tools, investigate XemTV's Home screen sidebar. "
    "Find and examine the actual Kotlin files responsible for sidebar navigation, "
    "focus handling and glow effects. Explain how these components interact, "
    "identify possible causes of incorrect focus behaviour or overlapping glow "
    "effects, and recommend specific improvements. Use local XemTV source. "
    "Do not perform web research unless external documentation is genuinely necessary. "
    "Do not modify files."
)


def test_multifile_inspection_uses_only_real_kotlin_sources():
    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp) / "XemAi"
        base.mkdir()
        data = base / "data"
        data.mkdir()
        project = Path(temp) / "XemTV"
        source = project / "android-app/app/src/main/java/com/xemtv/app"
        source.mkdir(parents=True)
        for filename, content in {
            "HomeFocusPolicy.kt": "class HomeFocusPolicy { fun returnToHome() = 0 }\n",
            "NavFocusState.kt": "class NavFocusState { fun focused() = true }\n",
            "SidebarEdgeGlow.kt": "class SidebarEdgeGlow { fun selectAt(y: Float) {} }\n",
            "SidebarGlowGeometry.kt": "class SidebarGlowGeometry { fun radius() = 6 }\n",
            "HomeLayout.kt": "class HomeLayout { fun layout() = 1 }\n",
        }.items():
            (source / filename).write_text(content, encoding="utf-8")
        docs = project / "docs"
        docs.mkdir()
        (docs / "HOME_FOCUS_GLOW_TRUE_BLACK_0.8.21.md").write_text(
            "DOCS_SHOULD_NOT_BE_PREFERRED", encoding="utf-8"
        )
        (docs / "NAVIGATION_FOCUS_SIDEBAR_GLOW.md").write_text(
            "DOCS_SHOULD_NOT_BE_PREFERRED", encoding="utf-8"
        )
        (project / ".git").mkdir()
        (project / ".git" / "sidebar.kt").write_text("GIT_SECRET", encoding="utf-8")
        logger = NoopLogger()
        registry = ToolRegistry(base, data, logger)
        registry.developer = DeveloperProjects(
            [{"id": "xemtv", "path": str(project)}],
            workspace=registry.workspace,
        )
        tools = TurnEvidenceTools(registry, QUESTION)
        context = source_context_for_request(QUESTION, tools)
        assert context, "Explicit multi-file request must preload actual code"
        paths = inspected_source_paths(context)
        assert 3 <= len(paths) <= 4, paths
        assert all(path.endswith(".kt") and path.startswith("android-app/") for path in paths)
        assert "DOCS_SHOULD_NOT_BE_PREFERRED" not in context
        assert "GIT_SECRET" not in context
        assert prefer_local_project_sources(QUESTION, context)
        tools.web_allowed = False
        names = {row["function"]["name"] for row in tools.definitions()}
        assert {"dev_list", "dev_read", "dev_search"}.issubset(names)
        assert not {"web_search", "web_fetch", "research_evidence"} & names
        assert not tools.web_search_enabled

        unfinished = (
            "The XemTV docs folder has focus notes. "
            "Would you like me to examine specific markdown files? "
            "I can also show you the first few lines of a relevant document."
        )
        assert source_answer_needs_retry(QUESTION, unfinished, context)
        vague = "These components are related through navigation and focus. " * 12
        assert source_answer_needs_retry(QUESTION, vague, context)
        valid = (
            "In " + Path(paths[0]).name +
            " the application controls one sidebar-related aspect. In " +
            Path(paths[1]).name +
            " a separate drawing or focus routine is implemented. "
            "These have different responsibilities. The first file's code "
            "defines a focused element, and the second defines the visual "
            "response that should be checked for ordering and duplicate "
            "draw operations. Their actual runtime linkage still requires "
            "verifying the call sites before claiming a definitive root cause."
        )
        assert not source_answer_needs_retry(QUESTION, valid, context)
        fallback = source_failure_report(context)
        assert "have not yet produced a reliable analysis" in fallback
        assert all(path in fallback for path in paths)
        assert prefer_local_project_sources(
            "Inspect source from XemTV", context
        )
        assert not prefer_local_project_sources(
            "Search the web and inspect source from XemTV", context
        )
        assert not prefer_local_project_sources(QUESTION, "")
        # Explicit single-file document requests can still read the docs.
        doc_context = source_context_for_request(
            "Inspect XemTV's NAVIGATION_FOCUS_SIDEBAR_GLOW.md", tools
        )
        assert "DOCS_SHOULD_NOT_BE_PREFERRED" in doc_context
        # A plain conversational reply shouldn't trigger any source gathering.
        assert not source_context_for_request(
            "Hello, how are you?", tools
        )


if __name__ == "__main__":
    test_multifile_inspection_uses_only_real_kotlin_sources()
    print("Multi-file developer source tests passed.")
