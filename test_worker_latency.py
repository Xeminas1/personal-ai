"""HTTP coverage for worker model validation and non-sensitive phase timings."""
from __future__ import annotations

import json
import threading
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from app.worker_server import XemAiWorkerHandler, XemAiWorkerServer


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


if __name__ == "__main__":
    unittest.main()
