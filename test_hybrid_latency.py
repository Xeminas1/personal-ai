"""Regression coverage for a reachable worker slower than the old limits."""
import json
import logging
import os
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from app import hybrid_autosetup
from app.hybrid import HybridOllamaClient, HybridWorkerClient, build_llm_client
from app.secrets import save_hybrid_worker_client_pairing, load_hybrid_worker_client_token


class SlowWorkerTests(unittest.TestCase):
    def test_slow_discovery_pairing_and_route_preserve_pending_credential(self):
        token = "regression-test-credential-32-characters"
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def respond(self, value, status=200):
                raw = json.dumps(value).encode()
                self.send_response(status)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                # Actual network latency beyond both former timeout limits.
                time.sleep(4.3)
                if self.path == "/api/health" and self.headers.get("Authorization") != "Bearer " + token:
                    self.respond({"ok": False}, 401)
                    return
                self.respond({"ok": True, "role": "xemai_hybrid_worker",
                              "recommended_model": "qwen3:8b", "machine_name": "Test-PC"})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append(body)
                self.respond({"ok": body == {"host_id": "laptop.tailnet.ts.net", "token": token}})

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = "http://127.0.0.1:" + str(server.server_port)
        config = {"model": "qwen3:1.7b", "hybrid_worker_port": 8766}
        request_json = hybrid_autosetup._request_json
        real_open = hybrid_autosetup.open_model_request

        def local_json(url, **kwargs):
            return request_json(base + url[url.index("/api/"):], **kwargs)

        def local_open(request, **kwargs):
            request.full_url = base + request.full_url[request.full_url.index("/api/"):]
            return real_open(request, **kwargs)

        try:
            with tempfile.TemporaryDirectory() as temporary:
                data = Path(temporary)
                save_hybrid_worker_client_pairing(data, host_id="laptop.tailnet.ts.net", token=token)
                with patch.dict(os.environ, {"XEMAI_WORKER_TOKEN": "", "XEMAI_WORKER_SERVER_TOKEN": ""}), \
                     patch.object(hybrid_autosetup, "DATA_DIR", data), \
                     patch.object(hybrid_autosetup, "load_config", side_effect=lambda: config.copy()), \
                     patch.object(hybrid_autosetup, "save_config", side_effect=lambda value: config.update(value)), \
                     patch.object(hybrid_autosetup, "_tailscale_exe", return_value="tailscale"), \
                     patch.object(hybrid_autosetup, "is_central_host", return_value=True), \
                     patch.object(hybrid_autosetup, "_peer_candidates", return_value=("laptop.tailnet.ts.net", ["pc.tailnet.ts.net"])), \
                     patch.object(hybrid_autosetup, "_request_json", side_effect=local_json), \
                     patch.object(hybrid_autosetup, "open_model_request", side_effect=local_open):
                    self.assertTrue(hybrid_autosetup.try_auto_pair())
                    self.assertEqual(load_hybrid_worker_client_token(data), token)
                    self.assertNotIn("hybrid_worker_pending_token", json.loads((data / "secrets.json").read_text()))
                    self.assertEqual(config["model"], "qwen3:1.7b")
                    self.assertTrue(config["hybrid_enabled"])
                    config["hybrid_worker_url"] = base
                    client = build_llm_client(config, logging.getLogger("regression"), data)
                    self.assertIsInstance(client, HybridOllamaClient)
                    self.assertEqual(client.refresh_route()["compute"], "remote_worker")
                    self.assertEqual(client.model, "qwen3:8b")
                    # Worker failure falls back, and recovery selects the worker again.
                    with patch.object(client.worker_client, "worker_health", side_effect=TimeoutError), \
                         patch.object(client.local_client, "discover_runtime_model", return_value={"model": "qwen3:1.7b", "source": "test"}):
                        self.assertEqual(client.refresh_route()["compute"], "local_host")
                        self.assertEqual(client.model, "qwen3:1.7b")
                    self.assertEqual(client.refresh_route()["compute"], "remote_worker")
                    self.assertEqual(len(calls), 1)
        finally:
            server.shutdown()
            server.server_close()
            thread.join()


if __name__ == "__main__":
    unittest.main()
