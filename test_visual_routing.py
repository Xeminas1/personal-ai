"""Image-only XemAi benchmark regression tests: no unrelated code/web answers."""
from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import gui_backend, media_support
from app.database import Database
from app.visual_guidance import (
    NoExternalOrSourceTools, VISUAL_ONLY_INSTRUCTIONS,
    is_image_only_request, visual_answer_needs_retry,
    visual_reports_ready, visual_unavailable_response,
)

JPEG = b"\xff\xd8\xff\xe0fixture-image\xff\xd9"
VISUAL = (
    "One supplied image; no audio.\n"
    "VISION MODEL OBSERVATIONS (qwen2.5vl:7b on paired PC; interpretation):\n"
    "The blue filled pill highlights Home in the left sidebar. The top Play "
    "button and the first Films poster both have cyan-blue glows."
)
QUESTION = (
    "Describe the image I attached. Tell me which navigation row is highlighted "
    "and where glow effects are located. Do not inspect source code or search "
    "the internet."
)
PROHIBITED = (
    "The provided source files implement ArtworkLoader.kt, artwork.py "
    "and test_artwork.py, invoking FFmpeg to create thumbnails."
)


class VisualRoutingTests(unittest.TestCase):
    def test_classifier_requires_attachment_and_positive_visual_intent(self):
        jpg = [{"name": "screen.jpg", "mime": "image/jpeg", "path": "x"}]
        self.assertTrue(is_image_only_request(QUESTION, jpg))
        self.assertTrue(is_image_only_request(
            "SCREENSHOT BENCHMARK - VISUAL ANALYSIS ONLY. Image 1 is the "
            "concept and Image 2 is the app. Do not inspect source code or "
            "search the internet. Describe visible differences.",
            jpg * 2,
        ))
        self.assertTrue(is_image_only_request("Describe this image.", jpg))
        self.assertTrue(is_image_only_request(
            "Please review the screenshots. Do not use Developer Mode.",
            jpg,
        ))
        for question in (
            "Compare screenshots, then use Developer Mode to inspect source code.",
            "Read the actual Kotlin files behind this screenshot and trace the classes.",
            "Inspect the source code and compare against this image.",
        ):
            self.assertFalse(is_image_only_request(question, jpg), question)
        self.assertFalse(is_image_only_request(QUESTION, []))
        self.assertFalse(is_image_only_request("Hello!", jpg))
        self.assertFalse(is_image_only_request(QUESTION, [{"name": "source.kt", "mime": "text/plain"}]))
        self.assertFalse(is_image_only_request(QUESTION, jpg + [{"name": "code.kt", "mime": "text/plain"}]))

    def test_reports_must_represent_each_attached_image(self):
        a = {"name": "a.jpg", "path": "a", "mime": "image/jpeg"}
        b = {"name": "b.jpg", "path": "b", "mime": "image/jpeg"}
        self.assertTrue(visual_reports_ready([a], {"a": VISUAL}))
        self.assertTrue(visual_reports_ready([a, b], {"a": VISUAL, "b": VISUAL}))
        self.assertFalse(visual_reports_ready([a, b], {"a": VISUAL, "b": "[Visual contents not analysed.]"}))
        self.assertFalse(visual_reports_ready([a], {"a": "[Visual contents not analysed.]"}))
        self.assertFalse(visual_reports_ready([], {"a": VISUAL}))
        self.assertIn("did not return usable observations", visual_unavailable_response())

    def test_no_visual_only_tool_actions_and_no_hallucinated_code_answer(self):
        tools = NoExternalOrSourceTools()
        self.assertEqual(tools.definitions(), [])
        self.assertFalse(__import__("json").loads(tools.execute("dev_read", {}))["ok"])
        self.assertFalse(__import__("json").loads(tools.execute("web_search", {}))["ok"])
        self.assertIn("LEFT SIDEBAR", VISUAL_ONLY_INSTRUCTIONS)
        self.assertTrue(visual_answer_needs_retry(QUESTION, PROHIBITED))
        self.assertTrue(visual_answer_needs_retry(QUESTION,
            "The image file is not directly accessible or verifiable."))
        self.assertTrue(visual_answer_needs_retry(QUESTION, "Too short"))
        self.assertFalse(visual_answer_needs_retry(QUESTION,
            "The Home navigation entry in the left sidebar is highlighted "
            "in blue. In the main area, the Play button and the first film "
            "poster both show luminous cyan outlines."))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / "data"
        self.folder = self.data / "attachments" / "chat_1"
        self.folder.mkdir(parents=True)
        (self.folder / "screen.jpg").write_bytes(JPEG)
        db = Database(self.data / "personal_ai.db")
        self.addCleanup(db.close)
        user = db.create_user("Test")
        self.chat_id = db.create_chat(user["id"], "New chat")["id"]
        self.db = db
        self.backend = gui_backend.ChatBackend.__new__(gui_backend.ChatBackend)
        self.backend.config = {
            "model": "qwen3:8b", "auto_memory": False,
            "evidence_research_mode": "auto",
            "specialists_enabled": False,
            "laptop_answer_guidance": False,
        }
        self.backend.logger = logging.getLogger("visual-routing-test")
        self.attachment = {
            "name": "screen.jpg", "path": "attachments/chat_1/screen.jpg",
            "mime": "image/jpeg",
        }

    def test_full_visual_chat_ignores_web_and_source_and_uses_observations(self):
        client = Mock()
        client.model = "qwen3:8b"
        client.route_info = {"compute": "remote_worker"}
        client.agent_chat.return_value = (
            "The Home row in the left sidebar is selected with a blue filled "
            "highlight. The Play button and the first Films poster glow cyan. "
            "The text is pale blue and the background is very dark navy."
        )
        with patch.object(gui_backend, "DATA_DIR", self.data), \
             patch.object(gui_backend, "build_llm_client", return_value=client), \
             patch.object(self.backend, "refresh_runtime_model", return_value={
                 "model": "qwen3:8b", "worker_available": True, "compute": "remote_worker"
             }), \
             patch.object(gui_backend, "analyse_attachment", return_value=VISUAL), \
             patch.object(gui_backend, "source_context_for_request") as src, \
             patch.object(gui_backend, "should_research_query") as research:
            result = self.backend.send(
                self.chat_id, QUESTION, attachments=[self.attachment],
            )
        self.assertIn("Home row", result)
        src.assert_not_called()
        research.assert_not_called()
        self.assertEqual(client.agent_chat.call_count, 1)
        call = client.agent_chat.call_args
        self.assertIsInstance(call.kwargs["tool_registry"], NoExternalOrSourceTools)
        self.assertEqual(call.kwargs["tool_registry"].definitions(), [])
        messages = call.args[0]
        self.assertTrue(any(VISUAL in x["content"] for x in messages if x["role"] == "user"))
        self.assertTrue(any("IMAGE-ONLY TASK" in x["content"] for x in messages if x["role"] == "system"))

    def test_off_topic_code_reply_is_retried_with_no_tools(self):
        client = Mock()
        client.model = "qwen3:8b"
        client.route_info = {"compute": "remote_worker"}
        client.agent_chat.side_effect = [
            PROHIBITED,
            "The Home button in the left sidebar has a filled cyan-blue "
            "highlight. The Play button below The Wanderer and the first "
            "movie poster also have blue glow outlines."
        ]
        with patch.object(gui_backend, "DATA_DIR", self.data), \
             patch.object(gui_backend, "build_llm_client", return_value=client), \
             patch.object(self.backend, "refresh_runtime_model", return_value={
                 "model": "qwen3:8b", "worker_available": True, "compute": "remote_worker"
             }), \
             patch.object(gui_backend, "analyse_attachment", return_value=VISUAL):
            result = self.backend.send(
                self.chat_id, QUESTION, attachments=[self.attachment],
            )
        self.assertEqual(client.agent_chat.call_count, 2)
        self.assertIn("Home button", result)
        self.assertNotIn("ArtworkLoader", result)
        for call in client.agent_chat.call_args_list:
            self.assertIsInstance(call.kwargs["tool_registry"], NoExternalOrSourceTools)

    def test_failed_vision_never_asks_text_model_to_guess(self):
        client = Mock()
        client.model = "qwen3:8b"
        client.route_info = {"compute": "remote_worker"}
        with patch.object(gui_backend, "DATA_DIR", self.data), \
             patch.object(gui_backend, "build_llm_client", return_value=client), \
             patch.object(self.backend, "refresh_runtime_model", return_value={
                 "model": "qwen3:8b", "worker_available": True, "compute": "remote_worker"
             }), \
             patch.object(gui_backend, "analyse_attachment",
                          return_value="[Visual contents not analysed.]"):
            result = self.backend.send(
                self.chat_id, QUESTION, attachments=[self.attachment],
            )
        self.assertIn("did not return usable observations", result)
        client.agent_chat.assert_not_called()
        last = self.db.get_recent_messages(self.chat_id)[-1]
        self.assertIn("did not return usable observations", last["content"])


if __name__ == "__main__":
    unittest.main()
