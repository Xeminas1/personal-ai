"""HTTP coverage for worker model validation and non-sensitive phase timings."""
from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import logging
import time
from types import SimpleNamespace
from unittest.mock import patch
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from app.worker_server import (
    XemAiWorkerHandler, XemAiWorkerServer, _recommended_model,
    _specialist_model, PREFERRED_EVERYDAY_MODEL,
)
from app.llm import OllamaClient
from app.hybrid import HybridWorkerClient


class CapturingLogger:
    def __init__(self):
        self.timings = []
        self.recorded = threading.Event()

    def debug(self, *args):
        pass

    def info(self, template, *values):
        self.timings.append((template, values))
        self.recorded.set()


class FakeOllama:
    def __init__(self):
        self.installed_calls = 0
        self.running_calls = 0
        self.requests = []
        self.allow_running = False
        self.fail_generation = False

    def installed_models(self):
        self.installed_calls += 1
        return [{"name": "qwen3:8b"}, {"name": "qwen3:1.7b"}, {"name": "llama3:8b"}]

    def running_models(self):
        self.running_calls += 1
        if not self.allow_running:
            raise AssertionError("Explicit-model inference must not discover running models")
        return [{"name": "qwen3:1.7b"}]

    def _request(self, path, *, payload, timeout):
        self.requests.append((path, dict(payload), timeout))
        if self.fail_generation:
            raise RuntimeError("test private generation failure")
        return {"message": {"role": "assistant", "content": "ok"}, "model": payload["model"]}


class ObservedLock:
    def __init__(self):
        self.lock = threading.Lock()
        self.waiting = threading.Event()

    def __enter__(self):
        self.waiting.set()
        self.lock.acquire()

    def __exit__(self, *args):
        self.lock.release()


