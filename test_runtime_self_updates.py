"""Self-update questions and same-chat corrections use installed app facts, not web."""
from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import gui_backend
from app.capability_inventory import direct_answer, inventory, local_question_type
from app.database import Database
from app.self_knowledge import RELEASE_HISTORY, followup_self_topic
from app.version import VERSION


class LiveSelfUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / "data"
        self.data.mkdir()
        db = Database(self.data / "personal_ai.db")
        self.user = db.create_user("Tester")
        self.chat = db.create_chat(self.user["id"], "XemAi questions")["id"]
        db.close()
        self.backend = gui_backend.ChatBackend.__new__(gui_backend.ChatBackend)
        self.backend.logger = logging.getLogger("self-update-regression")
        self.backend.config = {
            "model": "qwen3:8b", "auto_memory": False, "agent_team_enabled": True,
            "ai_watch_enabled": False, "specialists_enabled": False,
            "laptop_answer_guidance": False, "evidence_research_mode": "auto",
        }
        self.runtime = {
            "model": "qwen3:8b", "compute": "remote_worker",
            "worker_available": True,
        }
        self.model = Mock()
        self.model.model = "qwen3:8b"
        self.model.route_info = {"compute": "remote_worker"}

    def test_current_release_must_be_in_bundled_history(self):
        # Regression gate: future version bumps must also update release
        # history or the assistant will again describe an old release.
        self.assertIn(VERSION, dict(RELEASE_HISTORY))
        self.assertEqual(RELEASE_HISTORY[-1][0], VERSION)
        data = inventory(self.backend.config, self.runtime, RELEASE_HISTORY)
        answer = direct_answer(data, "latest_release")
        self.assertIn("XemAi v" + VERSION, answer)
        self.assertIn(dict(RELEASE_HISTORY)[VERSION], answer)
        self.assertNotIn("can't access", answer.lower())
        self.assertIn("underlying model weights", answer)

    def test_natural_update_wordings_and_non_xemai_projects(self):
        for prompt in (
            "Can you see what your most recent update was?",
            "What was the last update to XemAi?",
            "Do you know your newest release?",
            "What's your latest version?",
        ):
            # Only the first and common possessive forms are guaranteed by
            # the direct handler; other phrasings still use self knowledge.
            self.assertTrue(
                local_question_type(prompt) or gui_backend.is_self_knowledge_query(prompt),
                prompt,
            )
        for prompt in (
            "Could you check the latest Skyrim update?",
            "Could you explain Vortex's update history?",
            "What was your advice about SKSE's last update?",
        ):
            self.assertNotEqual(local_question_type(prompt), "latest_release")

    def test_followup_topic_requires_immediate_self_context(self):
        history = [
            {"role":"user", "content":"Can you see what your most recent update was?"},
            {"role":"assistant", "content":"No, I am only a model with no update log."},
            {"role":"user", "content":"I'm pretty sure you do."},
        ]
        self.assertEqual(followup_self_topic("I'm pretty sure you do.", history), "latest_release")
        self.assertEqual(followup_self_topic("That's wrong, check again", history), "latest_release")
        self.assertEqual(followup_self_topic("Sure", history), "latest_release")
        history[0]["content"] = "What was your favourite Skyrim mod recommendation?"
        self.assertEqual(followup_self_topic("I'm pretty sure you do.", history), "")
        self.assertEqual(followup_self_topic(
            "I'm pretty sure you do.", [
                {"role": "user", "content": "Can you see what your most recent update was?"},
                {"role": "user", "content": "I'm pretty sure you do."},
            ],
        ), "")

    def test_real_backend_corrects_prior_denial_without_web_or_model(self):
        db = Database(self.data / "personal_ai.db")
        db.add_message(self.chat, "user", "Can you see what your most recent update was?")
        db.add_assistant_message(
            self.chat, "No, I can't see my own update history.",
            model="qwen3:8b", compute_source="remote_worker",
        )
        db.close()
        with patch.object(gui_backend, "DATA_DIR", self.data), \
             patch.object(gui_backend, "build_llm_client", return_value=self.model), \
             patch.object(self.backend, "refresh_runtime_model", return_value=self.runtime), \
             patch.object(gui_backend, "should_research_query",
                          side_effect=AssertionError("No unrelated web searching")), \
             patch.object(gui_backend, "source_context_for_request", return_value=""):
            answer = self.backend.send(self.chat, "I'm pretty sure you do.")
        self.assertIn("You're right to challenge", answer)
        self.assertIn("XemAi v" + VERSION, answer)
        self.assertIn("release notes", answer.lower())
        self.assertNotIn("unrestricted computer", answer.lower())
        self.model.agent_chat.assert_not_called()


if __name__ == "__main__":
    unittest.main()
