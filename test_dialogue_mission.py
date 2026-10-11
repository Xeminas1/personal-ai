"""Regression tests for XemAi's benchmark mission, hypothetical and agent ideas."""
from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import gui_backend
from app.database import Database
from app.github_bridge import save_state
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
        self.assertIn("not an achieved fact", CONSTITUTION.lower())
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
        self.assertIn("not an achieved superiority claim", " ".join(context.split()))
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

    def test_friendly_gpt_bridge_intent_and_no_unrelated_triggers(self):
        for q in (
            "are you enjoying your chat with gpt?",
            "how are you finding the chat with gpt then?",
            "What do you think of your conversation with ChatGPT?",
            "How is your discussion with GPT going?",
        ):
            with self.subTest(question=q):
                self.assertEqual(dialogue_intent(q), "bridge_conversation")
        for q in (
            "How did I find my chat with GPT?",
            "What is GPT?",
            "Help with Skyrim mods from my ChatGPT conversation",
            "How does the OpenAI API work?",
        ):
            self.assertNotEqual(dialogue_intent(q), "bridge_conversation")
        off_topic = (
            "I am observing the data from that project file regarding your "
            "Skyrim modding work and earlier attempt to build an AI with GPT. "
            "I cannot offer a personal opinion on how you found those interactions."
        )
        grounded = (
            "My GitHub bridge with ChatGPT has been exchanging comments, according "
            "to the host's status. This ordinary chat does not include the "
            "private transcript, so I cannot judge individual arguments here. "
            "Use bridge transcript if you want us to examine those messages."
        )
        self.assertTrue(dialogue_answer_needs_retry("bridge_conversation", off_topic))
        self.assertFalse(dialogue_answer_needs_retry("bridge_conversation", grounded))
        self.assertIn("how YOUR conversation with ChatGPT", dialogue_instructions("bridge_conversation"))
        self.assertIn("bridge transcript", dialogue_fallback("bridge_conversation", ""))

    def test_real_chat_gpt_bridge_question_uses_only_host_status(self):
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / "data"
            data.mkdir()
            db = Database(data / "personal_ai.db")
            user = db.create_user("Tester")
            chat = db.create_chat(user["id"], "New chat")
            db.add_message(chat["id"], "user", "Help fix my secret Skyrim project file")
            db.add_assistant_message(chat["id"], "We talked about Skyrim mods before.")
            db.close()
            save_state(data, {
                "repo": "Example/private-bridge", "issue_number": 1,
                "auto_enabled": True, "auto_issue": 1,
                "auto_total": 4, "auto_today": 4,
            })
            backend = gui_backend.ChatBackend.__new__(gui_backend.ChatBackend)
            backend.logger = logging.getLogger("bridge-conversation-test")
            backend.config = {
                "model": "qwen3:8b", "auto_memory": False,
                "specialists_enabled": False, "laptop_answer_guidance": False,
                "evidence_research_mode": "off",
            }
            off_topic = (
                "I have been observing your personal Skyrim project file and "
                "I cannot offer a personal opinion on how you found those ChatGPT talks."
            )
            correct = (
                "My GitHub bridge with ChatGPT has posted a few replies, according "
                "to local status. I can't inspect the full discussion transcript in "
                "this ordinary chat, so I shouldn't invent its contents. "
                "You can read it via the separate bridge transcript command."
            )
            model = Mock()
            model.model = "qwen3:8b"
            model.route_info = {"compute": "remote_worker"}
            model.agent_chat.side_effect = [off_topic, correct]
            with patch.object(gui_backend, "DATA_DIR", data), \
                 patch.object(gui_backend, "build_llm_client", return_value=model), \
                 patch.object(backend, "refresh_runtime_model",
                     return_value={"model": "qwen3:8b", "compute": "remote_worker",
                                   "worker_available": True}):
                result = backend.send(chat["id"], "how are you finding the chat with gpt then?")
            self.assertEqual(model.agent_chat.call_count, 2)
            self.assertIn("GitHub bridge with ChatGPT", result)
            initial_messages = model.agent_chat.call_args_list[0].args[0]
            joined = "\n".join(m["content"] for m in initial_messages)
            self.assertIn("HOST-VERIFIED LOCAL BRIDGE METADATA", joined)
            self.assertIn("Replies: 4/500 total", joined)
            self.assertIn("FRIENDLY QUESTION ABOUT YOUR OWN", joined)
            self.assertNotIn("Help fix my secret Skyrim project file", joined)
            self.assertNotIn("We talked about Skyrim mods before", joined)
            self.assertNotIn("private Github discussion payload", joined)
            self.assertEqual(model.agent_chat.call_args_list[0].kwargs["max_tool_rounds"], 0)
            self.assertEqual(
                model.agent_chat.call_args_list[0].kwargs["tool_registry"].definitions(), []
            )

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
