"""Regression: unrelated lesson examples must not hijack ordinary replies.

Replays (with invented data) the shape of a real conversation where XemAi
answered "what do you think of them?" about its updates with "what would you
like me to do with that other option?" and then a "birthday invitation for six
guests" that never appeared in the chat. Both phrases came from approved lesson
examples that were injected into every prompt regardless of relevance.
"""
from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import gui_backend, tools as tool_module
from app.conversation_learning import chat_command
from app.database import Database
from app.tools import ToolError, ToolRegistry


class OfflineTools(ToolRegistry):
    def web_search(self, *a, **k):
        raise ToolError("offline test")

    def web_fetch(self, *a, **k):
        raise ToolError("offline test")
from app.version import VERSION

LESSON = ("When asked about the other option for a birthday invitation for six guests, "
          "compare both venues before proceeding.")


class Worker:
    is_hybrid = False

    def __init__(self):
        self.model = "qwen3.5:9b-q8_0"
        self.route_info = {"model": self.model, "compute": "remote_worker", "worker_available": True}
        self.calls = []

    def discover_runtime_model(self, **_kwargs):
        return dict(self.route_info)

    def agent_chat(self, messages, **_kwargs):
        self.calls.append(list(messages))
        return "Here is a reply about what you asked."

    def chat(self, messages, *, json_mode=False):
        self.calls.append(list(messages))
        return json.dumps({"memories": []}) if json_mode else "Here is a reply about what you asked."

    def local_review(self, *a, **k):
        return None

    def specialist_pass(self, *a, **k):
        raise AssertionError("not expected")


class ContextLeakTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.data = self.root / "data"
        self.db = Database(self.data / "personal_ai.db")
        self.addCleanup(self.db.close)
        user = self.db.create_user("Owner")
        self.chat_id = self.db.create_chat(user["id"], "Updates")["id"]
        self.backend = gui_backend.ChatBackend.__new__(gui_backend.ChatBackend)
        self.backend.logger = logging.getLogger(self.id())
        self.backend.config = {"model": "qwen3:8b", "auto_memory": False}
        self.client = Worker()
        self.approve_lesson()

    def approve_lesson(self):
        chat_command(self.data, "conversation learning on")
        chat_command(self.data, "conversation learning correct: compare both venues", history=[
            {"role": "user", "content": "What about the other option for the party?"},
            {"role": "assistant", "content": "Sure."},
            {"role": "user", "content": "conversation learning correct: compare both venues"},
        ])
        reply = chat_command(self.data, f"conversation learning propose 1: conversation || {LESSON} || "
                                        "Owner wanted both options compared in a test dialogue.")
        self.assertNotIn("rejected", reply.lower())
        self.assertIn("owner-approved", chat_command(self.data, "conversation learning approve 1"))

    def send(self, text):
        self.client.calls.clear()
        with patch.object(gui_backend, "BASE_DIR", self.root), \
             patch.object(gui_backend, "DATA_DIR", self.data), \
             patch.object(gui_backend, "ToolRegistry", OfflineTools), \
             patch.object(gui_backend, "build_llm_client", return_value=self.client), \
             patch.object(tool_module, "load_ollama_api_key", return_value="offline-fixture"):
            answer = self.backend.send(self.chat_id, text)
        prompt = "\n".join(str(m.get("content")) for call in self.client.calls for m in call)
        return answer, prompt

    def test_lesson_scenarios_never_reach_unrelated_turns(self):
        for text in ["are you able to see what you've just had updated?", "what do you think of them?",
                     "what do you think of your new updates", "lets explore its details"]:
            answer, prompt = self.send(text)
            self.assertNotIn("birthday", prompt.lower(), text)
            self.assertNotIn("six guests", answer.lower(), text)

    def test_update_questions_are_answered_from_release_notes(self):
        answer, _ = self.send("are you able to see what you've just had updated?")
        self.assertIn(VERSION, answer)
        answer, prompt = self.send("what do you think of them?")
        # The follow-up is about those updates: release facts are what the reply is built on.
        self.assertTrue(VERSION in answer or VERSION in prompt, answer[:300])

    def test_a_genuinely_related_message_still_gets_the_lesson(self):
        _, prompt = self.send("Can you help me compare two venues for a birthday party with six guests?")
        self.assertIn("birthday invitation", prompt)
        self.assertIn("NOT part of this conversation", prompt)


if __name__ == "__main__":
    unittest.main()
