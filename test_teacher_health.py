"""Optional teacher discovery cannot make the ordinary worker unavailable."""
from __future__ import annotations

import json
import logging
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import Mock, patch

from app import worker_server
from app.worker_server import XemAiWorkerHandler, XemAiWorkerServer


class EverydayOllama:
    model = "qwen3:8b"

    def __init__(self):
        self.inventory_reads = 0
        self.running_reads = 0
        self.requests = []
        self.installed = ["qwen3:8b", "qwen3:14b", "qwen3:30b", "qwen2.5vl:7b"]

    def installed_models(self):
        self.inventory_reads += 1
        return [{"name": name} for name in self.installed]

    def running_models(self):
        self.running_reads += 1
        return [{"name": "qwen3:30b"}, {"name": "qwen2.5vl:7b"}]

    def _request(self, path, *, payload, timeout):
        self.requests.append((path, payload, timeout))
        return {"model": payload["model"], "message": {"role": "assistant", "content": "Everyday answer"}}


class TeacherHealthTests(unittest.TestCase):
    def setUp(self):
        self.server = XemAiWorkerServer(("127.0.0.1", 0), XemAiWorkerHandler)
        self.server.worker_token = "private-worker-credential"
        self.server.ollama_client = self.client = EverydayOllama()
        self.server.xemai_logger = logging.getLogger(self.id())
        self.server.generation_lock = threading.Lock()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path, payload=None, *, authenticated=True):
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = "Bearer " + self.server.worker_token
        request = urllib.request.Request(
            self.base + path, data=None if payload is None else json.dumps(payload).encode(),
            headers=headers, method="GET" if payload is None else "POST",
        )
        try:
            response = self.opener.open(request, timeout=3)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def test_health_reuses_inventory_and_never_runs_optional_teacher_probes(self):
        with patch.object(worker_server, "_teacher_model", side_effect=RuntimeError("private-teacher-failure")) as teacher, \
             patch.object(worker_server, "_teacher_target_model", side_effect=TimeoutError("private-hardware-failure")) as hardware, \
             patch.object(worker_server, "_installed_model_names", side_effect=RuntimeError("private-extra-inventory")) as inventory:
            code, health = self.request("/api/health")
            self.assertEqual(code, 200)
            self.assertTrue(health["ok"])
            self.assertEqual(health["recommended_model"], "qwen3:8b")
            self.assertEqual(health["teacher_model"], "")
            self.assertEqual(health["teacher_hardware"], {})  # Unknown, not guessed from a model name.
            self.assertNotIn("qwen2.5vl:7b", health["installed_qwen"])
            self.assertEqual(self.client.inventory_reads, 1)
            self.assertEqual(self.client.running_reads, 1)
            code, answer = self.request("/api/chat", {"model": "qwen3:8b", "messages": [{"role": "user", "content": "Question"}]})
            self.assertEqual(code, 200)
            self.assertEqual(answer["message"]["content"], "Everyday answer")
            self.assertEqual(self.client.requests[-1][1]["model"], "qwen3:8b")
            teacher.assert_not_called()
            hardware.assert_not_called()
            inventory.assert_not_called()

    def test_cached_hardware_preserves_preferred_teacher_without_fresh_probes(self):
        self.server.teacher_hardware = {"system_ram_gb": 32.0, "gpu_vram_gb": 16.0, "target_model": "qwen3:14b"}
        with patch.object(worker_server, "_teacher_target_model", side_effect=AssertionError("Health must not launch nvidia-smi")):
            for _ in range(2):
                code, health = self.request("/api/health")
                self.assertEqual(code, 200)
                self.assertEqual(health["teacher_model"], "qwen3:14b")
                self.assertEqual(health["teacher_hardware"], self.server.teacher_hardware)
                self.assertEqual(health["recommended_model"], "qwen3:8b")
        self.assertEqual(self.client.inventory_reads, 2)

    def test_malformed_optional_metadata_and_missing_teacher_keep_worker_healthy(self):
        self.server.teacher_hardware = {
            "system_ram_gb": True, "gpu_vram_gb": float("nan"),
            "target_model": "private-alternate-model", "private": "private-secret",
        }
        self.client.installed = ["qwen3:8b"]
        code, health = self.request("/api/health")
        self.assertEqual(code, 200)
        self.assertEqual(health["teacher_model"], "")
        self.assertEqual(health["teacher_hardware"], {})
        self.assertEqual(health["recommended_model"], "qwen3:8b")
        self.assertNotIn("private", json.dumps(health))
        self.assertEqual(self.request("/api/health", authenticated=False)[0], 401)

    def test_optional_preparation_failure_does_not_prevent_worker_startup(self):
        # Exercises the real lifecycle control flow without starting Ollama,
        # downloading a model, or using a user's installation/state directory.
        with tempfile.TemporaryDirectory() as temporary:
            server = Mock()
            server.serve_forever.side_effect = KeyboardInterrupt
            logger = Mock()
            with patch.object(worker_server, "load_config", return_value={}), \
                 patch.object(worker_server, "setup_logging", return_value=logger), \
                 patch.object(worker_server, "ensure_hybrid_worker_server_token", return_value="private-token"), \
                 patch.object(worker_server, "OllamaClient", return_value=self.client), \
                 patch.object(worker_server, "XemAiWorkerServer", return_value=server), \
                 patch.object(worker_server, "DATA_DIR", Path(temporary)), \
                 patch.object(worker_server, "_ensure_teacher_model_async", side_effect=RuntimeError("private-setup-failure")):
                self.assertEqual(worker_server.run_worker_server(), 0)
            server.serve_forever.assert_called_once()
            server.server_close.assert_called_once()
            self.assertNotIn("private-setup-failure", str(logger.mock_calls))


if __name__ == "__main__":
    unittest.main()
