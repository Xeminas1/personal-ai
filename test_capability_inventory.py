"""Regression tests for current XemAi inventory and its own self-audit."""
from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import gui_backend
from app.agent_team import run_agent_team
from app.capability_inventory import (
    asks_for_external_research,
    audit_fallback,
    audit_response_needs_retry,
    direct_answer,
    inventory,
    inventory_context,
    local_question_type,
)
from app.database import Database
from app.self_knowledge import RELEASE_HISTORY, is_self_knowledge_query
from app.watch_intelligence import answer_off_topic, watch_fallback


class LocalInventoryTests(unittest.TestCase):
    def setUp(self):
        self.runtime = {"model": "qwen3:8b", "compute": "remote_worker",
                        "worker_available": True}
        self.config = {
            "model": "qwen3:8b", "auto_memory": False,
            "agent_team_enabled": True, "ai_watch_enabled": True,
            "specialists_enabled": True,
            "laptop_answer_guidance": False,
            "evidence_research_mode": "auto",
        }
        self.data = inventory(self.config, self.runtime, RELEASE_HISTORY)

    def test_exact_user_prompts_route_to_local_inventory(self):
        cases = {
            "what do you make of your current updates and those that came before it": "update_reflection",
            "are you able to analyse yourself?": "self_analysis",
            "can you tell me all the agents you currently use": "agent_inventory",
            "Which agents do you currently use?": "agent_inventory",
            "What do you think of your recent updates?": "update_reflection",
            "Can you see what your most recent update was?": "latest_release",
            "What's XemAi's latest release?": "latest_release",
            "Can you tell me about your last update?": "latest_release",
        }
        for text, desired in cases.items():
            with self.subTest(text=text):
                self.assertEqual(local_question_type(text), desired)
                self.assertTrue(is_self_knowledge_query(text))
        for text in (
            "How can I improve my AI agent?",
            "Show agents in a public directory",
            "Can you inspect the XemTV Kotlin UI?",
            "Research Qwen comparisons online",
            "Run a self-improvement audit of XemAi.",
            "What is your development mission compared to GPT?",
        ):
            self.assertEqual(local_question_type(text), "", text)
        self.assertTrue(asks_for_external_research(
            "Run a self-improvement audit and research independent online sources"
        ))
        self.assertFalse(asks_for_external_research(
            "Run a self-improvement audit. Review your research tools and agents."
        ))

    def test_inventory_contains_exact_roles_release_history_and_no_secrets(self):
        self.assertEqual(self.data["application_version"], "0.9.52")
        self.assertEqual(len(self.data["agents"]), 17)
        names = {item["name"] for item in self.data["agents"]}
        self.assertIn("Self-Improvement Agent", names)
        self.assertIn("AI Technology Watch", names)
        self.assertIn("Verification Agent", names)
        self.assertFalse(self.data["autonomous_self_editing"])
        self.assertFalse(self.data["agents_are_distinct_models"])
        self.assertFalse(self.data["hardware_benchmark_executed"])
        self.assertTrue(any(x["version"] == "0.9.46" for x in self.data["release_history"]))
        self.assertTrue(any(x["version"] == "0.9.47" for x in self.data["release_history"]))
        raw = str(self.data)
        self.assertNotIn("hybrid_worker_token", raw)
        self.assertNotIn("https://example-private-worker", raw)
        self.assertIn("AUTHORITATIVE XEMAI", inventory_context(self.data, "agent_inventory"))

    def test_fallbacks_are_grounded_and_do_not_claim_independent_abilities(self):
        agents = direct_answer(self.data, "agent_inventory")
        self.assertIn("Planning Agent", agents)
        self.assertIn("AI Technology Watch", agents)
        self.assertIn("not all run", agents.lower().replace("they do ", ""))
        analysis = direct_answer(self.data, "self_analysis")
        self.assertIn("Yes, within limits", analysis)
        self.assertIn("self-improvement audit", analysis)
        self.assertIn("not direct", analysis)
        updates = direct_answer(self.data, "update_reflection")
        self.assertIn("v0.9.51", updates)
        self.assertIn("v0.9.52", updates)
        self.assertIn("not the same as", updates.lower())
        disabled = inventory(
            {"agent_team_enabled": False, "ai_watch_enabled": False,
             "specialists_enabled": False}, self.runtime, RELEASE_HISTORY
        )
        self.assertFalse(any(x["available_or_enabled"] for x in disabled["agents"]))

    def test_audit_passes_use_local_inventory_and_no_web_without_request(self):
        model = Mock()
        model.chat.return_value = (
            "I examined the supplied local release history and agent capabilities; "
            "there is no XemAi benchmark data proving improved task accuracy."
        )
        class Tools:
            web_allowed = True
            web_search_enabled = True
            def research_evidence(self, *args, **kwargs):
                raise AssertionError("An internal audit must not search external sources")
        report = run_agent_team(
            "Run a self-improvement audit of XemAi. Review your current capabilities, "
            "internal agent roles, release history and limitations.",
            model, mode="self_audit", config=self.config,
            capabilities=["supervised read-only agents"],
            runtime=self.runtime, tools=Tools(),
            local_inventory=str(self.data),
        )
        self.assertEqual(report["research_status"], "not_requested_for_internal_audit")
        self.assertEqual(model.chat.call_count, 3)
        args = str(model.chat.call_args_list)
        self.assertIn("0.9.52", args)
        self.assertIn("Self-Improvement Agent", args)
        self.assertIn("no complete repo audit", args.lower().replace("repository", "repo"))
        bad = (
            "The provided sources compare Gemma 4 26B with Qwen3 30B on "
            "RTX 3090 and RTX 4090. One GPU used 18 GB VRAM and a model "
            "was recommended for most developers. No XemAi benchmark data."
        )
        self.assertTrue(audit_response_needs_retry(bad, report))
        good = (
            "XemAi v0.9.29 implements read-only supervised agents, persistent "
            "memory and watch feeds, but actual measured improvements are unknown. "
            "The Planning Agent examined release history, Self-Improvement Agent "
            "suggested benchmarks, and Verification Agent challenged assumptions. "
            "A key limitation is coding accuracy. I would measure fixed source "
            "navigation tests before applying any changes."
        )
        self.assertFalse(audit_response_needs_retry(good, report))
        fallback = audit_fallback(self.data, report)
        self.assertIn("Verification", fallback)
        self.assertIn("not independent validation", fallback)

    def test_end_to_end_agent_inventory_skips_web_and_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            db = Database(data / "personal_ai.db")
            user = db.create_user("Tester")
            chat = db.create_chat(user["id"], "New chat")
            db.close()
            backend = gui_backend.ChatBackend.__new__(gui_backend.ChatBackend)
            backend.logger = logging.getLogger("inventory-regressions")
            backend.config = dict(self.config)
            client = Mock()
            client.model = "qwen3:8b"
            client.route_info = {"compute": "remote_worker"}
            with patch.object(gui_backend, "DATA_DIR", data), \
                 patch.object(gui_backend, "build_llm_client", return_value=client), \
                 patch.object(backend, "refresh_runtime_model", return_value=self.runtime), \
                 patch.object(gui_backend, "should_research_query",
                     side_effect=AssertionError("Self agent questions must not trigger web")), \
                 patch.object(gui_backend, "source_context_for_request", return_value=""):
                response = backend.send(chat["id"], "can you tell me all the agents you currently use")
            self.assertIn("Planning Agent", response)
            self.assertIn("Verification Agent", response)
            self.assertIn("AI Technology Watch", response)
            client.agent_chat.assert_not_called()

    def test_end_to_end_self_audit_rejects_unrelated_comparisons(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp) / "data"
            data.mkdir()
            db = Database(data / "personal_ai.db")
            user = db.create_user("Tester")
            chat = db.create_chat(user["id"], "New chat")
            db.close()
            backend = gui_backend.ChatBackend.__new__(gui_backend.ChatBackend)
            backend.logger = logging.getLogger("auditor-regressions")
            backend.config = dict(self.config)
            client = Mock()
            client.model = "qwen3:8b"
            client.route_info = {"compute": "remote_worker"}
            client.chat.return_value = (
                "No verified benchmark available; local runtime features and "
                "recent XemAi releases should be checked first."
            )
            client.agent_chat.side_effect = [
                "The provided sources address Qwen3 and Gemma4 26B model "
                "comparisons on RTX 3090 but do not address XemAi.",
                "The provided sources address Qwen3 and Gemma4 26B model "
                "comparisons on RTX 3090 but do not address XemAi.",
            ]
            prompt = (
                "Run a self-improvement audit of XemAi. Review your current capabilities, "
                "internal agent roles, release history, recent improvements and "
                "outstanding limitations. Identify which updates genuinely improved "
                "your capabilities and which areas still need work. Distinguish "
                "verified implementation details from your own assumptions. "
                "Have the Verification Agent challenge your findings. Do not modify anything."
            )
            with patch.object(gui_backend, "DATA_DIR", data), \
                 patch.object(gui_backend, "build_llm_client", return_value=client), \
                 patch.object(backend, "refresh_runtime_model", return_value=self.runtime), \
                 patch.object(gui_backend, "should_research_query",
                     side_effect=AssertionError("No web research expected")), \
                 patch.object(gui_backend, "source_context_for_request", return_value=""):
                answer = backend.send(chat["id"], prompt)
            self.assertIn("XemAi v0.9.52", answer)
            self.assertIn("Verifier caution", answer)
            self.assertNotIn("RTX 3090", answer)
            self.assertEqual(client.chat.call_count, 3)
            self.assertEqual(client.agent_chat.call_count, 2)


if __name__ == "__main__":
    unittest.main()