class WorkerLatencyTests(unittest.TestCase):
    def setUp(self):
        self.server = XemAiWorkerServer(("127.0.0.1", 0), XemAiWorkerHandler)
        self.server.worker_token = "private-worker-test-token"
        self.server.ollama_client = self.ollama = FakeOllama()
        self.server.generation_lock = threading.Lock()
        self.server.xemai_logger = self.logger = CapturingLogger()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, payload, *, authenticated=True):
        headers = {"Content-Type": "application/json"}
        if authenticated:
            headers["Authorization"] = "Bearer " + self.server.worker_token
        request = urllib.request.Request(
            self.base + "/api/chat", data=json.dumps(payload).encode(),
            headers=headers, method="POST",
        )
        try:
            response = self.opener.open(request, timeout=3)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, json.load(response)

    def timing(self):
        self.assertTrue(self.logger.recorded.wait(2), "Missing worker timing event")
        template, values = self.logger.timings[-1]
        self.assertEqual(template, "Worker timing | discovery_ms=%d queue_ms=%d generation_ms=%d success=%s")
        self.assertTrue(all(isinstance(value, int) and value >= 0 for value in values[:3]))
        self.assertIsInstance(values[3], bool)
        return values

    def test_explicit_model_skips_running_discovery_and_preserves_request(self):
        sentinel = "private prompt must not appear in timing"
        status, data = self.request({"model": "qwen3:8b", "messages": [{"role": "user", "content": sentinel}], "stream": True})
        self.assertEqual(status, 200)
        self.assertEqual(data["model"], "qwen3:8b")
        self.assertEqual(self.ollama.installed_calls, 1)
        self.assertEqual(self.ollama.running_calls, 0)
        path, payload, timeout = self.ollama.requests[0]
        self.assertEqual(path, "/api/chat")
        self.assertEqual(timeout, 600)
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["messages"][0]["content"], sentinel)
        self.assertTrue(self.timing()[3])
        serialized = repr(self.logger.timings)
        self.assertNotIn(sentinel, serialized)
        self.assertNotIn(self.server.worker_token, serialized)

    def test_unauthorized_and_invalid_models_never_generate(self):
        self.assertEqual(self.request({"model": "qwen3:8b"}, authenticated=False)[0], 401)
        self.assertEqual(self.ollama.installed_calls, 0)
        for model in ("qwen3:32b", "llama3:8b", " "):
            with self.subTest(model=model):
                self.assertEqual(self.request({"model": model})[0], 400)
        self.assertEqual(self.ollama.running_calls, 0)
        self.assertEqual(self.ollama.requests, [])

    def test_omitted_model_still_uses_running_recommendation(self):
        self.ollama.allow_running = True
        status, data = self.request({"messages": []})
        self.assertEqual(status, 200)
        self.assertEqual(data["model"], "qwen3:1.7b")
        self.assertEqual(self.ollama.installed_calls, 1)
        self.assertEqual(self.ollama.running_calls, 1)

    def test_queue_time_is_measured_separately_from_generation(self):
        observed = ObservedLock()
        self.server.generation_lock = observed
        observed.lock.acquire()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.request, {"model": "qwen3:8b", "messages": []})
            try:
                self.assertTrue(observed.waiting.wait(2), "Request did not reach the queue")
                # Keep the real request queued briefly using a bounded event wait.
                self.assertFalse(self.logger.recorded.wait(0.03))
                self.assertFalse(future.done())
            finally:
                observed.lock.release()
            self.assertEqual(future.result(timeout=2)[0], 200)
        discovery_ms, queue_ms, generation_ms, success = self.timing()
        self.assertGreaterEqual(queue_ms, 20)
        self.assertTrue(success)

    def test_failed_generation_also_logs_numeric_timing(self):
        self.ollama.fail_generation = True
        self.assertEqual(self.request({"model": "qwen3:8b", "messages": []})[0], 500)
        self.assertFalse(self.timing()[3])
        self.assertNotIn("test private generation failure", repr(self.logger.timings))

    def test_health_uses_inventory_once_without_a_duplicate_connectivity_probe(self):
        self.ollama.allow_running = True

        def duplicate_probe():
            self.fail("Inventory already checks model connectivity")

        self.ollama.health_check = duplicate_probe
        request = urllib.request.Request(self.base + "/api/health", headers={
            "Authorization": "Bearer " + self.server.worker_token,
        })
        with self.opener.open(request, timeout=3) as response:
            self.assertEqual(response.status, 200)
            health = json.load(response)
        self.assertTrue(health["ok"])
        self.assertEqual(health["recommended_model"], "qwen3:1.7b")
        self.assertEqual(self.ollama.installed_calls, 1)
        self.assertEqual(self.ollama.running_calls, 1)

    def test_qwen35_host_disables_thinking_through_real_worker_http(self):
        # Regression: health selected the 9B model, yet a response containing
        # only message.thinking caused HybridOllamaClient to fall back to 1.7B.
        # Verify the *real host->worker HTTP payload* includes think=false.
        prior_models = self.ollama.installed_models
        self.ollama.installed_models = lambda: [
            *prior_models(),
            {"name": "qwen3.5:9b-q8_0", "details": {"parameter_size": "9B"}},
        ]
        client = HybridWorkerClient(
            self.base, self.server.worker_token,
            "qwen3.5:9b-q8_0", logging.getLogger("qwen35.http"),
        )
        response = client.chat_raw([
            {"role": "user", "content": "Briefly explain aimKeyA."}
        ])
        self.assertEqual(response["message"]["content"], "ok")
        path, forwarded, timeout = self.ollama.requests[-1]
        self.assertEqual(path, "/api/chat")
        self.assertEqual(forwarded["model"], "qwen3.5:9b-q8_0")
        self.assertIs(forwarded["think"], False)
        self.assertEqual(timeout, 600)

    def test_unreachable_ollama_health_keeps_service_unavailable_status(self):
        def unavailable():
            raise RuntimeError("private-connection-error")

        self.ollama.installed_models = unavailable
        request = urllib.request.Request(self.base + "/api/health", headers={
            "Authorization": "Bearer " + self.server.worker_token,
        })
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.opener.open(request, timeout=3)
        with caught.exception as response:
            self.assertEqual(response.status, 503)
            self.assertNotIn("private-connection-error", response.read().decode())



