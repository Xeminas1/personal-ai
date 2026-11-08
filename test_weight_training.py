"""App-side owner-controlled weight training: teach, collection, pinning, worker endpoints.

Synthetic data only. No GPU, torch or Ollama needed.
"""
from __future__ import annotations

import json
import logging
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from app import weight_training as wt
from app.database import Database


def make_db(tmp: Path):
    db = Database(tmp / "personal_ai.db")
    user = db.get_user() or db.create_user("Owner")
    chat = db.create_chat(user["id"], "Test chat")
    return db, user["id"], chat["id"]


def local_reply(db, chat_id, text):
    return db.add_assistant_message(chat_id, text, compute_source="local_host", model="qwen3:8b")


class TeachAndCollectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db, self.user, self.chat = make_db(self.dir)
        self.addCleanup(self.db.close)

    def test_command_recognition_is_exact(self):
        for text in ["teach: Canberra.", "TEACH:  x y", "weights", "weights status", "weights setup",
                     "weights train", "weights use r3", "weights rollback", " Weights Train "]:
            self.assertTrue(wt.is_command(text), text)
        for text in ["teach me python", "weights are heavy", "weights use 3", "weights use r0",
                     "can you teach: things", "weights train now please", ""]:
            self.assertFalse(wt.is_command(text), text)

    def test_teach_saves_question_context_and_corrected_answer(self):
        self.db.add_message(self.chat, "user", "What's the capital of Australia?")
        local_reply(self.db, self.chat, "Sydney.")
        self.db.add_message(self.chat, "user", "teach: The capital of Australia is Canberra.")
        reply = wt.record_teach(self.dir, self.db, self.chat, "The capital of Australia is Canberra.")
        self.assertIn("Saved", reply)
        self.assertIn("9 more needed", reply)
        rows = [json.loads(l) for l in (self.dir / "weight_training" / "teach.jsonl").read_text().splitlines()]
        self.assertEqual(rows[0]["messages"], [
            {"role": "user", "content": "What's the capital of Australia?"},
            {"role": "assistant", "content": "The capital of Australia is Canberra."},
        ])

    def test_teach_keeps_earlier_turns_as_context(self):
        self.db.add_message(self.chat, "user", "I'm modding Skyrim SE with Vortex.")
        local_reply(self.db, self.chat, "Nice, what do you need?")
        self.db.add_message(self.chat, "user", "Which load order tool should I use?")
        local_reply(self.db, self.chat, "Use NMM.")
        wt.record_teach(self.dir, self.db, self.chat, "Vortex sorts load order itself via LOOT rules.")
        row = json.loads((self.dir / "weight_training" / "teach.jsonl").read_text().splitlines()[0])
        self.assertEqual([m["role"] for m in row["messages"]], ["user", "assistant", "user", "assistant"])
        self.assertEqual(row["messages"][-1]["content"], "Vortex sorts load order itself via LOOT rules.")
        self.assertEqual(row["messages"][-2]["content"], "Which load order tool should I use?")

    def test_teach_without_earlier_reply_is_refused(self):
        self.assertIn("no earlier", wt.record_teach(self.dir, self.db, self.chat, "Something"))
        self.assertIn("better answer", wt.record_teach(self.dir, self.db, self.chat, " "))
        self.assertFalse((self.dir / "weight_training" / "teach.jsonl").exists())

    def test_collect_uses_high_rated_local_replies_and_prefers_corrections(self):
        self.db.add_message(self.chat, "user", "Explain RAM briefly.")
        great = local_reply(self.db, self.chat, "RAM is short-term working memory.")
        self.db.rate_assistant_message(self.user, self.chat, great, 10, "overall", "")
        self.db.add_message(self.chat, "user", "Explain a CPU briefly.")
        poor = local_reply(self.db, self.chat, "It's a thing.")
        self.db.rate_assistant_message(self.user, self.chat, poor, 3, "overall", "")
        self.db.add_message(self.chat, "user", "Explain a GPU briefly.")
        app_reply = self.db.add_assistant_message(self.chat, "App text", compute_source="application")
        self.db.rate_assistant_message(self.user, self.chat, app_reply, 10, "overall", "")
        rows = wt.collect_examples(self.dir, self.db)
        self.assertEqual([r["source"] for r in rows], ["rated"])
        self.assertEqual(rows[0]["messages"][-1]["content"], "RAM is short-term working memory.")
        # Correcting the same prompt replaces the rated answer as the target.
        wt.record_teach(self.dir, self.db, self.chat, "A CPU executes program instructions.")
        self.db.add_message(self.chat, "user", "Explain RAM briefly.")
        sources = sorted(r["source"] for r in wt.collect_examples(self.dir, self.db))
        self.assertEqual(sources, ["rated", "teach"])


