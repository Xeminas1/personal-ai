"""Fast update discovery stays separate from atomic install ownership."""
from __future__ import annotations

import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import mobile_server
import test_chat_delete as chat_fixture


CHANNEL = "https://example.test/updates.json"
MANIFEST = {"version": "9.9.9", "files": []}


class ScriptedStop:
    """Advance scheduling deterministically through event-wait boundaries."""
    def __init__(self, limit=3, actions=None):
        self.waits = []
        self.stopped = False
        self.limit = limit
        self.actions = actions or {}

    def is_set(self):
        return self.stopped

    def set(self):
        self.stopped = True

    def wait(self, seconds):
        self.waits.append(seconds)
        action = self.actions.get(len(self.waits))
        if action:
            action()
        if len(self.waits) >= self.limit:
            self.stopped = True
        return self.stopped


class FastStartupStop(threading.Event):
    def __init__(self):
        super().__init__()
        self.startup = True

    def wait(self, timeout=None):
        if self.startup:
            self.startup = False
            return self.is_set()
        return super().wait(timeout)


def scheduler_server(stop):
    return SimpleNamespace(stop_event=stop, update_lock=threading.Lock(),
        chat_operation_lock=threading.RLock(), activity_lock=threading.Lock(),
        active_chat_requests=0, chat_activity={}, update_restarting=False,
        xemai_logger=None)


class AutoUpdateTests(unittest.TestCase):
    def setUp(self):
        self.config = {"update_manifest_url": CHANNEL, "auto_update_interval_seconds": 15,
                       "mobile_updates_enabled": True, "auto_install_updates": True}
        self.stop = ScriptedStop()
        self.server = scheduler_server(self.stop)

    def run_loop(self, *, check=None, install=None, restart=None):
        check = check or Mock(return_value=None)
        install = install or Mock(return_value="9.9.9")
        restart = restart or Mock()
        with patch.object(mobile_server, "load_config", side_effect=lambda: dict(self.config)), \
             patch.object(mobile_server.updater, "check_for_update", check), \
             patch.object(mobile_server.updater, "install_update", install), \
             patch.object(mobile_server, "ChatBackend", side_effect=AssertionError("Scheduler created backend")), \
             patch.object(mobile_server, "_schedule_mobile_server_restart", restart):
            mobile_server._auto_update_loop(self.server)
        return check, install, restart

    def test_startup_normal_cadence_and_custom_interval(self):
        for interval, expected in ((15, 15), (60, 15), (45, 45)):
            with self.subTest(interval=interval):
                self.config["auto_update_interval_seconds"] = interval
                self.stop = ScriptedStop()
                self.server = scheduler_server(self.stop)
                check, install, _ = self.run_loop()
                self.assertEqual(self.stop.waits, [2, expected, expected])
                self.assertEqual(check.call_count, 2)
                install.assert_not_called()
                self.assertEqual(self.config["auto_update_interval_seconds"], interval)

    def test_interval_default_legacy_floor_custom_and_invalid(self):
        self.assertEqual(mobile_server._auto_update_interval({}), 15)
        for value, expected in ((60, 15), ("60", 15), (5, 10), (10, 10), (27, 27),
                                (120, 120), (None, 15), (0, 15), (-1, 15),
                                (True, 15), ("bad", 15), (float("inf"), 15),
                                (int(threading.TIMEOUT_MAX) + 1, 15), (10 ** 100, 15)):
            with self.subTest(value=value):
                self.assertEqual(mobile_server._auto_update_interval(
                    {"auto_update_interval_seconds": value}), expected)

    def test_found_manifest_waits_for_reply_and_memory_tail_without_refetch(self):
        self.server.active_chat_requests = 1
        self.server.chat_activity = {10: {"status": "Replying"}}
        self.stop.limit = 5
        # The answer becomes visible, but the reply counter still covers memory.
        self.stop.actions = {2: lambda: self.server.chat_activity.clear(),
                             3: lambda: setattr(self.server, "active_chat_requests", 0)}
        def install(**kwargs):
            self.assertTrue(self.server.update_lock.locked())
            self.assertEqual(kwargs["manifest"], MANIFEST)
            self.assertEqual(self.server.active_chat_requests, 0)
            return "9.9.9"
        check, _, restart = self.run_loop(check=Mock(return_value=MANIFEST), install=Mock(side_effect=install))
        self.assertEqual(self.stop.waits, [2, 2, 2])
        check.assert_called_once_with(CHANNEL)
        restart.assert_called_once_with()
        self.assertTrue(self.server.update_restarting)
        self.assertFalse(self.server.update_lock.locked())

    def test_found_manifest_waits_for_existing_manual_owner(self):
        self.assertIsNone(mobile_server._reserve_update(self.server))
        self.stop.actions = {2: self.server.update_lock.release}
        check, install, _ = self.run_loop(check=Mock(return_value=MANIFEST))
        check.assert_called_once_with(CHANNEL)
        install.assert_called_once()
        self.assertEqual(self.stop.waits, [2, 2])

    def test_pending_manifest_discarded_on_disable_or_channel_change(self):
        for changed in ({"mobile_updates_enabled": False}, {"auto_install_updates": False},
                        {"update_manifest_url": "https://example.test/other.json"}):
            with self.subTest(changed=changed):
                self.setUp()
                self.server.active_chat_requests = 1
                self.stop.actions = {2: lambda: self.config.update(changed)}
                check, install, _ = self.run_loop(check=Mock(side_effect=[MANIFEST, None]))
                install.assert_not_called()
                self.assertEqual(self.stop.waits, [2, 2, 15])
                expected = 2 if "update_manifest_url" in changed else 1
                self.assertEqual(check.call_count, expected)
                if expected == 2:
                    self.assertEqual(check.call_args.args[0], changed["update_manifest_url"])

    def test_config_changed_during_fetch_cannot_install_stale_manifest(self):
        for changed in ({"mobile_updates_enabled": False}, {"auto_install_updates": False},
                        {"update_manifest_url": "https://example.test/other.json"}):
            with self.subTest(changed=changed):
                self.setUp()
                self.stop.limit = 2
                def check(_channel):
                    self.config.update(changed)
                    return MANIFEST
                _, install, _ = self.run_loop(check=Mock(side_effect=check))
                install.assert_not_called()
                self.assertFalse(self.server.update_lock.locked())

    def test_check_install_and_restart_failures_release_ownership_and_retry_normally(self):
        for failure in ("check", "install", "restart"):
            with self.subTest(failure=failure):
                self.setUp()
                check = Mock(side_effect=[RuntimeError("Check failed"), None]) if failure == "check" else Mock(side_effect=[MANIFEST, None])
                install = Mock(side_effect=RuntimeError("Install failed")) if failure == "install" else Mock(return_value="9.9.9")
                restart = Mock(side_effect=RuntimeError("Restart failed")) if failure == "restart" else Mock()
                self.run_loop(check=check, install=install, restart=restart)
                self.assertEqual(self.stop.waits, [2, 15, 15])
                self.assertEqual(check.call_count, 2)
                self.assertFalse(self.server.update_lock.locked())
                self.assertFalse(self.server.update_restarting)

    def test_shutdown_during_startup_fetch_or_pending_wait_prevents_install(self):
        for phase in ("startup", "fetch", "pending"):
            with self.subTest(phase=phase):
                self.setUp()
                if phase == "startup":
                    self.stop.limit = 1
                elif phase == "pending":
                    self.server.active_chat_requests = 1
                    self.stop.limit = 2
                def check(_channel):
                    if phase == "fetch":
                        self.stop.set()
                    return MANIFEST
                check, install, _ = self.run_loop(check=Mock(side_effect=check))
                install.assert_not_called()
                self.assertEqual(check.call_count, 0 if phase == "startup" else 1)
                self.assertFalse(self.server.update_lock.locked())


