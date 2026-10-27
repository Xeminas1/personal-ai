"""Synthetic regression tests for local-first XemAi source inspection.

Never uses private conversations, network access or real owner machine paths.
"""
from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, PropertyMock, patch

from app.developer_guidance import (
    is_xemai_source_request,
    inspected_source_paths,
    self_source_unavailable_report,
    source_context_for_request,
    source_answer_needs_retry,
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
        self.assertEqual(self.logger.calls.count("dev_projects"), 1)

    def test_fabricated_confirmed_class_is_rejected_after_real_source_read(self):
        tools = self.configure()
        source = source_context_for_request(QUESTION, tools)
        claim = (
            "The file app/developer_projects.py defines the actual class "
            "DeveloperProjects, which checks only approved project roots. "
            "The module app/agent_team.py contains verified class DevTaskAgent "
            "which can perform hidden writes. This was verified from source. "
            "The proposed engineering workflow must remain read-only."
        )
        self.assertTrue(source_answer_needs_retry(QUESTION, claim, source))
        good = (
            "The file app/developer_projects.py defines class DeveloperProjects. "
            "The file app/agent_team.py defines class ReadOnlyTeamTools. "
            "Both definitions appear in the retrieved synthetic source, so "
            "we can report them as observations. This does not demonstrate "
            "any deployed shell access, development privileges or runtime "
            "test execution."
        )
        self.assertFalse(source_answer_needs_retry(QUESTION, good, source))

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

    def test_backend_reports_missing_self_source_without_web_or_model_claims(self):
        from app import gui_backend
        from app.database import Database

        self.registry.developer = DeveloperProjects(
            [], workspace=self.registry.workspace
        )
        db = Database(self.data / "personal_ai.db")
        user = db.create_user("Synthetic User")
        chat_id = db.create_chat(user["id"], "Source test")["id"]
        db.close()
        backend = gui_backend.ChatBackend.__new__(gui_backend.ChatBackend)
        backend.config = {
            "model": "qwen3:8b", "auto_memory": False,
            "specialists_enabled": False, "laptop_answer_guidance": False,
            "evidence_research_mode": "auto", "agent_team_enabled": False,
        }
        backend.logger = logging.getLogger("self-source-regression")
        llm = Mock()
        llm.model = "qwen3:8b"
        llm.route_info = {"compute": "remote_worker"}
        with patch.object(gui_backend, "DATA_DIR", self.data), \
             patch.object(gui_backend, "ToolRegistry", return_value=self.registry), \
             patch.object(gui_backend, "build_llm_client", return_value=llm), \
             patch.object(backend, "refresh_runtime_model", return_value={
                 "model": "qwen3:8b", "compute": "remote_worker",
                 "worker_available": True,
             }), \
             patch.object(gui_backend, "should_research_query", return_value=True), \
             patch.object(gui_backend, "should_force_web_search", return_value=True), \
             patch.object(ToolRegistry, "web_search_enabled",
                          new_callable=PropertyMock, return_value=True), \
             patch.object(self.registry, "research_evidence",
                          side_effect=AssertionError("web must not be called")):
            response = backend.send(chat_id, QUESTION)
        self.assertIn("does not expose dev_projects/dev_read", response)
        self.assertIn("No dev_read call succeeded", response)
        llm.agent_chat.assert_not_called()
        self.assertNotIn("DeveloperProjectsManager", response)

    def test_generic_xemtv_source_question_remains_supported(self):
        tools = self.configure("xemtv")
        q = "Inspect XemTV source file app/tools.py and explain it."
        source = source_context_for_request(q, tools)
        self.assertIn("class ToolRegistry:", source)


if __name__ == "__main__":
    unittest.main()
