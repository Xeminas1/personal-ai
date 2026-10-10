"""Self metadata routing does not swallow polite Skyrim diagnostic requests."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.self_knowledge import (
    RELEASE_HISTORY, build_authoritative_self_context, is_ai_comparison_query,
    is_self_knowledge_query,
)
from app.specialists import SpecialistCoordinator


class SelfKnowledgeTests(unittest.TestCase):
    def test_polite_external_version_memory_and_missing_file_requests_are_not_self_queries(self):
        questions = (
            "Could you help check the SKSE version for Skyrim?",
            "XemAi, could you help check the SKSE version for Skyrim?",
            "Can you check whether this log mentions missing masters?",
            "XemAi, can you analyse this crash log for missing masters?",
            "Could you compare Skyrim runtime versions and their SKSE compatibility?",
            "Please help me diagnose the missing textures in my load order.",
            "Can you analyse the game's memory usage from this crash log?",
            "Could you inspect this CPU memory report?",
            "Which model do you recommend for Skyrim footage analysis?",
            "Which model and version do you recommend for Skyrim footage analysis?",
            "Which model are you recommending for my stronger PC?",
            "What version are you recommending for SKSE?",
            "Which model generated this answer in my offline Skyrim tool?",
            "Which model is replying in the Skyrim mod author's chatbot?",
            "What model handles Skyrim NPC messages?",
            "Can you check the SKSE version using your recommendation from earlier?",
            "What has been added to Skyrim by this patch?",
            "Could you explain Vortex's update history?",
            "Please help compare these tools for modding.",
        )
        for question in questions:
            with self.subTest(question=question):
                self.assertFalse(is_self_knowledge_query(question))

    def test_actual_assistant_capabilities_runtime_and_model_questions_remain_self_queries(self):
        questions = (
            "What can you do?", "What can't you do?", "What are your limitations?",
            "What do you think your AI is missing?", "Do you have memory?",
            "Can you remember?", "Do you have web access?", "What tools can you use?",
            "What version are you?", "Which version are you currently running?",
            "Which model are you running?", "What language model do you use?",
            "What model and version are you currently running?",
            "Which model is replying here?", "What model answers my messages?",
            "Which model generated this answer?", "What AI model is responding to me?",
            "Which model produced the previous reply in this chat?",
            "What model are you?", "Which model are you based on?",
            "Tell me your actual runtime model.", "Explain how your memory works.",
            "What are XemAi's capabilities?", "What limitations does this assistant have?",
            "What version is XemAi?", "What model does this AI use?", "What can XemAi do?",
            "What is missing from XemAi?", "What has changed with XemAi?",
            "What has been added?", "What’s been added?", "Update history",
            "Through your iterative updates, can you recognise whats been added?",
        )
        for question in questions:
            with self.subTest(question=question):
                self.assertTrue(is_self_knowledge_query(question))

    def test_direct_ai_opinions_and_comparisons_keep_the_existing_route(self):
        for question in ("What's your opinion on ChatGPT?", "Are you better than ChatGPT?",
                         "Compare XemAi with Claude", "How do you rate other AI systems?"):
            with self.subTest(question=question):
                self.assertTrue(is_ai_comparison_query(question))
                self.assertTrue(is_self_knowledge_query(question))

    def test_skse_request_is_eligible_for_skyrim_review_instead_of_self_suppression(self):
        client = SimpleNamespace(route_info={"compute": "local_host"}, local_review=lambda *args, **kwargs: None)
        query = "Could you help check the SKSE version for Skyrim?"
        coordinator = SpecialistCoordinator({}, client, query, is_skyrim=True, diagnostic=True,
            user_context="Parsed crash log: runtime 1.6.1170; SKSE 2.2.6")
        self.assertTrue(coordinator.eligible)
        self.assertTrue(coordinator._available("local_host"))
        self.assertFalse(SpecialistCoordinator({}, client, "Which model are you running?",
                                              is_skyrim=True, diagnostic=True).eligible)

    def test_laptop_runtime_description_and_new_history_do_not_claim_a_model_upgrade(self):
        tools = SimpleNamespace(web_search_enabled=False, web_allowed=True)
        context = build_authoritative_self_context({}, tools,
            {"model": "qwen3:1.7b", "compute": "local_host", "source": "runtime_discovery"})
        self.assertIn("Underlying language model actually selected at runtime: qwen3:1.7b", context)
        self.assertIn("v0.9.18", context)
        self.assertIn("no laptop preparation pass runs", context)
        self.assertIn("Citation correction consumes that laptop extra pass", context)
        self.assertIn("do not change model weights or switch", context)
        summary = dict(RELEASE_HISTORY)["0.9.18"]
        self.assertIn("qwen3:1.7b", summary)
        self.assertIn("does not switch", summary)
        self.assertIn("independently verify", summary)

    def test_malformed_query_is_not_classified_as_self_metadata(self):
        for text in (None, 42, {}, []):
            self.assertFalse(is_self_knowledge_query(text))


if __name__ == "__main__":
    unittest.main()
