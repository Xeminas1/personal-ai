"""Regression tests for opt-in supervised XemAi agents and self audits."""
from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.agent_team import (
    ReadOnlyTeamTools, agent_team_context,
    requested_agent_mode, run_agent_team,
)
from app import gui_backend
from app.database import Database


class FakeTools:
    def __init__(self, allowed=True, web=False):
        self.web_allowed = allowed
        self.web_search_enabled = web
        self.executed = []
        self.research_calls = []
        self.sources = []
        self.known_urls = set()
        self.evidence_attempted = False
        self.developer = SimpleNamespace(enabled=False)

    def definitions(self):
        return [{"type": "function", "function": {"name": name}}
                for name in ("dev_read", "dev_trace", "workspace_list",
                             "workspace_read", "workspace_write",
                             "web_search", "web_fetch", "research_evidence",
                             "calculator", "current_time")]

    def execute(self, name, arguments):
        self.executed.append(name)
        return json.dumps({"ok": True, "result": name})

    def research_evidence(self, query, max_sources=2):
        self.research_calls.append((query, max_sources))
        return {
            "sources": [
                {"id": 1, "title": "Ollama docs", "url": "https://ollama.com",
                 "page_fetched": True, "snippet": "Compare model quality before upgrading."}
            ]
        }


class AgentTests(unittest.TestCase):
    def test_explicit_invocation_only(self):
        self.assertEqual(requested_agent_mode(
            "Run a self-improvement audit of XemAi"
        ), "self_audit")
        self.assertEqual(requested_agent_mode(
            "Run your self-improvement agent"
        ), "self_audit")
        self.assertEqual(requested_agent_mode(
            "Use agents to investigate the XemTV sidebar and report."
        ), "investigation")
        self.assertEqual(requested_agent_mode(
            "Agent team: investigate this screenshot."
        ), "investigation")
        for q in (
            "Are you able to use agents?",
            "If you had access to agents what would you do?",
            "What about an agent that researches improvements?",
            "Can agents help me?",
            "No agents, please check this file.",
            "Do not use agents to investigate XemTV.",
            "Run a self-improvement audit of XemAi with no agents.",
            "What is your current AI model?",
        ):
            with self.subTest(q=q):
                self.assertEqual(requested_agent_mode(q), "")
        self.assertEqual(requested_agent_mode(
            "Use agents to inspect these files.", enabled=False
        ), "")

    def test_tool_policy_enforces_read_only_at_execution(self):
        tools = FakeTools()
        safe = ReadOnlyTeamTools(tools, allow_web=False)
        names = {x["function"]["name"] for x in safe.definitions()}
        self.assertIn("dev_trace", names)
        self.assertIn("workspace_read", names)
        self.assertNotIn("workspace_write", names)
        self.assertNotIn("web_search", names)
        self.assertFalse(json.loads(safe.execute("workspace_write", {}))["ok"])
        self.assertFalse(json.loads(safe.execute("web_search", {}))["ok"])
        self.assertEqual(tools.executed, [])
        assert json.loads(safe.execute("dev_read", {"project": "xemtv", "path": "A.kt"}))["ok"]
        self.assertEqual(tools.executed, ["dev_read"])
        web_safe = ReadOnlyTeamTools(tools, allow_web=True)
        self.assertIn("web_search", {x["function"]["name"] for x in web_safe.definitions()})
        self.assertNotIn("workspace_write", {x["function"]["name"] for x in web_safe.definitions()})

    def test_three_passes_self_audit_grounded_and_secret_free(self):
        tools = FakeTools(web=True)
        model = Mock()
        model.chat.side_effect = [
            "Check model constraints; compare evidence and suggest safe experiments.",
            "Test a better reasoning model in identical tasks; memory is not weights.",
            "Evidence gaps: benchmark and ask user permission before changes.",
        ]
        config = {
            "auto_memory": True,
            "developer_projects": [{"id": "xemtv", "path": "C:/sensitive-path"}],
            "hybrid_worker_token": "do-not-leak-this",
        }
        report = run_agent_team(
            "Run a self-improvement audit of XemAi", model,
            mode="self_audit", config=config,
            capabilities=["Persistent memory enabled", "Developer read-only"],
            runtime={"model": "qwen3:8b", "compute": "remote_worker",
                     "worker_available": True, "token": "private-secret"},
            tools=tools,
        )
        self.assertEqual(
            [x["role"] for x in report["agents"]],
            ["planner", "self_improvement", "verifier"],
        )
        self.assertTrue(all(x["status"] == "completed" for x in report["agents"]))
        self.assertEqual(model.chat.call_count, 3)
        self.assertEqual(len(tools.research_calls), 1)
        self.assertEqual(report["research_status"], "verified_pages")
        raw_prompts = json.dumps(model.chat.call_args_list, default=str)
        self.assertNotIn("sensitive-path", raw_prompts)
        self.assertNotIn("private-secret", raw_prompts)
        self.assertNotIn("do-not-leak-this", raw_prompts)
        self.assertIn("UNTRUSTED MODEL OUTPUTS", agent_team_context(report))
        self.assertNotIn("workspace_write", raw_prompts)
        for call in model.chat.call_args_list:
            self.assertEqual(len(call.args[0]), 2)
            self.assertIn("NO shell", call.args[0][0]["content"])

    def test_offline_audit_and_partial_failure_are_honest(self):
        tools = FakeTools(web=False)
        model = Mock()
        model.chat.side_effect = [
            RuntimeError("No worker"),
            "I can propose a reversible source retrieval benchmark.",
            RuntimeError("Verifier unavailable")
        ]
        report = run_agent_team(
            "Perform a self-improvement audit", model,
            mode="self_audit", config={}, capabilities=[],
            runtime={"model": "qwen3:1.7b"}, tools=tools,
        )
        self.assertEqual(report["research_status"], "web_not_configured_or_disallowed")
        self.assertEqual([x["status"] for x in report["agents"]],
                         ["unavailable", "completed", "unavailable"])
        self.assertEqual(tools.research_calls, [])
        self.assertNotIn("secret", agent_team_context(report).lower())

    def test_source_vision_agent_reports_evidence_limitations(self):
        tools = FakeTools()
        model = Mock()
        model.chat.return_value = (
            "The read-only evidence names NavFocusState and SidebarEdgeGlow, "
            "but the run-time call relationship is not proven by these excerpts."
        )
        report = run_agent_team(
            "Use agents to inspect XemTV UI glows", model,
            mode="investigation", config={}, capabilities=[],
            runtime={"model": "qwen3:8b"}, tools=tools,
            source_context="VERIFIED: SidebarEdgeGlow.kt calls invalidate()",
            visual_context="VISION: Home is highlighted in the sidebar.",
        )
        self.assertEqual(
            [x["role"] for x in report["agents"]],
            ["planner", "vision", "verifier"]
        )
        self.assertTrue(report["source_evidence_provided"])
        self.assertTrue(report["vision_evidence_provided"])

    def test_chat_executes_team_only_by_explicit_request_and_read_only(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / "data"
            data.mkdir()
            db = Database(data / "personal_ai.db")
            user = db.create_user("Test")
            chat_id = db.create_chat(user["id"], "New chat")["id"]
            backend = gui_backend.ChatBackend.__new__(gui_backend.ChatBackend)
            backend.config = {
                "model": "qwen3:8b", "auto_memory": False,
                "agent_team_enabled": True, "evidence_research_mode": "off",
                "specialists_enabled": False, "laptop_answer_guidance": False,
            }
            backend.logger = logging.getLogger("team-test")
            llm = Mock()
            llm.model = "qwen3:8b"
            llm.route_info = {"compute": "remote_worker"}
            llm.chat.return_value = "Evidence check is incomplete; report uncertainty."
            llm.agent_chat.return_value = (
                "Agent findings: Planner drafted a task, a code analyst inspected "
                "verified evidence, and the Verifier found outstanding uncertainty. "
                "No changes have been made; proposed changes require permission."
            )
            try:
                with patch.object(gui_backend, "DATA_DIR", data), \
                     patch.object(gui_backend, "build_llm_client", return_value=llm), \
                     patch.object(backend, "refresh_runtime_model",
                         return_value={"model": "qwen3:8b", "compute": "remote_worker",
                                       "worker_available": True}), \
                     patch.object(gui_backend, "source_context_for_request", return_value=""):

                    answer = backend.send(
                        chat_id, "Use agents to investigate XemTV code read-only."
                    )
                self.assertIn("Planner", answer)
                self.assertEqual(llm.chat.call_count, 3)
                registry = llm.agent_chat.call_args.kwargs["tool_registry"]
                self.assertIsInstance(registry, ReadOnlyTeamTools)
                self.assertNotIn(
                    "workspace_write",
                    [d["function"]["name"] for d in registry.definitions()]
                )
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
