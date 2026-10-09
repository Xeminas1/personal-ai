"""Reply timing must distinguish a visible answer from background memory work."""
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import gui_backend
from app.database import Database
from app.support_access import structured_log


class ChatTimingTests(unittest.TestCase):
    def test_persisted_reply_excludes_slow_failed_memory_extraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary)
            db = Database(data / "personal_ai.db")
            self.addCleanup(db.close)
            user = db.create_user("Test")
            chat_id = db.create_chat(user["id"], "New chat")["id"]
            clock = [100.0]
            status = []
            backend = gui_backend.ChatBackend.__new__(gui_backend.ChatBackend)
            backend.config = {"model": "qwen3:8b", "auto_memory": True}
            backend.logger = logging.getLogger("personal_ai")
            route = {"model": "qwen3:8b", "compute": "remote_worker"}
            llm = Mock(model="qwen3:8b", is_hybrid=True, route_info=route)

            def discover(**kwargs):
                clock[0] += 5
                return route

            def generate(*args, **kwargs):
                clock[0] += 10
                return "answer-private-sentinel"

            def memory(**kwargs):
                # The client can already read the answer before memory starts.
                self.assertIsNone(status[-1])
                self.assertEqual(db.get_recent_messages(chat_id)[-1]["content"], "answer-private-sentinel")
                clock[0] += 30
                raise RuntimeError("Memory unavailable")

            llm.discover_runtime_model.side_effect = discover
            llm.agent_chat.side_effect = generate
            tools = Mock(web_search_enabled=False)
            tools.status_lines.return_value = []
            with patch.object(gui_backend, "DATA_DIR", data), \
                 patch.object(gui_backend, "time", SimpleNamespace(monotonic=lambda: clock[0])), \
                 patch.object(gui_backend, "ToolRegistry", return_value=tools), \
                 patch.object(gui_backend, "build_llm_client", return_value=llm), \
                 patch.object(gui_backend, "build_system_prompt", return_value="system-private-sentinel"), \
                 patch.object(gui_backend, "build_capability_status", return_value=""), \
                 patch.object(gui_backend, "extract_and_store_memories", side_effect=memory), \
                 self.assertLogs("personal_ai", level="INFO") as logs:
                answer = backend.send(chat_id, "prompt-private-sentinel", status.append)

            self.assertEqual(answer, "answer-private-sentinel")
            timing = [r.getMessage() for r in logs.records if r.getMessage().startswith("Chat timing | ")]
            exported = structured_log("\n".join(
                "2026-10-09 10:30:01,123 | INFO | personal_ai | " + line for line in timing
            ))
            phases = {event["phase"]: event for event in exported}
            self.assertEqual(phases["route"]["elapsed_ms"], 5000)
            self.assertEqual(phases["answer"]["elapsed_ms"], 10000)
            self.assertEqual(phases["visible_reply"]["elapsed_ms"], 15000)
            self.assertEqual(phases["memory"]["elapsed_ms"], 30000)
            self.assertEqual(phases["complete"]["elapsed_ms"], 45000)
            self.assertEqual(phases["visible_reply"]["compute"], "remote_worker")
            self.assertNotIn("private-sentinel", "\n".join(timing))


if __name__ == "__main__":
    unittest.main()