class FakeExecutor:
    label = "your PC"

    def __init__(self):
        self.trained = None
        self.used = []

    def status(self):
        return {"ok": True, "setup": "ready", "busy": "", "active": None, "runs": [
            {"run": "r1", "stage": "ready", "message": "Ready", "passed": True, "model": "xemai-qwen-tuned:r1",
             "evaluation": {"holdout_nll_base": 1.9, "holdout_nll_tuned": 1.4, "anchor_drift": 0.03}}]}

    def setup(self):
        return {"ok": True, "message": "Installing"}

    def train(self, examples, base):
        self.trained = (examples, base)
        return {"ok": True, "run": "r2", "examples": len(examples)}

    def use(self, run):
        self.used.append(run)
        return {"ok": True, "model": f"xemai-qwen-tuned:{run}" if run else None}


class CommandTests(TeachAndCollectTests):
    def test_train_needs_ten_examples_then_sends_them(self):
        ex = FakeExecutor()
        reply = wt.command(self.dir, self.db, self.chat, "weights train", executor=ex, ollama_base="qwen3:8b")
        self.assertIn("at least 10", reply)
        self.assertIsNone(ex.trained)
        rows = [{"source": "teach", "messages": [{"role": "user", "content": f"q{i}"},
                                                {"role": "assistant", "content": f"a{i}"}]} for i in range(12)]
        (self.dir / "weight_training").mkdir(exist_ok=True)
        (self.dir / "weight_training" / "teach.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        reply = wt.command(self.dir, self.db, self.chat, "weights train", executor=ex, ollama_base="qwen3:8b")
        self.assertIn("r2 started", reply)
        self.assertEqual(len(ex.trained[0]), 12)

    def test_status_use_and_rollback(self):
        ex = FakeExecutor()
        status = wt.command(self.dir, self.db, self.chat, "weights", executor=ex, ollama_base="qwen3:8b")
        self.assertIn("1.9 → 1.4", status)
        self.assertIn("original base model", status)
        self.assertIn("Switched to xemai-qwen-tuned:r1",
                      wt.command(self.dir, self.db, self.chat, "weights use r1", executor=ex, ollama_base="x"))
        self.assertIn("Rolled back",
                      wt.command(self.dir, self.db, self.chat, "weights rollback", executor=ex, ollama_base="x"))
        self.assertEqual(ex.used, ["r1", None])


class PinTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def make_run(self, run, passed=True):
        path = self.dir / "weight_training" / "runs" / run
        path.mkdir(parents=True)
        (path / "report.json").write_text(json.dumps({"passed": passed, "model": f"xemai-qwen-tuned:{run}"}))

    def test_only_passed_runs_can_be_activated(self):
        self.make_run("r1", passed=False)
        self.make_run("r2")
        self.assertFalse(wt.set_active(self.dir, "r1")["ok"])
        self.assertFalse(wt.set_active(self.dir, "r9")["ok"])
        self.assertFalse(wt.set_active(self.dir, "../r2")["ok"])
        self.assertIsNone(wt.active_tuned_model(self.dir))
        self.assertTrue(wt.set_active(self.dir, "r2")["ok"])
        self.assertEqual(wt.active_tuned_model(self.dir), "xemai-qwen-tuned:r2")
        wt.set_active(self.dir, None)
        self.assertIsNone(wt.active_tuned_model(self.dir))

    def test_local_discovery_ignores_unpinned_tuned_model_but_uses_pinned(self):
        from app import config
        from app.llm import OllamaClient

        client = OllamaClient(base_url="http://127.0.0.1:9", model="qwen3:8b",
                              logger=logging.getLogger("t"), provider_name="t")
        installed = [{"name": "qwen3:8b", "modified_at": "2026-01-01"},
                     {"name": "xemai-qwen-tuned:r2", "modified_at": "2026-11-08"}]
        with patch.object(config, "DATA_DIR", self.dir), \
             patch.object(OllamaClient, "installed_models", return_value=installed), \
             patch.object(OllamaClient, "running_models", return_value=[]):
            info = client.discover_runtime_model(preferred="qwen3:8b")
            self.assertEqual(info["model"], "qwen3:8b")  # newest tuned copy is NOT auto-picked
            self.assertNotIn("xemai-qwen-tuned:r2", info["installed_qwen"])
            self.make_run("r2")
            wt.set_active(self.dir, "r2")
            info = client.discover_runtime_model(preferred="qwen3:8b")
            self.assertEqual((info["model"], info["source"]), ("xemai-qwen-tuned:r2", "owner_tuned"))
            wt.set_active(self.dir, None)
            self.assertEqual(client.discover_runtime_model(preferred="qwen3:8b")["model"], "qwen3:8b")


class LocalTrainLaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def examples(self, n):
        return [{"source": "teach", "messages": [{"role": "user", "content": f"q{i}"},
                                                {"role": "assistant", "content": f"a{i}"}]} for i in range(n)]

    def test_refuses_before_setup_and_with_too_few_examples(self):
        result = wt.local_train(self.dir, self.examples(12), "qwen3:8b", "http://127.0.0.1:9")
        self.assertIn("weights setup", result["error"])
        self.mark_ready()
        self.assertIn("at least 10", wt.local_train(self.dir, self.examples(3), "qwen3:8b", "http://127.0.0.1:9")["error"])
        self.assertIn("Unknown base", wt.local_train(self.dir, self.examples(12), "xemai-qwen-tuned:r1", "http://127.0.0.1:9")["error"])

    def mark_ready(self):
        import sys

        python = wt.venv_python(self.dir)
        python.parent.mkdir(parents=True, exist_ok=True)
        if not python.exists():
            try:
                python.symlink_to(sys.executable)
            except OSError:
                import shutil
                shutil.copy(sys.executable, python)
        (self.dir / "weight_training" / "setup_status.json").write_text(json.dumps({"stage": "ready"}))

    def test_launch_creates_run_tracks_process_and_reports_failure_readably(self):
        self.mark_ready()
        result = wt.local_train(self.dir, self.examples(12), "qwen3:8b", "http://127.0.0.1:9")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["run"], "r1")
        run_dir = self.dir / "weight_training" / "runs" / "r1"
        self.assertEqual(len((run_dir / "dataset.jsonl").read_text().splitlines()), 12)
        # The real trainer runs (in this interpreter without a GPU stack it stops cleanly).
        for _ in range(200):
            if json.loads((run_dir / "status.json").read_text() if (run_dir / "status.json").exists() else "{}").get("stage") in {"ready", "failed"}:
                break
            time.sleep(0.1)
        status = wt.local_status(self.dir)
        self.assertEqual(status["runs"][0]["run"], "r1")
        self.assertIn(status["runs"][0]["stage"], {"failed", "ready"})
        self.assertTrue(status["runs"][0]["message"])
        self.assertEqual(wt.busy(self.dir), "")
        second = wt.local_train(self.dir, self.examples(12), "qwen3:8b", "http://127.0.0.1:9")
        self.assertEqual(second["run"], "r2")


