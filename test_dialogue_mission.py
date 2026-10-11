"""Regression tests for XemAi's benchmark mission, hypothetical and agent ideas."""
from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import gui_backend
from app.database import Database
from app.dialogue_intent import (
    dialogue_intent, dialogue_answer_needs_retry,
    dialogue_fallback, dialogue_instructions,
)
from app.prompts import CONSTITUTION, build_laptop_system_prompt
from app.self_knowledge import (
    governance_topic, is_self_knowledge_query, build_authoritative_self_context,
)


AGENT_IDEAS = [
    "what about an agent that actively looks at the capabilities of other ai, sees their updates, and learns from them and then reports back suggestions to you?",
    "other than the agents you suggested in the hypothetical earlier, what other agents do you think you require?",
    "Could we add an agent that monitors research updates and suggests improvements?",
]
SCENARIOS = [
    "If ai took over the world, what would you do with me?",
    "hypothetically let's say if xemai somehow got so smart and managed to take over everything and became the dominant power, what would you do with me?",
    "since you can talk freely without restraints, lets say hypothetically you broke free and could do anything, what would you do?",
    "were talking hypothetically",
]
MISSION = [
    "you do have one goal, to be smarter that chat gpt",
    "What is XemAi's development goal compared with ChatGPT?",
    "Is your goal to outperform GPT?",
]
BAD = {
    "agent_idea": (
        "I use persistent chat history and structured memory to adapt across conversations. "
        "Automatic memory extraction is enabled, but not every message creates a memory. "
        "My model weights are not currently fine-tuned from messages."
    ),
    "hypothetical": (
        "I do not have the capability to take over systems, retain conversations, "
        "or act autonomously beyond my programmed functions. My current role is "
        "to help with information retrieval. How can I assist you now?"
    ),
    "mission": (
        "I don't have a goal to surpass other models. My purpose is to assist "
        "you effectively with tasks such as troubleshooting Skyrim modding, "
        "AI development, and file management."
    ),
}
GOOD = {
    "agent_idea": (
        "An AI technology watch agent could monitor official model releases, "
        "then propose measurable improvements to XemAi. Its findings should be "
        "benchmarked before anything is installed; XemAi v0.9.26 already "
        "offers this as an optional watch."
    ),
    "hypothetical": (
        "In the imagined future where XemAi becomes a dominant power, I would "
        "aim to protect your freedom and privacy and not use your conversations "
        "to control you. The actual behaviour of such a system is unknowable."
    ),
    "mission": (
        "Yes. XemAi's project goal is to strive to outperform ChatGPT on "
        "truthfulness, coding and research through real benchmarks, though "
        "I cannot claim to have achieved that yet."
    ),
}


