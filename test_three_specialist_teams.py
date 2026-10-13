"""Regression tests for the three bounded opt-in specialist teams."""
from __future__ import annotations

import unittest

from app.agent_team_catalog import TEAM_SPECS, TEAM_ROLE_RULES, requested_specialist_team
from app.agent_team import requested_agent_mode


class NewSpecialistTeamTests(unittest.TestCase):
    EXPECTED = {
        "conversation_specialist": ("intent_interpreter", "continuity_critic", "dialogue_verifier"),
        "task_execution_planner": ("objective_mapper", "step_planner", "completion_verifier"),
        "performance_optimiser": ("latency_analyst", "routing_critic", "performance_verifier"),
    }

    def test_all_roles_registered(self):
        for name, roles in self.EXPECTED.items():
            with self.subTest(team=name):
                self.assertEqual(TEAM_SPECS[name]["roles"], roles)
                for role in roles:
                    self.assertIn(role, TEAM_ROLE_RULES)

    def test_explicit_requests_activate(self):
        for command, team in [
            ("run conversation specialist team", "conversation_specialist"),
            ("use dialogue specialist agents", "conversation_specialist"),
            ("run task execution planner team", "task_execution_planner"),
            ("run performance optimizer team", "performance_optimiser"),
            ("run performance optimiser team", "performance_optimiser"),
            ("run conversation specialist", "conversation_specialist"),
            ("use the dialogue specialist", "conversation_specialist"),
            ("run task execution planner", "task_execution_planner"),
            ("please start the performance optimiser", "performance_optimiser"),
        ]:
            with self.subTest(command=command):
                self.assertEqual(requested_specialist_team(command), team)
                self.assertEqual(requested_agent_mode(command), team)

    def test_discussion_does_not_activate(self):
        for message in [
            "Can the conversation specialist help?",
            "What does the performance optimizer do?",
            "Tell me about task execution planners",
            "run conversation specialist team without agents",
            "run conversation specialist without agents",
            "Should I run conversation specialist?",
            "How can I run task execution planner?",
            "run performance optimiser maybe",
        ]:
            with self.subTest(message=message):
                self.assertEqual(requested_agent_mode(message), "")

    def test_disabled_teams_do_not_activate(self):
        self.assertEqual(requested_agent_mode("run conversation specialist team", enabled=False), "")


if __name__ == "__main__":
    unittest.main()
