"""Regression tests for background-staged, parallel incremental XemAi updates."""
from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import mobile_server, updater


def entry(path: str, data: bytes) -> dict:
    return {
        "path": path,
        "sha256": hashlib.sha256(data).hexdigest(),
        "url": "https://raw.githubusercontent.com/example/pinned-release/" + path,
    }


class DeltaUpdateTests(unittest.TestCase):
    def test_prepare_changes_only_and_chat_can_use_existing_program(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data/personal_ai.db").write_bytes(b"real user data")
            (root / "logs").mkdir()
            (root / "logs/server.log").write_bytes(b"persistent log")
            (root / "config.json").write_bytes(b'{"watch_enabled": true}')
            (root / "app").mkdir()
            unchanged = b"print('no change')\n"
            old = b"print('old function')\n"
            new = b"print('new function')\n"
            (root / "app/already.py").write_bytes(unchanged)
            (root / "app/changed.py").write_bytes(old)
            manifest = {
                "version": "999.0.0",
                "files": [entry("app/already.py", unchanged),
                          entry("app/changed.py", new)]
            }
            requests = []
            def fetch(url):
                requests.append(url)
                return new
            with patch.object(updater, "_https_bytes", side_effect=fetch):
                staged = updater.prepare_file_update(
                    base_dir=root, manifest=manifest,
                )
            try:
                self.assertEqual(len(requests), 1)
                self.assertIn("changed.py", requests[0])
                self.assertEqual(staged.skipped, 1)
                self.assertEqual(staged.download_count, 1)
                self.assertEqual((root / "app/changed.py").read_bytes(), old)
                self.assertFalse((root / ".update_backups").exists())
                self.assertEqual(updater.install_prepared_update(
                    base_dir=root, prepared=staged,
                ), "999.0.0")
                self.assertEqual((root / "app/changed.py").read_bytes(), new)
                self.assertEqual((root / "app/already.py").read_bytes(), unchanged)
                backup = root / ".update_backups/before_999_0_0"
                self.assertEqual((backup / "app/changed.py").read_bytes(), old)
                self.assertFalse((backup / "app/already.py").exists())
                metadata = json.loads((backup / "rollback_manifest.json").read_text())
                self.assertEqual(metadata["restorable_files"], ["app/changed.py"])
                self.assertEqual((root / "data/personal_ai.db").read_bytes(), b"real user data")
                self.assertEqual((root / "config.json").read_bytes(), b'{"watch_enabled": true}')
                self.assertEqual((root / "logs/server.log").read_bytes(), b"persistent log")
            finally:
                staged.close()

    def test_parallel_changed_asset_downloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = b"print('first')\n"
            second = b"print('second')\n"
            barrier = threading.Barrier(2, timeout=6)
            manifest = {"version": "999.0.0", "files": [
                entry("app/first.py", first), entry("app/second.py", second)
            ]}
            def download(url):
                barrier.wait()  # Sequential download deadlocks and fails.
                return first if "first.py" in url else second
            with patch.object(updater, "_https_bytes", side_effect=download):
                prepared = updater.prepare_file_update(base_dir=root, manifest=manifest)
            try:
                self.assertEqual(prepared.download_count, 2)
                self.assertEqual(len(prepared.changed), 2)
            finally:
                prepared.close()

    def test_bad_asset_does_not_touch_program_or_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "main.py").write_bytes(b"old\n")
            manifest = {"version": "999.0.0", "files": [
                entry("main.py", b"new\n")
            ]}
            with patch.object(updater, "_https_bytes", return_value=b"corrupt"):
                with self.assertRaisesRegex(updater.UpdateError, "SHA-256 mismatch"):
                    updater.prepare_file_update(base_dir=root, manifest=manifest)
            self.assertEqual((root / "main.py").read_bytes(), b"old\n")
            self.assertFalse((root / ".update_backups").exists())

    def test_preparation_does_not_hold_server_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            script = b"print('updated')\n"
            manifest = {"version": "999.0.0", "files": [entry("app/file.py", script)]}
            update_lock = threading.Lock()
            chat_lock = threading.Lock()
            ready = threading.Event()
            allow_finish = threading.Event()
            stop = threading.Event()
            server = SimpleNamespace(
                chat_operation_lock=chat_lock,
                update_lock=update_lock,
                active_chat_requests=0,
                update_restarting=False,
                stop_event=stop,
                xemai_logger=None,
            )
            def slow_download(url):
                ready.set()
                if not allow_finish.wait(8):
                    raise RuntimeError("staging blocked")
                return script
            thread = threading.Thread(target=mobile_server._auto_update_loop, args=(server,), daemon=True)
            config = {
                "mobile_updates_enabled": True,
                "auto_install_updates": True,
                "update_manifest_url": "https://example.invalid/manifest",
                "auto_update_interval_seconds": 15,
            }
            def schedule(inst_server, version):
                self.assertFalse(update_lock.locked() is False)
                stop.set()
            with patch.object(mobile_server, "BASE_DIR", root), \
                 patch.object(mobile_server, "load_config", return_value=config), \
                 patch.object(mobile_server.updater, "check_for_update", return_value=manifest), \
                 patch.object(mobile_server.updater, "_https_bytes", side_effect=slow_download), \
                 patch.object(mobile_server, "_schedule_mobile_server_restart", side_effect=schedule):
                thread.start()
                try:
                    self.assertTrue(ready.wait(6), "preflight never started")
                    self.assertFalse(update_lock.locked(),
                                     "download must not hold update lock")
                    self.assertIsNone(mobile_server._reserve_update(server),
                                      "chat should be accepted while downloading")
                    update_lock.release()
                    allow_finish.set()
                    thread.join(8)
                    self.assertFalse(thread.is_alive())
                    self.assertTrue(stop.is_set())
                    self.assertEqual((root / "app/file.py").read_bytes(), script)
                finally:
                    allow_finish.set()
                    stop.set()
                    thread.join(8)

    def test_unsafe_and_duplicate_paths_never_modify_program(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = b"print(3)\n"
            variants = [
                [entry("../escape.py", fixture)],
                [entry("data/my_memory.db", fixture)],
                [entry("app/A.py", fixture), entry("app/a.py", fixture)],
            ]
            for files in variants:
                with self.subTest(files=files):
                    with self.assertRaises(updater.UpdateError):
                        updater.prepare_file_update(
                            base_dir=root,
                            manifest={"version": "999.0.0", "files": files},
                        )
            self.assertFalse((root / ".update_backups").exists())

    def test_app_only_accepts_actual_sha256_verified_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = {"version": "999.0.0", "files": [
                entry("main.py", b"print('safe')\n")
            ]}
            with patch.object(updater, "_https_bytes", return_value=b"print('safe')\n"):
                prepared = updater.prepare_file_update(base_dir=root, manifest=manifest)
            try:
                (prepared.stage / "main.py").unlink()
                with self.assertRaisesRegex(updater.UpdateError, "missing"):
                    updater.install_prepared_update(base_dir=root, prepared=prepared)
                self.assertFalse((root / ".update_backups").exists())
            finally:
                prepared.close()


if __name__ == "__main__":
    unittest.main()
