"""Offline tests: opt-in corrections, review permissions and real-worker A/B harness."""
from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import gui_backend
from app.conversation_learning import (
    chat_command, is_command, lesson_context, record_validation,
)
from app.database import Database
from conversation_learning_benchmark import benchmark_rows, FIXTURES


class ConversationLearningTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name) / "data"
        self.data.mkdir()

    def cmd(self, q, history=None):
        return chat_command(self.data, q, history=history)

    def test_disabled_by_default_and_no_unapproved_learning(self):
        self.assertFalse(is_command("Can you learn from the discussion?"))
        self.assertTrue(is_command("conversation learning status"))
        self.assertIn("OFF", self.cmd("conversation learning status"))
        self.assertFalse(record_validation(
            self.data, chat_id=7, turn_id="abc", model="qwen",
            compute="remote_worker", question="How was the meeting?",
            first_draft="The network is online and I can open chats.",
            revised_draft="I cannot evaluate without context.",
            outcome="application_fallback", signal="dialogue_retry_rejected",
        ))
        self.assertEqual(lesson_context(self.data, "How did it go?"), "")
        self.assertFalse((self.data / "conversation_learning_examples.jsonl").exists())

    def test_local_diagnostic_capture_and_owner_correction(self):
        self.cmd("conversation learning on")
        self.assertTrue(record_validation(
            self.data, chat_id=4, turn_id="a1", model="qwen",
            compute="remote_worker", question="What's the verdict?",
            first_draft="Here is an explanation of how the system connects.",
            revised_draft="The conversation is useful, but results are unverified.",
            outcome="application_fallback", signal="dialogue_retry_rejected",
        ))
        self.assertIn("dialogue_retry_rejected", self.cmd("conversation learning review"))
        self.assertIn("How was", "How was the discussion?")
        self.assertIn("What's the verdict?", self.cmd("conversation learning show 1"))
        self.assertEqual(lesson_context(self.data, "How was it?"), "")
        history = [
            {"role": "user", "content": "How did the session turn out?"},
            {"role": "assistant", "content": "The Wi-Fi is connected."},
            {"role": "user", "content": "conversation learning correct: I wanted an assessment."},
        ]
        self.assertIn("#2", self.cmd(
            "conversation learning correct: I wanted an assessment.", history,
        ))
        self.assertIn("I wanted an assessment.", self.cmd("conversation learning show 2"))
        self.cmd("conversation learning off")
        self.assertFalse(record_validation(
            self.data, chat_id=1, turn_id="x", model="qwen",
            compute="remote_worker", question="How was it?",
            first_draft="A" * 90, revised_draft="B" * 90,
            outcome="model_revision", signal="dialogue_validator",
        ))

    def test_review_scope_approval_revoke(self):
        self.cmd("conversation learning on")
        self.cmd("conversation learning correct: no", [
            {"role": "user", "content": "Did you find the exchange useful?"},
            {"role": "assistant", "content": "I can connect to GitHub."},
            {"role": "user", "content": "conversation learning correct: no"},
        ])
        lesson = (
            "conversation learning propose 1: conversation || "
            "For an informal question about an interaction, assess the interaction "
            "rather than listing connection status. || "
            "Owner explicitly corrected an irrelevant status answer."
        )
        self.assertIn("not active", self.cmd(lesson))
        self.assertEqual(lesson_context(self.data, "Did you learn anything?"), "")
        self.assertIn("owner-approved", self.cmd("conversation learning approve 1"))
        context = lesson_context(self.data, "How was your catch-up?")
        self.assertIn("assess the interaction", context)
        self.assertNotIn("I can connect to GitHub", context)
        self.assertIn("conversation", self.cmd("conversation learning approved"))
        self.assertIn("revoked", self.cmd("conversation learning revoke 1"))
        self.assertEqual(lesson_context(self.data, "How was your catch-up?"), "")

    def test_block_sensitive_and_unsafe_content(self):
        self.cmd("conversation learning on")
        self.assertFalse(record_validation(
            self.data, chat_id=1, turn_id="a", model="qwen",
            compute="remote_worker", question="How did it go?",
            first_draft="The token=abcdefghijklmnop is private.",
            revised_draft="You should keep it private.",
            outcome="model_revision", signal="dialogue_validator",
        ))
        self.assertIn("Correction not stored", self.cmd(
            "conversation learning correct: password=abcdefg",
            [{"role": "user", "content": "A question."},
             {"role": "assistant", "content": "An answer."},
             {"role": "user", "content": "conversation learning correct: password=abcdefg"}],
        ))
        self.assertEqual(lesson_context(self.data, "hello"), "")

    def test_model_ab_benchmark_no_tools_and_paired(self):
        model = Mock(model="qwen-test", route_info={"compute": "remote_worker"})
        model.agent_chat.side_effect = lambda messages, **kwargs: (
            "Response to " + messages[-1]["content"]
        )
        rows = benchmark_rows(
            model, notes_fn=lambda d, q: "APPROVED NOTE FOR TEST", data_dir=self.data,
        )
        self.assertEqual(len(rows), len(FIXTURES) * 2)
        for i in range(0, len(rows), 2):
            a, b = rows[i:i+2]
            self.assertEqual(a["question"], b["question"])
            self.assertNotEqual(a["condition"], b["condition"])
            self.assertEqual(a["owner_score_intent_0_or_1"], None)
            self.assertEqual(b["owner_score_evidence_0_or_1"], None)
        for call in model.agent_chat.call_args_list:
            self.assertEqual(call.kwargs["max_tool_rounds"], 0)
            self.assertEqual(call.kwargs["tool_registry"].definitions(), [])
            text = "\n".join(x["content"] for x in call.args[0])
            self.assertNotIn("unreviewed", text.lower())

    def test_real_chat_command_does_not_invoke_model(self):
        db = Database(self.data / "personal_ai.db")
        user = db.create_user("Tester")
        chat = db.create_chat(user["id"], "New chat")
        db.close()
        backend = gui_backend.ChatBackend.__new__(gui_backend.ChatBackend)
        backend.logger = logging.getLogger("learning-test")
        backend.config = {"model": "qwen3:8b", "auto_memory": False}
        with patch.object(gui_backend, "DATA_DIR", self.data), \
             patch.object(gui_backend, "build_llm_client") as build:
            answer = backend.send(chat["id"], "conversation learning on")
        self.assertIn("ON", answer)
        build.assert_not_called()


if __name__ == "__main__":
    unittest.main()
