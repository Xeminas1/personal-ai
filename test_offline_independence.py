"""Offline-first smoke checks for XemAi's local chat and deterministic tools.

Synthetic local-model stub; no external AI, GitHub, private data or real
network traffic. Passing these tests does NOT establish live-model quality,
performance, persistent model learning or offline operation on an owner host.
"""
from __future__ import annotations

import json
import logging
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from app import gui_backend
from app.database import Database
from app.evidence import TurnEvidenceTools
from app.llm import OllamaClient
from app.tools import ToolRegistry


class LocalOnlyModel(OllamaClient):
    """Simulate an already available localhost model without any HTTP calls."""

    def __init__(self, logger):
        super().__init__("http://127.0.0.1:1", "qwen3:1.7b", logger)
        self.route_info = {"compute": "local_host"}
        self.requests = []

    def _request(self, path, payload=None, timeout=600):
        self.requests.append((path, payload))
        return {"message": {
            "role": "assistant",
            "content": "Hello. This is a synthetic locally generated greeting.",
        }}


class OfflineIndependenceSmoke(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.logger = logging.getLogger(self.id())
        self.registry = ToolRegistry(self.root, self.data, self.logger)

    def test_offline_deterministic_tools_remain_available(self):
        tools = TurnEvidenceTools(self.registry, "Don't use the internet; calculate this locally.")
        names = {item["function"]["name"] for item in tools.definitions()}
        self.assertIn("calculator", names)
        self.assertNotIn("web_search", names)
        self.assertNotIn("web_fetch", names)
        self.assertNotIn("research_evidence", names)

        with patch.object(urllib.request, "urlopen",
                          side_effect=AssertionError("No external network allowed")) as network:
            result = json.loads(tools.execute("calculator", {"expression": "18 * 7"}))
            self.assertTrue(result["ok"])
            self.assertEqual(result["result"], 126)
            denied = json.loads(tools.execute("web_search", {"query": "external service"}))
            self.assertFalse(denied["ok"])
            network.assert_not_called()

    def test_chat_can_save_a_local_stub_reply_without_external_services(self):
        db = Database(self.data / "personal_ai.db")
        self.addCleanup(db.close)
        user = db.create_user("Fictional test user")
        chat_id = db.create_chat(user["id"], "Offline smoke")["id"]
        backend = gui_backend.ChatBackend.__new__(gui_backend.ChatBackend)
        backend.config = {
            "model": "qwen3:1.7b",
            "auto_detect_ollama_model": False,
            "auto_memory": False,
            "evidence_research_mode": "off",
            "specialists_enabled": False,
            "agent_team_enabled": False,
            "agent_teams_enabled": False,
            "laptop_answer_guidance": False,
            "laptop_review_enabled": False,
            "teacher_enabled": False,
            "hybrid_enabled": False,
        }
        backend.logger = self.logger
        model = LocalOnlyModel(self.logger)
        with (
            patch.object(gui_backend, "BASE_DIR", self.root),
            patch.object(gui_backend, "DATA_DIR", self.data),
            patch.object(gui_backend, "ToolRegistry", return_value=self.registry),
            patch.object(gui_backend, "build_llm_client", return_value=model),
            patch.object(
                urllib.request, "urlopen",
                side_effect=AssertionError("External network attempted"),
            ) as network,
        ):
            answer = backend.send(chat_id, "Say hello, without using the internet.")
            network.assert_not_called()

        self.assertEqual(answer, "Hello. This is a synthetic locally generated greeting.")
        self.assertGreaterEqual(len(model.requests), 1)
        messages = db.get_recent_messages(chat_id)
        self.assertEqual(messages[-1]["content"], answer)
        self.assertEqual(messages[-1]["inference_model"], "qwen3:1.7b")
        self.assertEqual(messages[-1]["inference_compute"], "local_host")


if __name__ == "__main__":
    unittest.main()