class AutoUpdateHTTPTests(unittest.TestCase):
    # Reuse the temporary database/real HTTP server fixture, without collecting
    # its unrelated deletion tests a second time.
    setUp = chat_fixture.ChatDeleteTests.setUp
    close_server = chat_fixture.ChatDeleteTests.close_server
    request = chat_fixture.ChatDeleteTests.request

    def backend(self):
        backend = chat_fixture.ChatDeleteTests.backend(self)
        backend.config = {"mobile_updates_enabled": True, "update_manifest_url": CHANNEL}
        backend.check_update = lambda: MANIFEST
        backend.install_update = lambda _manifest: "9.9.9"
        if getattr(self, "hold_validation", False):
            get_chat = backend.get_chat
            def validate(chat_id):
                self.validation_entered.set()
                if not self.allow_validation.wait(3):
                    raise RuntimeError("Validation gate timed out")
                return get_chat(chat_id)
            backend.get_chat = validate
        return backend

    def test_manifest_network_read_does_not_block_actual_message_submission(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        self.server.stop_event = FastStartupStop()
        self.addCleanup(self.server.stop_event.set)
        config = {"update_manifest_url": CHANNEL}
        def check(_channel):
            self.assertFalse(self.server.update_lock.locked())
            entered.set()
            if not release.wait(3):
                raise RuntimeError("Manifest gate timed out")
            return None
        with patch.object(mobile_server, "load_config", return_value=config), \
             patch.object(mobile_server.updater, "check_for_update", side_effect=check), \
             patch.object(mobile_server.updater, "install_update") as install:
            worker = threading.Thread(target=mobile_server._auto_update_loop, args=(self.server,))
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                status, _ = self.request(f"/api/chats/{self.chat_id}/messages",
                                        method="POST", body={"text": "Chat while checking"})
                self.assertEqual(status, 202)
                self.assertTrue(self.generation_started.wait(3))
                self.assertFalse(self.server.update_lock.locked())
                install.assert_not_called()
            finally:
                self.allow_generation.set()
                release.set()
                self.server.stop_event.set()
                worker.join(3)
            self.assertFalse(worker.is_alive())

    def test_generation_reservation_and_update_reservation_are_serialized(self):
        self.hold_validation = True
        self.validation_entered = threading.Event()
        self.allow_validation = threading.Event()
        self.addCleanup(self.allow_validation.set)
        reserve_entered = threading.Event()
        def reserve():
            reserve_entered.set()
            return mobile_server._reserve_update(self.server)
        with ThreadPoolExecutor(max_workers=2) as pool:
            message = pool.submit(self.request, f"/api/chats/{self.chat_id}/messages",
                                  method="POST", body={"text": "Reserved reply"})
            self.assertTrue(self.validation_entered.wait(3))
            update = pool.submit(reserve)
            self.assertTrue(reserve_entered.wait(3))
            self.assertFalse(update.done())
            self.allow_validation.set()
            self.assertEqual(message.result(3)[0], 202)
            self.assertEqual(update.result(3), "busy")
            self.assertFalse(self.server.update_lock.locked())
            self.allow_generation.set()

    def test_manual_install_owns_lock_once_and_rejects_concurrent_generation(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        installs = []
        original_backend = self.backend
        def backend():
            instance = original_backend()
            def install(manifest):
                self.assertTrue(self.server.update_lock.locked())
                installs.append(manifest)
                entered.set()
                if not release.wait(3):
                    raise RuntimeError("Install gate timed out")
                return "9.9.9"
            instance.install_update = install
            return instance
        with patch.object(mobile_server, "ChatBackend", side_effect=backend), \
             patch.object(mobile_server, "load_config", return_value={"mobile_updates_enabled": True, "update_manifest_url": CHANNEL}), \
             patch.object(mobile_server, "_schedule_mobile_server_restart") as restart, \
             ThreadPoolExecutor(max_workers=2) as pool:
            installing = pool.submit(self.request, "/api/update/install", method="POST")
            self.assertTrue(entered.wait(3))
            status, _ = self.request(f"/api/chats/{self.chat_id}/messages",
                                    method="POST", body={"text": "Too late"})
            self.assertEqual(status, 503)
            status, _ = self.request("/api/update/install", method="POST")
            self.assertEqual(status, 409)
            self.assertEqual(len(installs), 1)
            release.set()
            self.assertEqual(installing.result(3)[0], 200)
            # Returning the HTTP response can precede restart scheduling.
            self.assertTrue(self.server.update_lock.acquire(timeout=3))
            try:
                self.assertTrue(self.server.update_restarting)
            finally:
                self.server.update_lock.release()
            restart.assert_called_once()

    def test_manual_fetch_respects_settings_changed_during_lookup(self):
        for changed, status in (({"mobile_updates_enabled": False}, 403),
                                ({"update_manifest_url": "https://example.test/other.json"}, 409)):
            with self.subTest(changed=changed):
                config = {"mobile_updates_enabled": True, "update_manifest_url": CHANNEL}
                install = Mock()
                original_backend = self.backend
                def backend():
                    instance = original_backend()
                    def check():
                        config.update(changed)
                        return MANIFEST
                    instance.check_update = check
                    instance.install_update = install
                    return instance
                with patch.object(mobile_server, "ChatBackend", side_effect=backend), \
                     patch.object(mobile_server, "load_config", side_effect=lambda: dict(config)), \
                     patch.object(mobile_server, "_schedule_mobile_server_restart") as restart:
                    self.assertEqual(self.request("/api/update/install", method="POST")[0], status)
                install.assert_not_called()
                restart.assert_not_called()
                self.assertFalse(self.server.update_lock.locked())

    def test_manual_restart_failure_returns_error_and_leaves_chat_usable(self):
        with patch.object(mobile_server, "load_config", return_value={"mobile_updates_enabled": True, "update_manifest_url": CHANNEL}), \
             patch.object(mobile_server, "_schedule_mobile_server_restart", side_effect=OSError("Restart unavailable")):
            status, response = self.request("/api/update/install", method="POST")
        self.assertEqual(status, 500)
        self.assertFalse(response["ok"])
        with self.server.update_lock:
            self.assertFalse(self.server.update_restarting)
        status, _ = self.request(f"/api/chats/{self.chat_id}/messages", method="POST", body={"text": "Chat after failed restart"})
        self.assertEqual(status, 202)
        self.assertTrue(self.generation_started.wait(3))
        self.allow_generation.set()


if __name__ == "__main__":
    unittest.main()
