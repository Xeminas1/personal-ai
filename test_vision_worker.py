"""Real HTTP coverage for optional vision, bounded frames and shared inference."""
from __future__ import annotations

import base64
import json
import logging
import struct
import threading
import time
import unittest
import urllib.error
import urllib.request
import zlib
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from app.llm import OllamaClient
from app.vision import MAX_IMAGE_BYTES, MAX_OBSERVATION_CHARS, VISION_MODEL, VisionService
from app.worker_server import XemAiWorkerHandler, XemAiWorkerServer


def png_frame(width=1, height=1):
    def chunk(kind, content):
        return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content))

    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    # A valid small RGB PNG fixture. Oversized dimensions are used only to test
    # rejection before any image reaches a decoder or model.
    raw = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
    raw += chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00")) + chunk(b"IEND", b"")
    return base64.b64encode(raw).decode("ascii")


class FakeOllama:
    def __init__(self):
        self.vision_installed = True
        self.capabilities = ["completion", "vision"]
        self.requests = []
        self.pull_started = threading.Event()
        self.allow_pull = threading.Event()
        self.allow_pull.set()
        self.analysis_started = threading.Event()
        self.allow_analysis = threading.Event()
        self.allow_analysis.set()
        self.pull_count = 0
        self.fail_pull = False
        self.fail_analysis = False
        self.observations = "Observed a visible crosshair and scope overlay."
        self.state_lock = threading.Lock()
        self.active_inference = 0
        self.max_active_inference = 0

    def installed_models(self):
        models = [{"name": "qwen3:8b", "modified_at": "2025-01-01", "details": {"parameter_size": "8B"}}]
        if self.vision_installed:
            models.append({"name": VISION_MODEL, "modified_at": "2026-01-01", "details": {"parameter_size": "7B"}})
        return models

    def running_models(self):
        return [{"name": VISION_MODEL, "expires_at": "2099-01-01"}] if self.vision_installed else []

    def _request(self, path, *, payload, timeout):
        with self.state_lock:
            self.requests.append((path, payload, timeout))
        if path == "/api/show":
            return {"capabilities": self.capabilities}
        if path == "/api/pull":
            self.pull_count += 1
            self.pull_started.set()
            if not self.allow_pull.wait(3):
                raise TimeoutError("private-download-failure")
            if self.fail_pull:
                raise RuntimeError("private-download-credential")
            self.vision_installed = True
            return {"status": "success"}
        if path == "/api/chat":
            with self.state_lock:
                self.active_inference += 1
                self.max_active_inference = max(self.max_active_inference, self.active_inference)
            try:
                visual = payload.get("model") == VISION_MODEL
                if visual:
                    self.analysis_started.set()
                    if not self.allow_analysis.wait(3) or self.fail_analysis:
                        raise RuntimeError("private-analysis-credential")
                return {"model": payload["model"], "message": {"content": self.observations if visual else "Normal text reply"}}
            finally:
                with self.state_lock:
                    self.active_inference -= 1
        raise AssertionError("Unexpected Ollama request")


class VisionWorkerTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger(f"vision.tests.{self.id()}")
        self.ollama = FakeOllama()
        self.server = XemAiWorkerServer(("127.0.0.1", 0), XemAiWorkerHandler)
        self.server.worker_token = "private-worker-credential"
        self.server.ollama_client = self.ollama
        self.server.xemai_logger = self.logger
        self.server.generation_lock = threading.Lock()
        self.service = self.server.vision_service = VisionService(self.ollama, self.server.generation_lock, self.logger)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def close(self):
        self.ollama.allow_pull.set()
        self.ollama.allow_analysis.set()
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

    def wait_setup_finished(self):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            code, status = self.request("/api/vision/status")
            self.assertEqual(code, 200)
            if not status["installing"]:
                return status
        self.fail("Vision setup did not finish")

    def test_authentication_and_fixed_setup_parameters(self):
        for path, payload in (("/api/vision/status", None), ("/api/vision/setup", {}), ("/api/vision/analyse", {"images": [png_frame()], "prompt": "Inspect this frame"})):
            with self.subTest(path=path):
                self.assertEqual(self.request(path, payload, authenticated=False)[0], 401)
        self.assertEqual(self.ollama.requests, [])
        code, error = self.request("/api/vision/setup", {"model": "private-alternate-model"})
        self.assertEqual(code, 400)
        self.assertNotIn("private-alternate-model", error["error"])
        self.assertEqual(self.ollama.pull_count, 0)

    def test_status_and_missing_model_never_download_automatically(self):
        self.ollama.vision_installed = False
        self.assertFalse(self.request("/api/vision/status")[1]["ready"])
        code, result = self.request("/api/vision/analyse", {"images": [png_frame()], "prompt": "Inspect a scope"})
        self.assertEqual(code, 200)
        self.assertFalse(result["ready"])
        self.assertEqual(result["observed_text"], "")
        self.assertTrue(result["error"])
        self.assertEqual(self.ollama.pull_count, 0)
        self.assertEqual(self.ollama.requests, [])
        self.ollama.vision_installed = True
        self.ollama.capabilities = ["completion"]
        self.assertFalse(self.request("/api/vision/status")[1]["ready"])
        self.assertFalse(self.request("/api/vision/analyse", {"images": [png_frame()], "prompt": "Inspect"})[1]["ready"])
        self.assertFalse(any(path == "/api/chat" for path, _, _ in self.ollama.requests))

    def test_valid_frames_preserve_image_data_and_bound_observations_without_logging_content(self):
        images = [png_frame()] * 4
        prompt = "private-visual-prompt"
        self.ollama.observations = "visible-private-observation " * 400
        with self.assertLogs(self.logger, level="INFO") as logs:
            code, result = self.request("/api/vision/analyse", {"images": images, "prompt": prompt})
        self.assertEqual(code, 200)
        self.assertTrue(result["ready"])
        self.assertEqual(result["model"], VISION_MODEL)
        self.assertLessEqual(len(result["observed_text"]), MAX_OBSERVATION_CHARS)
        _, payload, timeout = next(entry for entry in self.ollama.requests if entry[0] == "/api/chat")
        self.assertEqual(payload["messages"][-1]["images"], images)
        self.assertEqual(payload["messages"][-1]["content"], prompt)
        self.assertFalse(payload["think"])
        self.assertEqual(payload["keep_alive"], 0)
        self.assertEqual(payload["options"]["num_predict"], 512)
        self.assertEqual(payload["options"]["num_ctx"], 8192)
        self.assertLessEqual(timeout, 180)
        emitted = "\n".join(logs.output)
        for private_value in (prompt, images[0], "visible-private-observation", self.server.worker_token):
            self.assertNotIn(private_value, emitted)

    def test_invalid_image_types_sizes_dimensions_and_prompts_never_infer(self):
        oversized = base64.b64encode(b"x" * (MAX_IMAGE_BYTES + 1)).decode()
        invalid_images = (None, "not-a-list", [], [png_frame()] * 5, [12], ["private-invalid-base64"],
                          [base64.b64encode(b"GIF89a").decode()], [oversized], [png_frame(2049, 1)], [png_frame(2048, 1024)])
        for images in invalid_images:
            with self.subTest(images_type=type(images).__name__):
                code, error = self.request("/api/vision/analyse", {"images": images, "prompt": "Inspect"})
                self.assertEqual(code, 400)
                self.assertNotIn("private-invalid-base64", error["error"])
        for prompt in (None, 123, "", "x" * 4001, "bad\x00prompt"):
            with self.subTest(prompt_type=type(prompt).__name__):
                self.assertEqual(self.request("/api/vision/analyse", {"images": [png_frame()], "prompt": prompt})[0], 400)
        self.assertEqual(self.request("/api/vision/analyse", {"images": [png_frame()], "prompt": "Inspect", "model": "another-model"})[0], 400)
        self.assertEqual(self.ollama.requests, [])

    def test_user_started_setup_is_async_single_and_does_not_block_text_inference(self):
        self.ollama.vision_installed = False
        self.ollama.allow_pull.clear()
        code, result = self.request("/api/vision/setup", {})
        self.assertEqual(code, 200)
        self.assertTrue(result["installing"])
        self.assertTrue(self.ollama.pull_started.wait(1))
        self.assertTrue(self.request("/api/vision/setup", {})[1]["installing"])
        self.assertTrue(self.request("/api/vision/status")[1]["installing"])
        # A download uses its separate setup guard; ordinary model replies do
        # not wait for multiple gigabytes of files to arrive.
        code, text = self.request("/api/chat", {"model": "qwen3:8b", "messages": []})
        self.assertEqual(code, 200)
        self.assertEqual(text["message"]["content"], "Normal text reply")
        self.assertEqual(self.ollama.pull_count, 1)
        pull = next(entry for entry in self.ollama.requests if entry[0] == "/api/pull")
        self.assertEqual(pull[1], {"model": VISION_MODEL, "stream": False})
        self.ollama.allow_pull.set()
        self.assertTrue(self.wait_setup_finished()["ready"])

    def test_vision_and_text_inference_share_the_worker_generation_lock(self):
        self.ollama.allow_analysis.clear()
        with ThreadPoolExecutor(max_workers=2) as pool:
            vision = pool.submit(self.request, "/api/vision/analyse", {"images": [png_frame()], "prompt": "Inspect"})
            self.assertTrue(self.ollama.analysis_started.wait(1))
            text = pool.submit(self.request, "/api/chat", {"model": "qwen3:8b", "messages": []})
            try:
                with self.assertRaises(TimeoutError):
                    text.result(timeout=0.05)
            finally:
                self.ollama.allow_analysis.set()
            self.assertTrue(vision.result(timeout=2)[1]["ready"])
            self.assertEqual(text.result(timeout=2)[0], 200)
        self.assertEqual(self.ollama.max_active_inference, 1)

    def test_failures_have_generic_messages_and_no_private_diagnostic_values(self):
        self.ollama.fail_analysis = True
        with self.assertLogs(self.logger, level="INFO") as logs:
            code, result = self.request("/api/vision/analyse", {"images": [png_frame()], "prompt": "private-prompt"})
        self.assertEqual(code, 200)
        self.assertFalse(result["ready"])
        self.assertEqual(result["observed_text"], "")
        self.assertNotIn("private", result["error"])
        self.assertNotIn("private", "\n".join(record.getMessage() for record in logs.records))
        self.ollama.vision_installed = False
        self.ollama.fail_pull = True
        self.request("/api/vision/setup", {})
        status = self.wait_setup_finished()
        self.assertFalse(status["ready"])
        self.assertNotIn("private", status["error"])

    def test_newly_installed_or_running_vision_never_changes_text_model_selection(self):
        code, health = self.request("/api/health")
        self.assertEqual(code, 200)
        self.assertEqual(health["recommended_model"], "qwen3:8b")
        self.assertNotIn(VISION_MODEL, health["installed_qwen"])
        local = OllamaClient("http://127.0.0.1:1", "qwen3:8b", self.logger)
        with patch.object(local, "installed_models", side_effect=self.ollama.installed_models), \
             patch.object(local, "running_models", side_effect=self.ollama.running_models):
            self.assertEqual(local.discover_runtime_model(preferred="qwen3:8b")["model"], "qwen3:8b")
        renamed_visual = [{"name": "custom-qwen:7b", "details": {"family": "qwen2_5_vl"}}, {"name": "qwen3:8b"}]
        self.assertEqual([item["name"] for item in local._qwen_models(renamed_visual)], ["qwen3:8b"])


if __name__ == "__main__":
    unittest.main()
