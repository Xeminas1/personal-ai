"""Chat deletion exercises temporary databases, files and real HTTP races."""
from __future__ import annotations

import base64
import json
import logging
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app import gui_backend, mobile_server
from app.database import Database


class ChatDeleteTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.data = Path(temporary.name) / "data"
        self.db = Database(self.data / "personal_ai.db")
        self.addCleanup(self.db.close)
        self.user_id = self.db.create_user("Test")["id"]
        self.chat_id = self.db.create_chat(self.user_id, "Delete me")["id"]
        self.other_chat = self.db.create_chat(self.user_id, "Keep me")["id"]
        self.logger = logging.getLogger(self.id())
        self.delete_entered = threading.Event()
        self.allow_delete = threading.Event()
        self.generation_started = threading.Event()
        self.allow_generation = threading.Event()
        self.generation_finished = threading.Event()
        self.hold_delete = False
        self.addCleanup(self.allow_delete.set)
        self.addCleanup(self.allow_generation.set)
        for module in (gui_backend, mobile_server):
            patcher = patch.object(module, "DATA_DIR", self.data)
            patcher.start()
            self.addCleanup(patcher.stop)
        patcher = patch.object(mobile_server, "ChatBackend", side_effect=self.backend)
        patcher.start()
        self.addCleanup(patcher.stop)
        original_count = mobile_server._change_active_chat_requests
        def change_count(server, delta):
            original_count(server, delta)
            if delta < 0:
                self.generation_finished.set()
        patcher = patch.object(mobile_server, "_change_active_chat_requests", side_effect=change_count)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.server = mobile_server.XemAiMobileServer(("127.0.0.1", 0), mobile_server.XemAiMobileHandler)
        self.server.activity_lock = threading.Lock()
        self.server.active_chat_requests = 0
        self.server.chat_activity = {}
        self.server.update_lock = threading.Lock()
        self.server.update_restarting = False
        self.server.xemai_logger = self.logger
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close_server)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def close_server(self):
        self.allow_delete.set()
        self.allow_generation.set()
        if self.generation_started.is_set():
            self.generation_finished.wait(timeout=3)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)

    def backend(self):
        backend = gui_backend.ChatBackend.__new__(gui_backend.ChatBackend)
        backend.db = Database(self.data / "personal_ai.db")
        backend.user = backend.db.get_user()
        backend.logger = self.logger
        delete = backend.delete_chat
        def delete_chat(chat_id):
            if self.hold_delete:
                self.delete_entered.set()
                if not self.allow_delete.wait(timeout=3):
                    raise RuntimeError("Test deletion gate timed out")
            return delete(chat_id)
        backend.delete_chat = delete_chat
        def generate(chat_id, text, *, status_callback, **kwargs):
            # The answer is visible while the background memory phase is active.
            backend.db.add_message(chat_id, "user", text)
            backend.db.add_assistant_message(chat_id, "Test answer", model="qwen3:8b", compute_source="remote_worker")
            status_callback(None)
            self.generation_started.set()
            if not self.allow_generation.wait(timeout=3):
                raise RuntimeError("Test generation gate timed out")
        backend.send = generate
        return backend

    def request(self, path=None, *, method="DELETE", body=None, origin=True, headers=None):
        request_headers = {"Content-Type": "application/json"}
        if origin:
            request_headers["Origin"] = self.base if origin is True else origin
        request_headers.update(headers or {})
        payload = json.dumps(body if body is not None else {}).encode()
        request = urllib.request.Request(self.base + (path or f"/api/chats/{self.chat_id}"),
            data=payload, method=method, headers=request_headers)
        try:
            response = self.opener.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def attachment_folder(self, chat_id=None):
        folder = self.data / "attachments" / f"chat_{self.chat_id if chat_id is None else chat_id}"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def test_delete_cascades_chat_data_but_preserves_saved_memories_and_other_chat(self):
        self.db.add_message(self.chat_id, "user", "Question")
        message = self.db.add_assistant_message(self.chat_id, "Answer", model="qwen3:8b", compute_source="remote_worker")
        self.db.add_feedback(self.user_id, self.chat_id, message, 7, "Useful")
        self.db.add_chat_feedback(self.user_id, self.chat_id, 8, "Good chat")
        memory = self.db.add_memory(self.user_id, self.chat_id, "project", "Preserve the Skyrim mod project", 0.9)
        keep_message = self.db.add_message(self.other_chat, "user", "Keep this history")
        folder = self.attachment_folder()
        (folder / "upload.txt").write_text("Test attachment")
        sibling = self.attachment_folder(self.other_chat) / "keep.txt"
        sibling.write_text("Keep this file")
        status, response = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(response, {"ok": True, "deleted_chat_id": self.chat_id, "attachment_cleanup_complete": True})
        self.assertIsNone(self.db.get_chat(self.chat_id))
        for table in ("messages", "message_inference", "feedback", "chat_feedback"):
            self.assertEqual(self.db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0], 1 if table == "messages" else 0)
        saved = self.db.conn.execute("SELECT * FROM memories WHERE id=?", (memory,)).fetchone()
        self.assertIsNone(saved["source_chat_id"])
        self.assertEqual(saved["content"], "Preserve the Skyrim mod project")
        self.assertEqual(saved["active"], 1)
        self.assertEqual(self.db.get_recent_messages(self.other_chat)[0]["id"], keep_message)
        self.assertFalse(folder.exists())
        self.assertEqual(sibling.read_text(), "Keep this file")
        self.assertEqual(self.db.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.assertEqual(self.request()[0], 404)

    def test_current_user_scope_protects_foreign_chat_and_attachment_files(self):
        foreign_user = self.db.create_user("Other")["id"]
        foreign_chat = self.db.create_chat(foreign_user, "Foreign")["id"]
        self.assertFalse(self.db.delete_chat(self.user_id, foreign_chat))
        file = self.attachment_folder(foreign_chat) / "foreign.txt"
        file.write_text("Protected")
        self.assertEqual(self.request(f"/api/chats/{foreign_chat}")[0], 404)
        self.assertIsNotNone(self.db.get_chat(foreign_chat))
        self.assertEqual(file.read_text(), "Protected")

    def test_origin_support_key_and_input_guards_cannot_delete(self):
        for kwargs in (
            {"origin": False}, {"origin": "https://other.example"}, {"origin": "http://["},
            {"headers": {"Sec-Fetch-Site": "cross-site"}},
            {"headers": {"Authorization": "Bearer read-only-support-key"}},
            {"headers": {"Content-Type": "text/plain"}},
        ):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.request(**kwargs)[0], 403)
                self.assertIsNotNone(self.db.get_chat(self.chat_id))
        self.assertEqual(self.request(f"/api/chats/{self.chat_id}?unexpected=1")[0], 403)
        self.assertEqual(self.request(body={"user_id": self.user_id})[0], 400)
        self.assertEqual(self.request(f"/api/chats/{self.chat_id}/messages")[0], 404)
        self.assertIsNotNone(self.db.get_chat(self.chat_id))

    def test_active_reply_memory_tail_and_update_reject_delete(self):
        self.server.active_chat_requests = 1
        self.server.chat_activity = {}  # Visible reply finished; memory still runs.
        self.assertEqual(self.request()[0], 409)
        self.server.active_chat_requests = 0
        self.server.update_restarting = True
        self.assertEqual(self.request()[0], 409)
        self.server.update_restarting = False
        with self.server.update_lock:
            self.assertEqual(self.request()[0], 409)
        self.assertIsNotNone(self.db.get_chat(self.chat_id))

    def test_cleanup_failure_does_not_undo_successful_chat_deletion(self):
        file = self.attachment_folder() / "left.txt"
        file.write_text("Cleanup fixture")
        with patch.object(gui_backend.shutil, "rmtree", side_effect=PermissionError("private-file-path-sentinel")):
            status, response = self.request()
        self.assertEqual(status, 200)
        self.assertFalse(response["attachment_cleanup_complete"])
        self.assertNotIn("private-file-path-sentinel", json.dumps(response))
        self.assertIsNone(self.db.get_chat(self.chat_id))
        self.assertTrue(file.exists())

    def test_attachment_folder_symlink_never_deletes_external_content(self):
        outside = self.data.parent / "outside"
        outside.mkdir()
        protected = outside / "protected.txt"
        protected.write_text("Keep external content")
        parent = self.data / "attachments"
        parent.mkdir()
        try:
            (parent / f"chat_{self.chat_id}").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("Symlink creation unavailable")
        status, response = self.request()
        self.assertEqual(status, 200)
        self.assertFalse(response["attachment_cleanup_complete"])
        self.assertEqual(protected.read_text(), "Keep external content")

    def test_started_reply_reservation_blocks_delete_even_after_activity_clears(self):
        status, _ = self.request(f"/api/chats/{self.chat_id}/messages", method="POST", body={"text": "Question"})
        self.assertEqual(status, 202)
        self.assertTrue(self.generation_started.wait(timeout=3))
        self.assertFalse(mobile_server._get_chat_activity(self.server, self.chat_id)["active"])
        self.assertEqual(self.request()[0], 409)
        self.allow_generation.set()
        self.assertTrue(self.generation_finished.wait(timeout=3))
        self.assertEqual(self.request()[0], 200)

    def test_concurrent_stale_send_or_upload_cannot_recreate_deleted_chat(self):
        for suffix, body in (("messages", {"text": "Stale message"}), ("attachments", {"name": "stale.txt", "data": base64.b64encode(b"stale file").decode()})):
            with self.subTest(suffix=suffix):
                self.chat_id = self.db.create_chat(self.user_id, "Race fixture")["id"]
                self.hold_delete = True
                self.delete_entered.clear()
                self.allow_delete.clear()
                body_read = threading.Event()
                original = mobile_server.XemAiMobileHandler._read_json
                def read_json(handler):
                    result = original(handler)
                    if handler.path.endswith("/" + suffix):
                        body_read.set()
                    return result
                with patch.object(mobile_server.XemAiMobileHandler, "_read_json", read_json), ThreadPoolExecutor(max_workers=2) as executor:
                    deleted = executor.submit(self.request)
                    self.assertTrue(self.delete_entered.wait(timeout=3))
                    stale = executor.submit(self.request, f"/api/chats/{self.chat_id}/{suffix}", method="POST", body=body)
                    self.assertTrue(body_read.wait(timeout=3))
                    self.allow_delete.set()
                    self.assertEqual(deleted.result(timeout=3)[0], 200)
                    self.assertEqual(stale.result(timeout=3)[0], 404)
                self.assertIsNone(self.db.get_chat(self.chat_id))
                self.assertFalse((self.data / "attachments" / f"chat_{self.chat_id}").exists())
                self.assertEqual(self.server.active_chat_requests, 0)
                self.assertFalse(self.generation_started.is_set())


if __name__ == "__main__":
    unittest.main()