class Qwen35UpgradeTests(unittest.TestCase):
    """Installed 9B must become the everyday worker without losing old 8B."""

    @staticmethod
    def inventory(include_9b=True):
        installed = [
            {"name": "qwen3:8b", "details": {"parameter_size": "8.2B"}},
            {"name": "qwen2.5vl:7b", "capabilities": ["vision"]},
        ]
        if include_9b:
            installed.append({
                "name": "qwen3.5:9b-q8_0",
                "details": {"family": "qwen35", "parameter_size": "9B"},
                "capabilities": ["completion", "vision", "tools", "thinking"],
            })
        return installed

    def test_multimodal_qwen35_is_an_everyday_chat_model(self):
        candidates = OllamaClient._qwen_models(self.inventory())
        self.assertEqual(
            {item["name"] for item in candidates},
            {"qwen3:8b", PREFERRED_EVERYDAY_MODEL},
        )

    def test_prefer_installed_9b_even_with_configured_old_8b(self):
        installed = self.inventory()
        fake = SimpleNamespace(
            model="qwen3:8b",
            installed_models=lambda: installed,
            running_models=lambda: [{"name": "qwen3:8b"}],
        )
        model, available, running = _recommended_model(fake)
        self.assertEqual(model, PREFERRED_EVERYDAY_MODEL)
        self.assertIn(PREFERRED_EVERYDAY_MODEL, available)
        self.assertEqual(running, ["qwen3:8b"])

    def test_keep_eight_b_until_nine_b_is_actually_installed(self):
        fake = SimpleNamespace(
            model="qwen3:8b",
            installed_models=lambda: self.inventory(False),
            running_models=lambda: [],
        )
        model, available, _ = _recommended_model(fake)
        self.assertEqual(model, "qwen3:8b")
        self.assertNotIn(PREFERRED_EVERYDAY_MODEL, available)

    def test_qwen35_chat_avoids_empty_thinking_only_responses(self):
        client = OllamaClient(
            base_url="http://localhost.invalid:11434",
            model=PREFERRED_EVERYDAY_MODEL,
            logger=logging.getLogger("qwen35.thinking"),
        )
        captured = []

        def fake_ollama(path, payload=None, timeout=600):
            captured.append(payload)
            if payload.get("think") is False:
                return {"model": payload["model"],
                        "message": {"role": "assistant", "content": "Use aimKeyA."}}
            return {"model": payload["model"],
                    "message": {"role": "assistant", "content": "",
                                "thinking": "Reasoning with no final answer."}}

        with patch.object(client, "_request", side_effect=fake_ollama):
            answer = client.chat([{"role": "user", "content": "How does aimKeyA work?"}])
        self.assertEqual(answer, "Use aimKeyA.")
        self.assertEqual(len(captured), 1)
        self.assertIs(captured[0]["think"], False)
        self.assertNotIn("think", captured[0].get("options", {}))

    def test_qwen35_json_mode_and_tool_call_also_disable_thinking(self):
        client = OllamaClient(
            base_url="http://localhost.invalid:11434",
            model=PREFERRED_EVERYDAY_MODEL,
            logger=logging.getLogger("qwen35.tools"),
        )
        captured = []

        def fake_ollama(path, payload=None, timeout=600):
            captured.append(payload)
            return {"model": payload["model"],
                    "message": {"role": "assistant", "content": "{}"}}

        with patch.object(client, "_request", side_effect=fake_ollama):
            client.chat_raw([], json_mode=True)
            client.chat_raw([], tools=[{
                "type": "function",
                "function": {"name": "test", "parameters": {"type": "object"}},
            }])
        self.assertTrue(all(p.get("think") is False for p in captured))
        self.assertEqual(captured[0]["format"], "json")
        self.assertEqual(len(captured[1]["tools"]), 1)

    def test_old_qwen3_keeps_existing_thinking_behavior(self):
        client = OllamaClient(
            base_url="http://localhost.invalid:11434",
            model="qwen3:8b",
            logger=logging.getLogger("qwen3.legacy"),
        )
        captured = []

        def fake_ollama(path, payload=None, timeout=600):
            captured.append(payload)
            return {"model": payload["model"],
                    "message": {"role": "assistant", "content": "Old Qwen is intact."}}

        with patch.object(client, "_request", side_effect=fake_ollama):
            self.assertEqual(client.chat([]), "Old Qwen is intact.")
        self.assertNotIn("think", captured[0])

    def test_nine_b_is_eligible_for_read_only_specialists(self):
        fake = SimpleNamespace(ollama_client=SimpleNamespace(model="qwen3:8b"))
        with patch("app.worker_server._deadline_inventory", return_value=self.inventory()):
            selected = _specialist_model(
                fake, "planner", PREFERRED_EVERYDAY_MODEL,
                time.monotonic() + 3,
            )
        self.assertEqual(selected, PREFERRED_EVERYDAY_MODEL)



if __name__ == "__main__":
    unittest.main()