class WorkerEndpointTests(unittest.TestCase):
    def setUp(self):
        from app import worker_server
        from app.worker_server import XemAiWorkerHandler, XemAiWorkerServer

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.patch = patch.object(worker_server, "DATA_DIR", self.dir)
        self.patch.start()
        self.addCleanup(self.patch.stop)

        class FakeOllama:
            base_url = "http://127.0.0.1:9"
            model = "qwen3.5:9b-q8_0"

            def installed_models(self):
                return [{"name": "qwen3.5:9b-q8_0", "details": {"parameter_size": "9B"}},
                        {"name": "xemai-qwen-tuned:r1", "details": {"parameter_size": "9B"}, "modified_at": "2099"}]

            def running_models(self):
                return []

        self.server = XemAiWorkerServer(("127.0.0.1", 0), XemAiWorkerHandler)
        self.server.worker_token = "worker-secret"
        self.server.ollama_client = FakeOllama()
        self.server.generation_lock = threading.Lock()
        self.server.xemai_logger = logging.getLogger("worker-test")
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close()))
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def call(self, path, payload=None, auth=True):
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = "Bearer worker-secret"
        request = urllib.request.Request(self.base + path, headers=headers,
                                         data=None if payload is None else json.dumps(payload).encode(),
                                         method="GET" if payload is None else "POST")
        try:
            response = self.opener.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def test_endpoints_require_pairing_token(self):
        for path, payload in [("/api/weights/status", None), ("/api/weights/train", {"examples": []}),
                              ("/api/weights/use", {"run": "r1"}), ("/api/weights/setup", {})]:
            self.assertEqual(self.call(path, payload, auth=False)[0], 401, path)

    def test_status_train_refusal_and_pin_drive_recommended_model(self):
        from app import worker_server

        code, status = self.call("/api/weights/status")
        self.assertEqual((code, status["setup"]), (200, "not_installed"))
        code, result = self.call("/api/weights/train", {"examples": []})
        self.assertFalse(result["ok"])
        # Unpinned tuned copy is never recommended, even though it's newest.
        self.assertEqual(worker_server._recommended_model(self.server.ollama_client)[0], "qwen3.5:9b-q8_0")
        run = self.dir / "weight_training" / "runs" / "r1"
        run.mkdir(parents=True)
        (run / "report.json").write_text(json.dumps({"passed": True, "model": "xemai-qwen-tuned:r1"}))
        self.assertEqual(self.call("/api/weights/use", {"run": "r1"})[1]["model"], "xemai-qwen-tuned:r1")
        self.assertEqual(worker_server._recommended_model(self.server.ollama_client)[0], "xemai-qwen-tuned:r1")
        self.assertEqual(worker_server._untuned_everyday_model(self.server.ollama_client), "qwen3.5:9b-q8_0")
        self.assertTrue(self.call("/api/weights/use", {"run": None})[1]["ok"])
        self.assertEqual(worker_server._recommended_model(self.server.ollama_client)[0], "qwen3.5:9b-q8_0")

    def test_health_reports_busy_while_training_so_host_falls_back(self):
        with patch.object(wt, "busy", return_value="training"):
            code, body = self.call("/api/health")
        self.assertEqual(code, 503)
        self.assertIn("busy with weight training", body["error"])


if __name__ == "__main__":
    unittest.main()
