"""Synthetic regression tests for local-first XemAi source inspection.

Never uses private conversations, network access or real owner machine paths.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.developer_guidance import (
    is_xemai_source_request,
    inspected_source_paths,
    self_source_unavailable_report,
    source_context_for_request,
)
from app.developer_projects import DeveloperProjects
from app.evidence import TurnEvidenceTools
from app.tools import ToolRegistry


QUESTION = (
    "XemAi, check your own application source code. Call dev_projects and "
    "dev_read to inspect app/developer_projects.py, app/agent_team.py "
    "and app/tools.py. Quote only actual retrieved class declarations. "
    "Do not search the internet."
)


class RecordingLogger:
    def __init__(self):
        self.calls = []

    def info(self, message, *args, **kwargs):
        if message == "Tool call | name=%s" and args:
            self.calls.append(args[0])

    def warning(self, *args, **kwargs):
        pass


class SelfSourceRoutingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.base = root / "XemAi"
        self.base.mkdir()
        self.data = self.base / "data"
        self.data.mkdir()
        self.checkout = root / "approved-source"
        (self.checkout / "app").mkdir(parents=True)
        (self.checkout / "app" / "developer_projects.py").write_text(
            "class DeveloperProjects:\n    pass\n", encoding="utf-8"
        )
        (self.checkout / "app" / "agent_team.py").write_text(
            "class ReadOnlyTeamTools:\n    pass\n", encoding="utf-8"
        )
        (self.checkout / "app" / "tools.py").write_text(
            "class ToolRegistry:\n    pass\n", encoding="utf-8"
        )
        self.logger = RecordingLogger()
        self.registry = ToolRegistry(self.base, self.data, self.logger)

    def configure(self, project_id="xemai"):
        self.registry.developer = DeveloperProjects(
            [{"id": project_id, "path": str(self.checkout)}],
            workspace=self.registry.workspace,
        )
        return TurnEvidenceTools(self.registry, QUESTION)

    def test_self_code_question_does_not_capture_generic_chat(self):
        self.assertTrue(is_xemai_source_request(QUESTION))
        self.assertFalse(is_xemai_source_request(
            "What is XemAi's goal compared with ChatGPT?"
        ))
        self.assertFalse(is_xemai_source_request(
            "Inspect source code supplied in this chat."
        ))
        self.assertFalse(is_xemai_source_request(
            "Inspect XemTV navigation and sidebar source code."
        ))

    def test_preflight_reads_real_self_checkout(self):
        tools = self.configure()
        source = source_context_for_request(QUESTION, tools)
        self.assertEqual(set(inspected_source_paths(source)), {
            "app/developer_projects.py", "app/agent_team.py", "app/tools.py"
        })
        self.assertIn("class DeveloperProjects:", source)
        self.assertIn("class ReadOnlyTeamTools:", source)
        self.assertIn("class ToolRegistry:", source)
        self.assertNotIn("class DevTaskAgent:", source)
        self.assertNotIn("has_admin_write_access", source)
        self.assertEqual(self.logger.calls.count("dev_read"), 3)
        self.assertEqual(self_source_unavailable_report(tools).startswith(
            "dev_projects succeeded"
        ), False)  # not a missing-source path after a successful preflight

    def test_unrelated_approved_checkout_is_never_misidentified_as_self(self):
        tools = self.configure("xemtv")
        self.assertEqual(source_context_for_request(QUESTION, tools), "")
        report = self_source_unavailable_report(tools)
        self.assertIn("dev_projects succeeded", report)
        self.assertIn("xemtv", report)
        self.assertIn("No dev_read call succeeded", report)
        self.assertNotIn(str(self.checkout), report)
        self.assertNotIn("ToolRegistry", report)

    def test_missing_project_reports_tools_not_registered(self):
        self.registry.developer = DeveloperProjects(
            [], workspace=self.registry.workspace
        )
        tools = TurnEvidenceTools(self.registry, QUESTION)
        self.assertEqual(source_context_for_request(QUESTION, tools), "")
        report = self_source_unavailable_report(tools)
        self.assertIn("does not expose dev_projects/dev_read", report)
        self.assertIn("No dev_read call succeeded", report)
        self.assertNotIn(str(self.checkout), report)

    def test_generic_xemtv_source_question_remains_supported(self):
        tools = self.configure("xemtv")
        q = "Inspect XemTV source file app/tools.py and explain it."
        source = source_context_for_request(q, tools)
        self.assertIn("class ToolRegistry:", source)


if __name__ == "__main__":
    unittest.main()
