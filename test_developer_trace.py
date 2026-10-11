"""Deterministic tests for source-code call-site evidence in Developer Mode."""
from __future__ import annotations

import tempfile
from pathlib import Path

from app.developer_guidance import (
    inspected_source_paths,
    source_answer_needs_retry,
    source_context_for_request,
)
from app.developer_projects import DeveloperProjects, ProjectError
from app.evidence import TurnEvidenceTools
from app.tools import ToolRegistry


class TestLogger:
    def info(self, *args, **kwargs):
        pass

    def warning(self, *args, **kwargs):
        pass


def run():
    with tempfile.TemporaryDirectory() as temp:
        base = Path(temp) / "XemAi"
        base.mkdir()
        data = base / "data"
        data.mkdir()
        project = Path(temp) / "XemTV"
        source = project / "android-app/app/src/main/java/com/xemtv/app"
        source.mkdir(parents=True)
        code = {
            "HomeFocusPolicy.kt": "object HomeFocusPolicy { fun shouldApplyHomeRefresh() = true }\n",
            "NavFocusState.kt": "object NavFocusState { fun activeStates() = true }\n",
            "NavSelectionGlow.kt": "class NavSelectionGlow { var railFocused = false }\n",
            "SidebarEdgeGlow.kt": "class SidebarEdgeGlow { fun selectAt(y: Float) {} }\n",
            "SidebarGlowGeometry.kt": "object SidebarGlowGeometry { fun midpoint(x:Int) = x }\n",
            "MainActivity.kt": (
                "class MainActivity {\n"
                "  val a = NavFocusState.activeStates()\n"
                "  val b = HomeFocusPolicy.shouldApplyHomeRefresh()\n"
                "  val c = SidebarEdgeGlow()\n"
                "  fun select() { c.selectAt(SidebarGlowGeometry.midpoint(2).toFloat()) }\n"
                "}\n"
            ),
            "Theme.kt": "object Theme { fun pill() = NavSelectionGlow() }\n",
        }
        for name, content in code.items():
            (source / name).write_text(content, encoding="utf-8")
        (project / ".git").mkdir()
        (project / ".git" / "NavFocusState.kt").write_text(
            "UNTRUSTED_GIT_CONTENT", encoding="utf-8"
        )
        (project / "docs").mkdir()
        (project / "docs" / "SidebarEdgeGlow.kt").write_text(
            "COMMENT_NOT_CALLER", encoding="utf-8"
        )
        (source / "AppSecretToken.kt").write_text(
            "NavFocusState = PRIVATE", encoding="utf-8"
        )
        registry = ToolRegistry(base, data, TestLogger())
        registry.developer = DeveloperProjects(
            [{"id": "xemtv", "path": str(project)}], workspace=registry.workspace
        )
        tools = TurnEvidenceTools(registry, "XemTV Developer Mode")
        names = {x["function"]["name"] for x in tools.definitions()}
        assert {"dev_trace", "dev_read", "dev_list", "dev_search"} <= names
        result = registry.developer.trace_symbol("xemtv", "NavFocusState")
        assert result["symbol"] == "NavFocusState"
        assert any(x["path"].endswith("MainActivity.kt") and x["line"] == 2
                   for x in result["references"])
        assert not any(".git" in x["path"] or "AppSecretToken" in x["path"]
                       for x in result["references"])
        assert result["scanned"] <= 1200
        assert not registry.developer.trace_symbol("xemtv", "NoSymbol")["references"]
        for bad in ("", "a", "../x", "A-B", "X" * 81, "token;rm"):
            try:
                registry.developer.trace_symbol("xemtv", bad)
            except ProjectError:
                pass
            else:
                raise AssertionError("Unsafe trace identifier was accepted: " + bad)
        for bad in (0, 21, True):
            try:
                registry.developer.trace_symbol("xemtv", "NavFocusState", max_results=bad)
            except ProjectError:
                pass
            else:
                raise AssertionError("Unsafe result count was accepted.")

        question = (
            "Using Developer Mode investigate XemTV's home sidebar navigation "
            "focus, selection and glow. Explain how components interact. "
            "Do not modify files or browse the web."
        )
        context = source_context_for_request(question, tools)
        assert context.startswith("VERIFIED READ-ONLY DEVELOPMENT FILE CONTENTS")
        paths = inspected_source_paths(context)
        assert len(paths) == 4 and all(path.endswith(".kt") for path in paths), paths
        assert "READ-ONLY CROSS-FILE IDENTIFIER REFERENCES" in context
        assert "MainActivity.kt" in context
        assert "Theme.kt" in context
        assert "NavFocusState" in context
        assert "NavSelectionGlow" in context
        assert "UNTRUSTED_GIT_CONTENT" not in context
        assert "COMMENT_NOT_CALLER" not in context
        assert "PRIVATE" not in context
        # Validation still parses correctly when trace excerpts follow source JSON.
        assert source_answer_needs_retry(question, "Need to choose files?", context)
        detailed = (
            "The file " + Path(paths[0]).name + " declares a navigation-related "
            "component, while " + Path(paths[1]).name + " holds another policy. "
            "The trace shows MainActivity.kt referencing these identifiers. "
            "This is a lexical reference and not proof of a runtime call flow. "
            "The relevant code must still be checked to distinguish causes."
        )
        assert not source_answer_needs_retry(question, detailed, context)
        # Unauthorised or disabled projects are never traced.
        registry.developer = DeveloperProjects([], workspace=registry.workspace)
        assert source_context_for_request(question, tools) == ""


if __name__ == "__main__":
    run()
    print("Developer source-tracing regression tests passed.")
