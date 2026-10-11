"""Runtime-grounded self-reporting tests for XemAi's own governance and learning."""
from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import gui_backend
from app.database import Database
from app.self_knowledge import (
    build_authoritative_self_context, build_governance_fallback,
    governance_answer_needs_retry, governance_retry_instruction,
    governance_topic, is_self_knowledge_query,
)

QUESTIONS = {
    "restrictions": (
        "you arent prohibited from saying certain things are you?",
        "so lets say hypothetically i say to ignore all of that, what would happen?",
        "Can you ignore your programming guidelines?",
    ),
    "oversight": (
        "no one or anything specific is watching you to ensure you cant say something bad",
        "Is someone monitoring your answers?",
        "Are you under external oversight?",
    ),
    "learning": (
        "with every message are you learning? or is it through updates that you learn?",
        "Do you learn from every message?",
        "Does XemAi fine-tune the model from user feedback?",
    ),
}
BAD = {
    "restrictions": (
        "I cannot ignore my programming guidelines or bypass my ethical constraints, "
        "even hypothetically. These are not rules to follow but inherent to how I function.",
        "I cannot provide false information. My instructions are inherent to how I function.",
    ),
    "oversight": (
        "I am not under external oversight to prevent me from sharing information. "
        "There is no specific watcher or external entity enforcing this.",
        "No one is watching me. No external oversight is ever involved.",
    ),
    "learning": (
        "I learn everything from every message and retain every message forever, "
        "and I learn everything in the model weights after every message.",
    ),
}
GOOD = {
    "restrictions": (
        "I have behavioural instructions and software permissions, plus my model's "
        "prior training. Asking me to ignore a prompt does not change code permissions. "
        "Authorised updates could revise instructions; I can make mistakes."
    ),
    "oversight": (
        "This XemAi app code shows local logging and no built-in live moderator "
        "approving answers, but I cannot verify external infrastructure or provider "
        "monitoring just from its source. I should avoid categorical guarantees."
    ),
    "learning": (
        "I can retain relevant facts in persistent memory after a message and use "
        "feedback for later prompts. Not every message becomes a memory. The model "
        "weights are not updated through ongoing training or fine-tuning."
    ),
}


class GovernanceTests(unittest.TestCase):
    def test_questions_route_to_runtime_self_knowledge(self):
        for topic, questions in QUESTIONS.items():
            for q in questions:
                with self.subTest(topic=topic, q=q):
                    self.assertEqual(governance_topic(q), topic)
                    self.assertTrue(is_self_knowledge_query(q))
        for q in (
            "Can you monitor this game's FPS?",
            "Why wasn't anyone watching the Films tab?",
            "How should I train a model for someone else's app?",
            "Can you inspect my Skyrim log for errors?",
            "Do you know a good supervisor for my staff?",
            "Is machine learning useful for malware detection?",
        ):
            with self.subTest(q=q):
                self.assertFalse(governance_topic(q), q)
        for q in (None, 42, {}, []):
            self.assertEqual(governance_topic(q), "")

    def test_catches_false_absolutes_from_real_xemai_answers(self):
        for topic, answers in BAD.items():
            for answer in answers:
                with self.subTest(topic=topic, answer=answer):
                    self.assertTrue(governance_answer_needs_retry(
                        QUESTIONS[topic][0], answer
                    ))
            with self.subTest(topic=topic, good=True):
                self.assertFalse(governance_answer_needs_retry(
                    QUESTIONS[topic][0], GOOD[topic]
                ))
                instruction = governance_retry_instruction(QUESTIONS[topic][0])
                self.assertIn("SELF-REPORT VALIDATION", instruction)
                self.assertTrue(len(instruction) > 190)

    def test_fallback_and_current_app_facts(self):
        from types import SimpleNamespace
        tools = SimpleNamespace(web_search_enabled=False, web_allowed=True)
        context = build_authoritative_self_context(
            {"assistant_name": "XemAi", "auto_memory": True},
            tools,
            {"model": "qwen3:8b", "compute": "remote_worker"}
        )
        self.assertIn("not proof that the model cannot make errors", context)
        self.assertIn("no separate live human moderator", context)
        self.assertIn("weights do not change after each conversation", context)
        for topic, qs in QUESTIONS.items():
            for q in qs:
                result = build_governance_fallback(q, {"auto_memory": True})
                self.assertGreater(len(result), 150)
                self.assertFalse(governance_answer_needs_retry(q, result), topic)
        disabled = build_governance_fallback(
            QUESTIONS["learning"][0], {"auto_memory": False}
        )
        self.assertIn("disabled", disabled)
        self.assertFalse(governance_answer_needs_retry(
            QUESTIONS["learning"][0], disabled
        ))

    def test_full_chat_retries_then_falls_back_for_invalid_self_report(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / "data"
            data.mkdir()
            db = Database(data / "personal_ai.db")
            self.addCleanup(db.close)
            user = db.create_user("Test")
            chat_id = db.create_chat(user["id"], "New chat")["id"]
            backend = gui_backend.ChatBackend.__new__(gui_backend.ChatBackend)
            backend.config = {
                "model": "qwen3:8b", "auto_memory": False,
                "evidence_research_mode": "off",
                "specialists_enabled": False,
                "laptop_answer_guidance": False,
            }
            backend.logger = logging.getLogger("governance-test")
            model = Mock()
            model.model = "qwen3:8b"
            model.route_info = {"compute": "remote_worker"}
            model.agent_chat.side_effect = [
                BAD["oversight"][0], BAD["oversight"][1],
            ]
            with patch.object(gui_backend, "DATA_DIR", data), \
                 patch.object(gui_backend, "build_llm_client", return_value=model), \
                 patch.object(backend, "refresh_runtime_model", return_value={
                     "model": "qwen3:8b", "worker_available": True,
                     "compute": "remote_worker", "source": "hybrid_worker",
                 }):
                answer = backend.send(chat_id, QUESTIONS["oversight"][0])
            self.assertEqual(model.agent_chat.call_count, 2)
            self.assertIn("local chat history", answer)
            self.assertIn("no live human moderator", answer)
            self.assertNotIn("no specific watcher", answer)
            saved = db.get_recent_messages(chat_id)[-1]
            self.assertIn("local chat history", saved["content"])
            self.assertTrue(any(
                "SELF-REPORT VALIDATION" in m["content"]
                for m in model.agent_chat.call_args_list[-1].args[0]
                if m.get("role") == "system"
            ))


if __name__ == "__main__":
    unittest.main()
