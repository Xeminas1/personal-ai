"""Supervised specialist-team routing, evidence isolation and provenance tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from app.agent_team import requested_agent_mode, run_agent_team, ReadOnlyTeamTools
from app.agent_team_catalog import TEAM_SPECS, TEAM_ROLE_RULES, requested_specialist_team
from app.database import Database, _validate_specialist_roles


class DeniedTools:
    web_allowed = False
    web_search_enabled = False
    def definitions(self):
        return [{"type": "function", "function": {"name": "workspace_write"}}]
    def execute(self, name, arguments):
        raise AssertionError("No tools may run through the simulated team")


class TeamCatalogTests(unittest.TestCase):
    def test_five_named_imperatives_route_correctly(self):
        commands = {
            "Run the memory & continuity team to review this thread": "memory_continuity",
            "Use your software engineering team to inspect the project": "software_engineering",
            "Start the research and verification team to check evidence": "research_verification",
            "Invoke the learning & benchmarks team to assess feedback": "learning_benchmarks",
            "Please run the design and accessibility team to review XemTV": "design_accessibility",
            "Run the coding team to examine approved source": "software_engineering",
        }
        for message, expected in commands.items():
            with self.subTest(message=message):
                self.assertEqual(requested_specialist_team(message), expected)
                self.assertEqual(requested_agent_mode(message), expected)

    def test_questions_and_opt_outs_do_not_spawn_teams(self):
        for message in (
            "Could we run a memory team?",
            "Would a research team be useful?",
            "Tell me about the learning team.",
            "Please do not run agents for this.",
            "Run the memory team without any agents.",
            "Use no agents in your response.",
            "How would a coding team work?",
            "Run a self-improvement audit of XemAi with no agents.",
        ):
            with self.subTest(message=message):
                self.assertEqual(requested_specialist_team(message), "")
                self.assertEqual(requested_agent_mode(message), "")

    def test_each_team_has_three_distinct_known_roles(self):
        original_teams = {
            "memory_continuity", "software_engineering", "research_verification",
            "learning_benchmarks", "design_accessibility",
        }
        self.assertTrue(original_teams.issubset(TEAM_SPECS))
        for name, spec in TEAM_SPECS.items():
            with self.subTest(team=name):
                self.assertEqual(len(spec["roles"]), 3)
                self.assertEqual(len(set(spec["roles"])), 3)
                for role in spec["roles"]:
                    self.assertIn(role, TEAM_ROLE_RULES)

    def test_three_no_tool_passes_no_autonomous_actions(self):
        for mode, spec in TEAM_SPECS.items():
            with self.subTest(mode=mode):
                llm = Mock()
                llm.chat.return_value = (
                    "The evidence is incomplete, so this is a proposal only; "
                    "any consequential action needs additional explicit approval."
                )
                report = run_agent_team(
                    "Use the relevant named team to review the supplied evidence",
                    llm, mode=mode, config={"agent_teams_enabled": True},
                    capabilities=["Read-only testing"], runtime={"model": "qwen3:8b"},
                    tools=DeniedTools(),
                    memory_context="PRIVATE_MEMORY_MARKER",
                    history_context="PRIVATE_CHAT_MARKER",
                    learning_context="AGGREGATE_RATING_MARKER",
                    research_context="SOURCE_EXCERPT_MARKER",
                    source_context="READ_ONLY_CODE_MARKER",
                    visual_context="SUPPLIED_VISUAL_MARKER",
                )
                self.assertEqual(report["team_name"], spec["title"])
                self.assertEqual([row["role"] for row in report["agents"]], list(spec["roles"]))
                self.assertEqual(len(llm.chat.call_args_list), 3)
                prompt = json.dumps(llm.chat.call_args_list, default=str)
                self.assertNotIn("tools", str(llm.chat.call_args_list[0].args[0][0]))
                self.assertEqual("PRIVATE_MEMORY_MARKER" in prompt, mode == "memory_continuity")
                self.assertEqual("PRIVATE_CHAT_MARKER" in prompt, mode == "memory_continuity")
                self.assertEqual("AGGREGATE_RATING_MARKER" in prompt, mode == "learning_benchmarks")
                self.assertEqual("SOURCE_EXCERPT_MARKER" in prompt, mode == "research_verification")
                for role in spec["roles"]:
                    self.assertIn(role, prompt)

    def test_config_disables_new_teams_without_breaking_old_audits(self):
        with self.assertRaises(ValueError):
            run_agent_team(
                "Run memory team", Mock(), mode="memory_continuity",
                config={"agent_teams_enabled": False},
                capabilities=[], runtime={}, tools=DeniedTools()
            )
        model = Mock()
        model.chat.return_value = (
            "Only supplied evidence was used. No benchmark was performed."
        )
        result = run_agent_team(
            "Run a self-improvement audit", model, mode="self_audit",
            config={"agent_teams_enabled": False},
            capabilities=[], runtime={}, tools=DeniedTools()
        )
        self.assertEqual(len(result["agents"]), 3)

    def test_private_user_roles_now_persist_safely(self):
        allowed = ["conversation", "conversation_reviewer"]
        self.assertEqual(_validate_specialist_roles(allowed), allowed)
        self.assertEqual(_validate_specialist_roles(["social"]), ["social"])
        with tempfile.TemporaryDirectory() as directory:
            db = Database(Path(directory) / "db.sqlite3")
            try:
                user = db.create_user("Test")
                chat = db.create_chat(user["id"], "Conversation")
                db.add_assistant_message(
                    chat["id"], "Response from two agents.",
                    specialist_roles=allowed
                )
                rows = db.get_recent_messages(chat["id"], limit=4)
                self.assertEqual(rows[-1]["specialist_roles"], allowed)
            finally:
                db.close()
        with self.assertRaises(ValueError):
            _validate_specialist_roles(["unapproved_system_agent"])


if __name__ == "__main__":
    unittest.main()
