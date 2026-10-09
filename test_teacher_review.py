"""Optional local teacher reviews preserve durable answer provenance and drafts."""
from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import gui_backend, tools as tool_module
from app.database import Database


DRAFT = (
    "Set aside a short study session on five days each week. Choose one specific "
    "topic for each session and use practice questions to check what you recall. "
    "Leave room for breaks and adjust the schedule to your workload. At the end "
    "of the week, review which topics need another pass and plan the next week. "
    "This is a suggested routine rather than a guarantee of a particular result."
)
REVIEWED = "Use short practice sessions, leave time for rest, and adjust the plan to your needs."


class TeacherModel:
    is_hybrid = True

    def __init__(self, outcome):
        self.model = "qwen3:8b"
        self.route_info = {"model": self.model, "compute": "remote_worker", "worker_available": True}
        self.outcome = outcome
        self.review_calls = []
        self.evidence_attempted = False

    def discover_runtime_model(self, **_kwargs):
        return dict(self.route_info)

    def agent_chat(self, _messages, *, tool_registry, **_kwargs):
        if self.evidence_attempted:
            tool_registry.evidence_attempted = True
        return DRAFT

    def review_answer(self, question, draft):
        self.review_calls.append((question, draft))
        if isinstance(self.outcome, Exception):
            # A later route change must not relabel the successful first-pass draft.
            self.model = "qwen3:1.7b"
            self.route_info = {"model": self.model, "compute": "local_host"}
            raise self.outcome
        return self.outcome


class TeacherReviewTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / "data"
        self.db = Database(self.data / "personal_ai.db")
        self.addCleanup(self.db.close)
        user = self.db.create_user("Test")
        self.chat_id = self.db.create_chat(user["id"], "Study routine")["id"]
        self.backend = gui_backend.ChatBackend.__new__(gui_backend.ChatBackend)
        self.backend.config = {"model": "qwen3:8b", "auto_memory": False,
                               "teacher_enabled": True, "teacher_min_answer_chars": 280}
        self.backend.logger = logging.getLogger("teacher-review-test")
        self.client = TeacherModel({"ok": True, "answer": REVIEWED, "model": "qwen3:30b"})

    def send(self, text="Suggest a weekly study routine."):
        with patch.object(gui_backend, "BASE_DIR", self.root), \
             patch.object(gui_backend, "DATA_DIR", self.data), \
             patch.object(gui_backend, "build_llm_client", return_value=self.client), \
             patch.object(tool_module, "load_ollama_api_key", return_value=None):
            return self.backend.send(self.chat_id, text)

    def assert_saved_answer(self, content, model="qwen3:8b"):
        messages = self.db.get_recent_messages(self.chat_id)
        self.assertEqual(messages[-1]["content"], content)
        self.assertEqual(messages[-1]["inference_model"], model)
        self.assertEqual(messages[-1]["inference_compute"], "remote_worker")
        self.assertFalse(any(message["content"].startswith(gui_backend.REPLY_ERROR_PREFIX)
                             for message in messages))

    def test_successful_review_persists_actual_teacher_model_as_worker_answer(self):
        self.assertEqual(self.send(), REVIEWED)
        self.assertEqual(self.client.review_calls, [("Suggest a weekly study routine.", DRAFT)])
        self.assert_saved_answer(REVIEWED, "qwen3:30b")

    def test_teacher_failure_keeps_successful_draft_and_original_provenance(self):
        self.client.outcome = RuntimeError("Teacher unavailable")
        self.assertEqual(self.send(), DRAFT)
        self.assert_saved_answer(DRAFT)

    def test_missing_or_invalid_review_metadata_cannot_discard_the_draft(self):
        outcomes = [None, {}, {"answer": REVIEWED},
                    {"answer": REVIEWED, "model": "bad\nlabel"},
                    {"answer": REVIEWED, "model": "x" * 257},
                    {"answer": 42, "model": "qwen3:30b"}]
        for outcome in outcomes:
            with self.subTest(outcome=outcome):
                self.client.outcome = outcome
                self.assertEqual(self.send(), DRAFT)
                self.assert_saved_answer(DRAFT)

    def test_invalid_optional_threshold_uses_safe_default(self):
        for invalid in (None, "not a number", float("inf")):
            with self.subTest(invalid=invalid):
                self.backend.config["teacher_min_answer_chars"] = invalid
                self.assertEqual(self.send(), REVIEWED)
                self.assert_saved_answer(REVIEWED, "qwen3:30b")

    def test_disabled_teacher_or_shorter_answer_policy_skips_review(self):
        for configuration in ({"teacher_enabled": False}, {"teacher_review_mode": " off "},
                              {"teacher_min_answer_chars": 1000}):
            with self.subTest(configuration=configuration):
                self.backend.config.update(teacher_enabled=True, teacher_review_mode="auto",
                                           teacher_min_answer_chars=280)
                self.backend.config.update(configuration)
                self.assertEqual(self.send(), DRAFT)
                self.assertEqual(self.client.review_calls, [])
                self.assert_saved_answer(DRAFT)

    def test_research_attempted_and_self_description_turns_skip_review(self):
        self.client.evidence_attempted = True
        self.assertEqual(self.send(), DRAFT)
        self.client.evidence_attempted = False
        with patch.object(gui_backend, "looks_like_stale_self_description", return_value=False):
            self.assertEqual(self.send("What version are you?"), DRAFT)
        self.assertEqual(self.client.review_calls, [])
        self.assert_saved_answer(DRAFT)


if __name__ == "__main__":
    unittest.main()
