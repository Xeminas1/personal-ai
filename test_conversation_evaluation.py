"""Read-only pilot lifecycle, model identity, records and chat integration."""
from __future__ import annotations
import csv
import io
import json
import logging
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from app import conversation_evaluation as evaluation, gui_backend, mobile_server
from app.database import Database

REAL_SELECT_CLIENT = evaluation._select_client


class FakeClient:
    model = "qwen3:1.7b"
    def __init__(self, actual=None, tool=False, error=False):
        self.actual = actual or self.model
        self.tool, self.error, self.calls = tool, error, []
    def installed_models(self):
        return [{"name": self.model, "digest": "a" * 64}]
    def chat_raw(self, messages):
        self.calls.append(messages)
        if self.error:
            raise RuntimeError("Bearer TEST_PRIVATE_TOKEN https://private-worker")
        return {
            "model": self.actual, "done": True,
            "message": {"content": "=1+1", **({"tool_calls": [{"name": "write_file"}]} if self.tool else {})},
        }


class ConversationEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.data = Path(self.temp.name) / "data"
        self.data.mkdir()
        self.config = {"model": "qwen3:1.7b", "secret": "NEVER_EXPORT_CONFIGURATION"}
        self.client = FakeClient()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(patch.stopall)
        self.select = patch.object(evaluation, "_select_client",
            return_value=(self.client, self.client.model, "local_host")).start()
        patch.object(evaluation, "_BETWEEN_REQUESTS_SECONDS", 0).start()
        self.addCleanup(self.stop_and_wait)

    def stop_and_wait(self):
        key = str(self.data.resolve())
        with evaluation._LOCK:
            job = evaluation._JOBS.get(key)
        if job:
            job["stop"].set()
            job["begin"].set()
            job["thread"].join(5)
        self.assertFalse(evaluation.is_running(self.data))

    def wait(self):
        deadline = time.monotonic() + 5
        while evaluation.is_running(self.data) and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertFalse(evaluation.is_running(self.data))
        return evaluation.status(self.data)

    def report(self):
        data, name = evaluation.export_results(self.data)
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            return json.loads(archive.read("results.json")), archive.read("blind_review.csv").decode("utf-8-sig"), name

    def test_only_exact_user_commands_are_actions(self):
        for text in ("conversation test", "Conversation test status!", "conversation test laptop", "conversation test pc"):
            self.assertTrue(evaluation.is_command(text), text)
        for text in ("Should we run a conversation test?", '"conversation test"',
                     "conversation test; delete files", "conversation testing", None):
            self.assertFalse(evaluation.is_command(text), text)
        self.assertIsNone(evaluation.command(self.data, "normal question", self.config))
        self.select.assert_not_called()

    def test_absent_approved_lessons_are_skipped_and_config_not_exported(self):
        config_before = json.dumps(self.config)
        text = evaluation.command(self.data, "conversation test", self.config)
        self.assertIn("background", text)
        meta = self.wait()
        self.assertEqual(meta["state"], "completed")
        self.assertEqual(meta["generated_answers"], 18)
        self.assertEqual(meta["skipped_rows"], 6)
        self.assertEqual(len(self.client.calls), 18)
        self.assertEqual(config_before, json.dumps(self.config))
        result, blind, name = self.report()
        self.assertFalse(result["manifest"]["training_applied"])
        self.assertFalse(result["manifest"]["scored"])
        self.assertNotIn("NEVER_EXPORT_CONFIGURATION", json.dumps(result))
        rows = list(csv.DictReader(io.StringIO(blind)))
        self.assertEqual(len(rows), 18)
        self.assertNotIn("condition", rows[0])
        self.assertEqual(rows[0]["answer"], "'=1+1")
        self.assertEqual(rows[0]["score_1_0_or_1"], "")
        self.assertTrue(name.endswith(".zip"))
        self.assertIn("[[XEMAI_CONVERSATION_RESULTS:", evaluation.command(self.data, "conversation test results", self.config))

    def test_approved_notes_only_enter_their_condition_and_are_not_copied(self):
        note = "APPROVED_NOTE_FIXTURE_NO_PRIVATE_CHAT"
        with patch.object(evaluation, "_notes", return_value=[note]):
            evaluation.command(self.data, "conversation test", self.config)
            meta = self.wait()
        self.assertEqual(meta["generated_answers"], 24)
        self.assertEqual(sum(note in json.dumps(m) for m in self.client.calls), 6)
        result, _, _ = self.report()
        self.assertNotIn(note, json.dumps(result))
        self.assertEqual(sum(r["lesson_present"] for r in result["results"]), 6)

    def test_model_mismatch_stops_without_a_laptop_retry(self):
        self.client.actual = "another-model"
        evaluation.command(self.data, "conversation test", self.config)
        meta = self.wait()
        self.assertEqual(meta["state"], "failed")
        self.assertEqual(len(self.client.calls), 1)
        self.assertEqual(meta["generated_answers"], 0)
        self.assertEqual(meta["unscorable_rows"], 1)
        result, blind, _ = self.report()
        self.assertEqual(result["results"][-1]["status"], "unscorable_model_identity")
        self.assertEqual(len(list(csv.DictReader(io.StringIO(blind)))), 0)

    def test_generation_error_does_not_export_private_exception_text(self):
        self.client.error = True
        evaluation.command(self.data, "conversation test", self.config)
        self.assertEqual(self.wait()["state"], "failed")
        result, _, _ = self.report()
        self.assertNotIn("TEST_PRIVATE_TOKEN", json.dumps(result))
        self.assertNotIn("private-worker", json.dumps(result))
        self.assertEqual(result["manifest"]["error_type"], "RuntimeError")

    def test_queued_run_is_single_and_can_be_cancelled_before_inference(self):
        evaluation.command(self.data, "conversation test", self.config, defer=True)
        self.assertEqual(evaluation.status(self.data)["state"], "queued")
        self.assertIn("already running", evaluation.command(self.data, "conversation test", self.config))
        self.assertIn("stopping", evaluation.command(self.data, "conversation test stop", self.config))
        self.assertEqual(self.wait()["state"], "cancelled")
        self.select.assert_not_called()
        self.assertEqual(len(self.client.calls), 0)

    def test_deferred_run_is_not_released_by_a_different_chat(self):
        db = Database(self.data / "personal_ai.db")
        user = db.create_user("Tester")
        chat = db.create_chat(user["id"], "Test")["id"]
        db.close()
        evaluation.command(self.data, "conversation test", self.config, chat_id=chat, defer=True)
        evaluation.begin(self.data, chat + 1)
        self.select.assert_not_called()
        evaluation.begin(self.data, chat)
        self.wait()
        db = Database(self.data / "personal_ai.db")
        try:
            messages = db.get_recent_messages(chat, limit=8)
        finally:
            db.close()
        self.assertEqual(len(messages), 1)
        self.assertIn("Conversation test completed", messages[0]["content"])
        self.assertEqual(messages[0]["inference_compute"], "application")

    def test_host_updates_wait_for_an_active_pilot(self):
        evaluation.command(self.data, "conversation test", self.config, defer=True)
        server = type("Server", (), {
            "chat_operation_lock": threading.Lock(), "update_lock": threading.Lock(),
            "update_restarting": False,
        })()
        with patch.object(mobile_server, "DATA_DIR", self.data), \
             patch.object(mobile_server, "_active_chat_requests", return_value=0):
            self.assertEqual(mobile_server._reserve_update(server), "busy")
            evaluation.command(self.data, "conversation test stop", self.config)
            self.wait()
            self.assertIsNone(mobile_server._reserve_update(server))
            server.update_lock.release()

    def test_interrupt_detection_and_export_path_restrictions(self):
        root = self.data / "conversation_tests"
        path = root / ("run_" + "a"*32)
        path.mkdir(parents=True)
        (root / "latest.json").write_text(json.dumps({"run_id":"a"*32}))
        (path / "state.json").write_text(json.dumps({"run_id":"a"*32,"state":"running","export_ready":False}))
        self.assertEqual(evaluation.status(self.data)["state"], "interrupted")
        for run_id in ("../secrets", "", "a"*31, "a"*32 + "/other"):
            with self.assertRaises(ValueError):
                evaluation.export_results(self.data, run_id)
        with self.assertRaises(FileNotFoundError):
            evaluation.export_results(self.data, "a"*32)

    def test_lock_is_exclusive_and_released(self):
        path = self.data / "test.lock"
        first, second = evaluation._Reservation(path), evaluation._Reservation(path)
        self.assertTrue(first.acquire())
        try:
            self.assertFalse(second.acquire())
        finally:
            first.release()
        self.assertTrue(second.acquire())
        second.release()

    def test_tools_and_unknown_model_are_unscorable(self):
        for client, status in (
            (FakeClient(tool=True), "unscorable_tool_call"),
            (FakeClient(actual=""), "generated"),
            (FakeClient(actual="another-model", tool=True), "unscorable_model_identity"),
        ):
            self.assertEqual(evaluation._generate(client, [], client.model)["status"], status)
        class Unknown:
            def chat_raw(self, messages):
                return {"message":{"content":"Answer"}}
        self.assertEqual(evaluation._generate(Unknown(), [], "qwen3:1.7b")["status"], "unscorable_model_identity")

    def test_explicit_laptop_route_is_ephemeral_and_pc_needs_existing_pairing(self):
        config = {"hybrid_enabled": True, "auto_detect_ollama_model": False}
        with patch("app.hybrid.build_llm_client", return_value=self.client) as factory:
            client, name, route = REAL_SELECT_CLIENT(config, self.data, "laptop")
        self.assertIs(client, self.client)
        self.assertEqual(route, "local_host")
        self.assertFalse(factory.call_args.args[0]["hybrid_enabled"])
        self.assertTrue(config["hybrid_enabled"])
        with patch("app.hybrid.build_llm_client") as factory:
            with self.assertRaises(ValueError):
                REAL_SELECT_CLIENT({"hybrid_enabled":False}, self.data, "pc")
        factory.assert_not_called()

    def test_explicit_pc_run_rejects_a_fallback_route(self):
        class Hybrid:
            active_client = self.client
            def refresh_route(self):
                return {"compute":"local_host"}
        with patch("app.hybrid.build_llm_client", return_value=Hybrid()):
            with self.assertRaises(ValueError):
                REAL_SELECT_CLIENT({"hybrid_enabled":True}, self.data, "pc")

    def test_real_backend_handles_command_before_normal_inference_or_memory(self):
        db = Database(self.data / "personal_ai.db")
        user = db.create_user("Tester")
        chat = db.create_chat(user["id"], "Test")["id"]
        db.close()
        backend = gui_backend.ChatBackend.__new__(gui_backend.ChatBackend)
        backend.logger = logging.getLogger("conversation-command")
        backend.config = self.config
        with patch.object(gui_backend, "DATA_DIR", self.data), \
             patch.object(evaluation, "command", return_value="Conversation test queued") as action, \
             patch.object(evaluation, "begin") as begin, \
             patch.object(gui_backend, "build_llm_client") as build, \
             patch.object(gui_backend, "extract_and_store_memories") as memories:
            answer = backend.send(chat, "conversation test")
        self.assertEqual(answer, "Conversation test queued")
        action.assert_called_once()
        self.assertTrue(action.call_args.kwargs["defer"])
        begin.assert_called_once_with(self.data, chat)
        build.assert_not_called()
        memories.assert_not_called()


if __name__ == "__main__":
    unittest.main()
