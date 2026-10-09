"""A failed route is selected once per reply, with safe typed diagnostics."""
from __future__ import annotations

import errno
import io
import json
import logging
import socket
import ssl
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import Mock

from app.hybrid import HybridOllamaClient, HybridWorkerClient, _error_diagnostics
from app.llm import OllamaError


class LocalClient:
    model = "qwen3:1.7b"
    base_url = "http://local.invalid"

    def __init__(self):
        self.discoveries = 0
        self.calls = []

    def discover_runtime_model(self, preferred=None):
        self.discoveries += 1
        return {"model": self.model, "source": "test"}

    def chat_raw(self, messages, *, json_mode=False, tools=None):
        self.calls.append((messages, json_mode, tools))
        return {"model": self.model, "message": {"role": "assistant", "content": "local answer"}}


class HybridTurnTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger("hybrid_turn." + self.id())
        self.local = LocalClient()

    def hybrid(self, worker):
        return HybridOllamaClient(local_client=self.local, worker_client=worker,
            logger=self.logger, local_fallback_model="qwen3:1.7b")

    def test_real_http_failed_health_is_not_repeated_for_answer_tools_retry_memory(self):
        state = {"healthy": False, "health_calls": 0, "chat_calls": 0}
        token = "private-worker-credential-sentinel"
        secret = "private-error-body-prompt-sentinel"

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self, payload, status=200):
                raw = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                state["health_calls"] += 1
                if self.headers.get("Authorization") != "Bearer " + token:
                    self.respond({"error": secret}, 401)
                elif not state["healthy"]:
                    self.respond({"error": secret}, 503)
                else:
                    self.respond({"ok": True, "recommended_model": "qwen3:8b"})

            def do_POST(self):
                state["chat_calls"] += 1
                self.rfile.read(int(self.headers["Content-Length"]))
                self.respond({"model": "qwen3:8b", "message": {"content": "worker answer"}})

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def close():
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.addCleanup(close)
        url = f"http://127.0.0.1:{server.server_port}"
        worker = HybridWorkerClient(url, token, "qwen3:8b", self.logger)
        client = self.hybrid(worker)
        client.turn_id = "0123456789abcdef"
        with self.assertLogs(self.logger, level="INFO") as captured:
            self.assertEqual(client.discover_runtime_model()["compute"], "local_host")
            self.assertEqual(client.chat([]), "local answer")
            client.chat_raw([], tools=[{"type": "function"}])
            client.chat([])
            client.chat([], json_mode=True)
        self.assertEqual(state["health_calls"], 1)
        self.assertEqual(state["chat_calls"], 0)
        self.assertEqual(self.local.discoveries, 1)
        self.assertEqual(len(self.local.calls), 4)
        self.assertTrue(client.worker_failed_for_request)
        logs = "\n".join(record.getMessage() for record in captured.records)
        self.assertIn("stage=worker_health", logs)
        self.assertIn("turn_id=0123456789abcdef", logs)
        self.assertIn("error_category=http http_status=503", logs)
        for private in (secret, token, url):
            self.assertNotIn(private, logs)
        state["healthy"] = True
        self.assertEqual(client.discover_runtime_model()["compute"], "remote_worker")
        self.assertFalse(client.worker_failed_for_request)
        self.assertEqual(client.chat([]), "worker answer")
        self.assertEqual(state["health_calls"], 2)
        self.assertEqual(state["chat_calls"], 1)

    def test_worker_chat_failure_latches_fallback_and_explicit_refresh_recovers(self):
        worker = Mock(model="qwen3:8b", base_url="https://private-worker.invalid")
        worker.worker_health.return_value = {"ok": True, "recommended_model": "qwen3:8b"}
        worker.chat_raw.side_effect = [TimeoutError("private-secret-error"), {"message": {"content": "recovered"}}]
        client = self.hybrid(worker)
        client.turn_id = "private-secret-invalid-trace-id"
        with self.assertLogs(self.logger, level="INFO") as captured:
            client.discover_runtime_model()
            self.assertEqual(client.chat([]), "local answer")
            self.assertEqual(client.chat([], json_mode=True), "local answer")
        self.assertEqual(worker.worker_health.call_count, 1)
        self.assertEqual(worker.chat_raw.call_count, 1)
        self.assertEqual(self.local.discoveries, 1)
        self.assertTrue(client.worker_failed_for_request)
        logs = "\n".join(record.getMessage() for record in captured.records)
        self.assertIn("stage=worker_chat", logs)
        self.assertIn("turn_id=none", logs)
        self.assertIn("error_category=timeout", logs)
        self.assertNotIn("private-secret-error", logs)
        self.assertNotIn(client.turn_id, logs)
        self.assertNotIn("https://private-worker.invalid", logs)
        self.assertEqual(client.refresh_route()["compute"], "remote_worker")
        self.assertFalse(client.worker_failed_for_request)
        self.assertEqual(client.chat([]), "recovered")

    def test_typed_error_causes_and_untrusted_strings_are_not_exported(self):
        secret = "secret-url-header-body-token-sentinel"
        refused = ConnectionRefusedError(errno.ECONNREFUSED, secret)
        refused.winerror = 10061
        examples = [
            (urllib.error.HTTPError("https://" + secret, 401, secret, {"Authorization": secret}, io.BytesIO(secret.encode())), "http", 401),
            (ssl.SSLCertVerificationError(1, secret), "tls_verification", -1),
            (ssl.SSLError(1, secret), "tls", -1),
            (socket.gaierror(-2, secret), "dns", -1),
            (TimeoutError(secret), "timeout", -1),
            (refused, "refused", -1),
            (ConnectionResetError(errno.ECONNRESET, secret), "reset", -1),
            (ConnectionAbortedError(errno.ECONNABORTED, secret), "aborted", -1),
            (OSError(errno.EHOSTUNREACH, secret), "unreachable", -1),
            (urllib.error.URLError(secret), "connection", -1),
            (RuntimeError(secret), "model_error", -1),
        ]
        for cause, category, status in examples:
            wrapped = OllamaError(secret)
            wrapped.__cause__ = cause if category == "model_error" else urllib.error.URLError(cause)
            with self.subTest(category=category):
                details = _error_diagnostics(wrapped)
                self.assertEqual(details["error_category"], category)
                self.assertEqual(details["http_status"], status)
                self.assertNotIn(secret, json.dumps(details))
                self.assertTrue(all(isinstance(details[field], int) for field in ("errno", "winerror", "http_status")))
        self.assertEqual(_error_diagnostics(urllib.error.URLError(socket.gaierror(-2, secret)))["errno"], -2)
        self.assertEqual(_error_diagnostics(urllib.error.URLError(refused))["winerror"], 10061)
        self.assertEqual(_error_diagnostics(None)["error_category"], "none")
        cycle = OllamaError(secret)
        cycle.__cause__ = cycle
        self.assertEqual(_error_diagnostics(cycle)["error_category"], "model_error")
        malformed = OSError(secret)
        malformed.errno = [secret]
        malformed.winerror = {"private": secret}
        self.assertEqual(_error_diagnostics(malformed), {
            "error_category": "connection", "http_status": -1, "errno": -1, "winerror": -1,
        })

    def test_diagnostic_failure_does_not_change_response_or_fallback(self):
        worker = Mock(model="qwen3:8b", base_url="https://private-worker.invalid")
        worker.worker_health.return_value = {"ok": True, "recommended_model": "qwen3:8b"}
        response = {"message": {"content": "valid worker answer"}}
        worker.chat_raw.side_effect = [response, TimeoutError("private-error")]
        client = self.hybrid(worker)
        logger = Mock()
        def fail_attempt(message, *args):
            if message.startswith("Hybrid attempt |"):
                raise RuntimeError("broken diagnostic handler")
        logger.info.side_effect = fail_attempt
        client.logger = logger
        self.assertEqual(client.discover_runtime_model()["compute"], "remote_worker")
        self.assertIs(client.chat_raw([]), response)
        self.assertEqual(client.chat([]), "local answer")
        self.assertTrue(client.worker_failed_for_request)
        self.assertEqual(client.route_info["compute"], "local_host")


if __name__ == "__main__":
    unittest.main()
