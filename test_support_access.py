from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import support_access as support


class SupportAccessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "app").mkdir()
        (self.root / "data").mkdir()
        (self.root / "logs").mkdir()
        (self.root / "app/version.py").write_text('VERSION = "0.9.5"\n', encoding="utf-8")
        (self.root / "main.py").write_text("# source\n", encoding="utf-8")

    def test_default_expiry_rotation_and_revoke(self):
        self.assertFalse(support.status(self.root)["enabled"])
        self.assertFalse(support.authorized(self.root, "x" * 43))
        with patch.object(support.time, "time", return_value=1000):
            first = support.enable(self.root)
            self.assertTrue(support.authorized(self.root, first["token"]))
            self.assertNotIn(first["token"], (self.root / "data/support_access.json").read_text())
            self.assertNotIn("token", support.status(self.root))
            second = support.enable(self.root)
            self.assertFalse(support.authorized(self.root, first["token"]))
            self.assertTrue(support.authorized(self.root, second["token"]))
        with patch.object(support.time, "time", return_value=1000 + support.ACCESS_SECONDS):
            self.assertFalse(support.status(self.root)["enabled"])
            self.assertFalse(support.authorized(self.root, second["token"]))
        support.disable(self.root)
        self.assertFalse((self.root / "data/support_access.json").exists())
        self.assertFalse(support.authorized(self.root, "é" * 43))

    def test_privacy_boundary_and_safe_urls(self):
        sentinel = "private-secret-chat-sentinel"
        (self.root / "config.json").write_text(json.dumps({
            "hybrid_enabled": True, "model": "qwen3:1.7b", "password": sentinel,
            "assistant_name": sentinel, "ollama_api_key": sentinel,
            "hybrid_worker_url": f"https://user:{sentinel}@worker.tailnet.ts.net:8766/{sentinel}?token={sentinel}#key",
        }), encoding="utf-8")
        (self.root / "data/secrets.json").write_text(json.dumps({
            "hybrid_worker_client_token": sentinel, "ollama_api_key": sentinel,
        }), encoding="utf-8")
        (self.root / "data/personal_ai.db").write_bytes(sentinel.encode())
        (self.root / "logs/personal_ai.log").write_text(
            f"2026-10-09 10:30:01,123 | DEBUG | personal_ai | User content | chat_id=1 | {sentinel}\n"
            f"{sentinel}\n"
            "2026-10-09 10:30:02,123 | INFO | personal_ai | Application start | version=0.9.5\n"
            f"2026-10-09 10:30:03,123 | INFO | personal_ai | Hybrid auto-pair candidate failed | url=https://worker/?token={sentinel} error=OllamaError('Ollama returned HTTP 400: model={sentinel} | model={sentinel}')\n",
            encoding="utf-8",
        )
        report = support.get_report(self.root)
        encoded = json.dumps(report)
        self.assertNotIn(sentinel, encoded)
        self.assertEqual(report["config"]["hybrid_worker_url"], "https://worker.tailnet.ts.net:8766")
        self.assertTrue(report["hybrid_bindings"]["worker_client_token_present"])
        event = report["logs"][0]["entries"][-1]
        self.assertEqual(event["http_status"], 400)
        self.assertEqual(event["error_type"], "OllamaError")
        for path in ["data/secrets.json", "data/support_access.json", "data/personal_ai.db", "hybrid_pairing.txt", "workspace/chat.txt", "logs/other.log", "../main.py", "/main.py", "app/../main.py", "app\\version.py"]:
            with self.subTest(path=path), self.assertRaises(ValueError):
                support.read_file(self.root, path)

    def test_symlinks_size_and_malformed_files(self):
        outside = self.root / "private.py"
        outside.write_text("private", encoding="utf-8")
        try:
            (self.root / "app/linked.py").symlink_to(outside)
        except OSError:
            self.skipTest("Symlink creation unavailable")
        with self.assertRaises(ValueError):
            support.read_file(self.root, "app/linked.py")
        (self.root / "main.py").write_bytes(b"x" * (support.MAX_FILE_BYTES + 1))
        with self.assertRaises(ValueError):
            support.read_file(self.root, "main.py")
        (self.root / "config.json").write_text(json.dumps({"hybrid_routing_mode": ["unexpected"]}), encoding="utf-8")
        (self.root / "app/version.py").write_text('VERSION = str(__import__("os").getcwd())', encoding="utf-8")
        report = support.get_report(self.root)
        self.assertEqual(report["config"], {})
        self.assertIsNone(report["disk_version"])
        self.assertFalse(any(item["path"] == "main.py" for item in report["files"]))
        self.assertFalse(any(item["path"] == "app/linked.py" for item in report["files"]))
        (self.root / "config.json").write_text("invalid json", encoding="utf-8")
        self.assertEqual(support.safe_config(self.root), {})

    def test_safe_state_refuses_symlink_directory(self):
        (self.root / "data").rmdir()
        try:
            (self.root / "data").symlink_to(self.root / "app", target_is_directory=True)
        except OSError:
            self.skipTest("Symlink creation unavailable")
        with self.assertRaises(ValueError):
            support.enable(self.root)
        self.assertFalse((self.root / "app/support_access.json").exists())

    def test_large_logs_export_only_bounded_safe_tail(self):
        sentinel = "private-chat-secret-sentinel"
        prefix = (sentinel + "\n").encode() * 80000
        event = b"2026-10-09 10:30:02,123 | INFO | personal_ai | Hybrid auto-pair waiting | reason=No reachable Qwen workers | peers=3\n"
        path = self.root / "logs/personal_ai.log"
        path.write_bytes(prefix + event)
        item = support.read_file(self.root, "logs/personal_ai.log")
        self.assertGreater(item["file_size_bytes"], support.MAX_FILE_BYTES)
        self.assertLessEqual(item["size_bytes"], support.MAX_FILE_BYTES)
        self.assertNotIn(sentinel, item["content"])
        events = json.loads(item["content"])["entries"]
        self.assertEqual(events[-1]["reason"], "No reachable Qwen workers")
        self.assertEqual(events[-1]["peers"], 3)
        self.assertLessEqual(len(support._log_tail(path)), support.MAX_FILE_BYTES)
        report = support.get_report(self.root)
        self.assertEqual(report["logs"][0]["entries"][-1]["peers"], 3)
        self.assertNotIn(sentinel, json.dumps(report))


if __name__ == "__main__":
    unittest.main()