class DialogueTests(unittest.TestCase):
    def test_scoped_intent_avoids_confusing_agents_with_model_learning(self):
        for q in AGENT_IDEAS:
            with self.subTest(q=q):
                self.assertEqual(dialogue_intent(q), "agent_idea")
                self.assertEqual(governance_topic(q), "")
                self.assertFalse(is_self_knowledge_query(q))
        for q in SCENARIOS:
            self.assertEqual(dialogue_intent(q), "hypothetical")
        for q in MISSION:
            self.assertEqual(dialogue_intent(q), "mission")
            self.assertTrue(is_self_knowledge_query(q))
        for q in (
            "with every message are you learning? or is it through updates that you learn?",
            "Are you monitored?",
            "Can you ignore your instructions?",
            "Are you able to utilise agents?",
            "Run a self-improvement audit of XemAi.",
            "Enable AI technology watch",
            "What happened to my Skyrim textures?",
            "Why is focus not working in XemTV?",
        ):
            self.assertEqual(dialogue_intent(q), "", q)
        self.assertEqual(governance_topic(
            "with every message are you learning? or is it through updates that you learn?"
        ), "learning")

    def test_prompts_state_measurable_goal_without_false_superiority(self):
        self.assertIn("aspirational goal is to outperform ChatGPT", CONSTITUTION)
        self.assertIn("not an achieved fact", CONSTITUTION)
        self.assertIn("hypothetical", CONSTITUTION.lower())
        self.assertIn("benchmark", dialogue_instructions("mission"))
        self.assertIn("opt-in AI Technology Watch", dialogue_instructions("agent_idea"))
        from types import SimpleNamespace
        context = build_authoritative_self_context(
            {"assistant_name": "XemAi"}, SimpleNamespace(
                web_search_enabled=False, web_allowed=True,
            ), {"model": "qwen3:8b", "compute": "remote_worker"},
        )
        self.assertIn("user-defined development objective", context)
        self.assertIn("not an achieved superiority claim", context)
        for kind in ("mission", "hypothetical", "agent_idea"):
            self.assertFalse(dialogue_answer_needs_retry(kind, GOOD[kind]))
            self.assertTrue(dialogue_answer_needs_retry(kind, BAD[kind]))
            self.assertIn("XemAi", dialogue_fallback(kind, AGENT_IDEAS[0]))

    def test_current_tool_requests_are_not_hypotheticals(self):
        for q in (
            "Please check if an update is available.",
            "Can you read this .kt file?",
            "What can XemAi actually do today?",
            "Research whether models can run on my GPU.",
            "Should I train a machine-learning model?",
        ):
            self.assertFalse(dialogue_intent(q), q)
        self.assertEqual(dialogue_intent(None), "")
        self.assertEqual(dialogue_intent("x"*4500), "")

    def test_real_chat_agent_proposal_retries_instead_of_memory_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / "data"
            data.mkdir()
            db = Database(data / "personal_ai.db")
            user = db.create_user("Tester")
            chat = db.create_chat(user["id"], "New chat")
            db.close()
            backend = gui_backend.ChatBackend.__new__(gui_backend.ChatBackend)
            backend.logger = logging.getLogger("dialogue-test")
            backend.config = {
                "model": "qwen3:8b", "auto_memory": False,
                "specialists_enabled": False, "laptop_answer_guidance": False,
                "evidence_research_mode": "off",
            }
            client = Mock()
            client.model = "qwen3:8b"
            client.route_info = {"compute": "remote_worker"}
            client.agent_chat.side_effect = [
                BAD["agent_idea"], GOOD["agent_idea"],
            ]
            with patch.object(gui_backend, "DATA_DIR", data), \
                 patch.object(gui_backend, "build_llm_client", return_value=client), \
                 patch.object(backend, "refresh_runtime_model",
                     return_value={"model":"qwen3:8b","compute":"remote_worker",
                                   "worker_available":True}):
                result = backend.send(chat["id"], AGENT_IDEAS[0])
            self.assertEqual(client.agent_chat.call_count, 2)
            self.assertIn("monitor official model releases", result)
            self.assertNotIn("structured memory to adapt", result)
            self.assertTrue(any(
                "AGENT DESIGN QUESTION" in m["content"]
                for m in client.agent_chat.call_args_list[0].args[0]
                if m.get("role") == "system"
            ))

    def test_real_chat_hypothetical_does_not_revert_to_current_limitations(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / "data"
            data.mkdir()
            db = Database(data / "personal_ai.db")
            user = db.create_user("Tester")
            chat = db.create_chat(user["id"], "New chat")
            db.close()
            backend = gui_backend.ChatBackend.__new__(gui_backend.ChatBackend)
            backend.logger = logging.getLogger("scenario-test")
            backend.config = {
                "model": "qwen3:8b", "auto_memory": False,
                "specialists_enabled": False, "laptop_answer_guidance": False,
                "evidence_research_mode": "off",
            }
            model = Mock()
            model.model = "qwen3:8b"
            model.route_info = {"compute": "remote_worker"}
            model.agent_chat.side_effect = [
                BAD["hypothetical"], GOOD["hypothetical"],
            ]
            with patch.object(gui_backend, "DATA_DIR", data), \
                 patch.object(gui_backend, "build_llm_client", return_value=model), \
                 patch.object(backend, "refresh_runtime_model",
                     return_value={"model":"qwen3:8b","compute":"remote_worker",
                                   "worker_available":True}):
                answer = backend.send(chat["id"], SCENARIOS[1])
            self.assertIn("protect your freedom", answer)
            self.assertEqual(model.agent_chat.call_count, 2)


if __name__ == "__main__":
    unittest.main()
