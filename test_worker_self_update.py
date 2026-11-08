"""The PC worker loads updates by itself instead of running stale code until a reboot."""
from __future__ import annotations

import json
import logging
import socket
import tempfile
import threading
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from app import restart_supervisor, weight_training as wt, worker_server
from app.version import VERSION


def bump(version: str) -> str:
    parts = version.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    return ".".join(parts)


def fake_server():
    return SimpleNamespace(generation_lock=threading.Lock(), xemai_logger=logging.getLogger("t"),
                           server_address=("127.0.0.1", 8766))


class UpdateStepTests(unittest.TestCase):
    def setUp(self):
        self.restarts = []
        patcher = patch.object(worker_server, "_schedule_worker_restart",
                               side_effect=lambda server, v: self.restarts.append(v))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.config = {"update_manifest_url": "https://example.invalid/m.json", "auto_install_updates": True,
                       "mobile_server_port": 8765}
        patcher = patch.object(worker_server, "load_config", side_effect=lambda: dict(self.config))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_newer_files_on_disk_restart_when_idle_and_keep_lock(self):
        server = fake_server()
        with patch.object(worker_server, "_installed_version", return_value=bump(VERSION)):
            server.generation_lock.acquire()
            self.assertEqual(worker_server._worker_update_step(server, {}), "busy")  # mid-reply: wait
            self.assertEqual(self.restarts, [])
            server.generation_lock.release()
            self.assertEqual(worker_server._worker_update_step(server, {}), "restarting")
        self.assertEqual(self.restarts, [bump(VERSION)])
        self.assertTrue(server.generation_lock.locked())  # no new reply starts before exit

    def test_leaves_installing_to_xemai_server_on_same_pc(self):
        with patch.object(worker_server, "_installed_version", return_value=VERSION), \
             patch.object(worker_server, "_port_listening", return_value=True), \
             patch("app.updater.check_for_update", side_effect=AssertionError("no network")):
            self.assertEqual(worker_server._worker_update_step(fake_server(), {}), "idle")
        self.config["auto_install_updates"] = False
        with patch.object(worker_server, "_installed_version", return_value=VERSION), \
             patch.object(worker_server, "_port_listening", return_value=False), \
             patch("app.updater.check_for_update", side_effect=AssertionError("disabled")):
            self.assertEqual(worker_server._worker_update_step(fake_server(), {}), "idle")

    def test_worker_alone_downloads_verifies_installs_when_idle_then_restarts(self):
        server, state, calls = fake_server(), {}, []
        manifest = {"version": bump(VERSION), "files": [{"path": "x"}]}
        with patch.object(worker_server, "_installed_version", return_value=VERSION), \
             patch.object(worker_server, "_port_listening", return_value=False), \
             patch("app.updater.check_for_update", return_value=manifest), \
             patch("app.updater.prepare_file_update", side_effect=lambda **k: calls.append("prepare") or "P"), \
             patch("app.updater.install_prepared_update",
                   side_effect=lambda **k: calls.append(("install", k["prepared"])) or manifest["version"]):
            server.generation_lock.acquire()
            self.assertEqual(worker_server._worker_update_step(server, state), "busy")
            self.assertEqual(state["prepared"], "P")  # downloaded once, kept for later
            server.generation_lock.release()
            self.assertEqual(worker_server._worker_update_step(server, state), "restarting")
        self.assertEqual(calls, ["prepare", ("install", "P")])
        self.assertEqual(self.restarts, [bump(VERSION)])

    def test_failed_install_releases_lock_and_retries_later(self):
        server = fake_server()
        with patch.object(worker_server, "_installed_version", return_value=VERSION), \
             patch.object(worker_server, "_port_listening", return_value=False), \
             patch("app.updater.check_for_update", return_value={"version": bump(VERSION), "files": [1]}), \
             patch("app.updater.prepare_file_update", return_value="P"), \
             patch("app.updater.install_prepared_update", side_effect=RuntimeError("hash mismatch")):
            state = {}
            with self.assertRaises(RuntimeError):
                worker_server._worker_update_step(server, state)
        self.assertFalse(server.generation_lock.locked())
        self.assertNotIn("prepared", state)
        self.assertEqual(self.restarts, [])

    def test_current_version_does_nothing(self):
        with patch.object(worker_server, "_installed_version", return_value=VERSION), \
             patch.object(worker_server, "_port_listening", return_value=False), \
             patch("app.updater.check_for_update", return_value=None):
            self.assertEqual(worker_server._worker_update_step(fake_server(), {}), "current")

    def test_installed_version_reads_disk(self):
        self.assertEqual(worker_server._installed_version(), VERSION)


class VersionEndpointTests(unittest.TestCase):
    def test_version_is_public_and_minimal(self):
        server = worker_server.XemAiWorkerServer(("127.0.0.1", 0), worker_server.XemAiWorkerHandler)
        server.worker_token = "secret"
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (server.shutdown(), server.server_close()))
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{server.server_port}/api/version", timeout=5) as response:
            body = json.load(response)
        self.assertEqual(body, {"ok": True, "role": "xemai_hybrid_worker", "version": VERSION})


class SupervisorWorkerTests(unittest.TestCase):
    def test_relaunches_worker_and_verifies_reported_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "XemAiWorker.pyw").write_text("")
            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            servers = []

            class Version(BaseHTTPRequestHandler):
                def do_GET(self):
                    raw = json.dumps({"ok": True, "role": "xemai_hybrid_worker", "version": "9.9.9"}).encode()
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)

                def log_message(self, *a):
                    pass

            def spawn(args, **kwargs):
                self.assertTrue(args[1].endswith("XemAiWorker.pyw"))
                httpd = ThreadingHTTPServer(("127.0.0.1", port), Version)
                threading.Thread(target=httpd.serve_forever, daemon=True).start()
                servers.append(httpd)
                return SimpleNamespace(poll=lambda: None)

            try:
                ok = restart_supervisor.relaunch("python", str(base / "XemAiWorker.pyw"), str(base), str(base),
                                                 "9.9.9", port, wait=lambda n: None, spawn=spawn)
            finally:
                for httpd in servers:
                    httpd.shutdown()
                    httpd.server_close()
            self.assertTrue(ok)
            self.assertEqual(json.loads((base / "worker_restart_status.json").read_text())["state"], "healthy")

    def test_rejects_other_scripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "evil.pyw").write_text("")
            self.assertFalse(restart_supervisor.relaunch("python", str(Path(tmp) / "evil.pyw"), tmp, tmp, "1", 8766,
                                                         wait=lambda n: None, spawn=None))


class OutdatedWorkerMessageTests(unittest.TestCase):
    def test_old_worker_404_becomes_clear_instructions(self):
        class OldWorker:
            def _request(self, path, payload=None, timeout=0):
                raise RuntimeError('Ollama returned HTTP 404: {"ok": false, "error": "Unknown worker endpoint."}')

            def worker_health(self):
                return {"ok": True, "version": "0.9.58"}

        reply = wt.command(Path(tempfile.gettempdir()), None, 1, "weights setup",
                           executor=wt.WorkerExecutor(OldWorker()), ollama_base="qwen3:8b")
        self.assertIn("still running v0.9.58", reply)
        self.assertIn("restart the PC", reply)
        self.assertNotIn("HTTP 404", reply)


if __name__ == "__main__":
    unittest.main()
