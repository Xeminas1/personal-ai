"""Exercise the actual phone/desktop chat menu in a real browser."""
from __future__ import annotations

import copy
import importlib.util
import json
import re
import shutil
import tempfile
import threading
import time
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


HAS_PLAYWRIGHT = importlib.util.find_spec("playwright") is not None
ROOT = Path(__file__).resolve().parent


class ChatAPIFixture:
    def __init__(self, version):
        self.version = version
        self.chats = [self.chat(10, "Pirates"), self.chat(20, "Notes")]
        self.chats[0]["updated_at"] = "2026-01-01T12:00:01+00:00"
        self.messages = {
            10: [self.message(101, "Pirates reply")],
            20: [self.message(201, "Notes reply")],
        }
        self.delete_requests = []
        self.created_count = 0
        self.capability_reads = 0
        self.reject_deletion = False
        self.delay_messages_for = None
        self.pending_messages = []

    @staticmethod
    def chat(identifier, title):
        return {"id": identifier, "user_id": 1, "title": title,
                "created_at": "2026-01-01T12:00:00+00:00",
                "updated_at": "2026-01-01T12:00:00+00:00"}

    @staticmethod
    def message(identifier, content):
        return {"id": identifier, "role": "assistant", "content": content,
                "created_at": "2026-01-01T12:00:00+00:00",
                "inference_model": None, "inference_compute": None}

    @staticmethod
    def respond(route, data, status=200):
        route.fulfill(status=status, content_type="application/json", body=json.dumps(data))

    def delete(self, identifier):
        self.chats = [chat for chat in self.chats if chat["id"] != identifier]
        self.messages.pop(identifier, None)

    def handle(self, route):
        request = route.request
        path, method = urlparse(request.url).path, request.method
        if path == "/api/bootstrap":
            return self.respond(route, {"ok": True, "version": self.version,
                "assistant_name": "XemAi", "user": {"id": 1, "name": "Test"},
                "runtime_model": "qwen3:8b", "compute_source": "remote_worker",
                "capabilities": []})
        if path == "/api/chats" and method == "GET":
            return self.respond(route, {"ok": True, "chats": self.chats})
        if path == "/api/chats" and method == "POST":
            self.created_count += 1
            chat = self.chat(20 + self.created_count * 10, "New chat")
            self.chats.insert(0, chat)
            self.messages[chat["id"]] = []
            return self.respond(route, {"ok": True, "chat": chat})
        match = re.fullmatch(r"/api/chats/(\d+)(?:/(messages|activity|feedback))?", path)
        if match:
            identifier, operation = int(match[1]), match[2]
            chat = next((chat for chat in self.chats if chat["id"] == identifier), None)
            if method == "DELETE" and operation is None:
                self.delete_requests.append(identifier)
                if self.reject_deletion:
                    return self.respond(route, {"ok": False, "error": "XemAi is finishing a reply. Try again shortly."}, 409)
                if chat is None:
                    return self.respond(route, {"ok": False, "error": "Chat not found."}, 404)
                self.delete(identifier)
                return self.respond(route, {"ok": True, "deleted_chat_id": identifier,
                    "attachment_cleanup_complete": True})
            if chat is None:
                return self.respond(route, {"ok": False, "error": "Chat not found."}, 404)
            if operation == "messages":
                response = copy.deepcopy({"ok": True, "chat": chat, "messages": self.messages[identifier]})
                if self.delay_messages_for == identifier:
                    self.delay_messages_for = None
                    self.pending_messages.append((route, response))
                    return
                return self.respond(route, response)
            if operation == "activity":
                return self.respond(route, {"ok": True, "active": False, "status": None})
            if operation == "feedback":
                return self.respond(route, {"ok": True})
        if path == "/api/capabilities":
            self.capability_reads += 1
            return self.respond(route, {"ok": True, "capabilities": ["Fixture capabilities"]})
        if path == "/api/compute":
            return self.respond(route, {"ok": True, "model": "qwen3:8b", "compute_source": "remote_worker"})
        if path == "/api/health":
            return self.respond(route, {"ok": True, "version": self.version})
        if path == "/api/update":
            return self.respond(route, {"ok": True, "enabled": True, "update": None, "current_version": self.version})
        return self.respond(route, {"ok": False, "error": "Unexpected fixture API request."}, 404)

    def release_messages(self):
        pending, self.pending_messages = self.pending_messages, []
        for route, response in pending:
            self.respond(route, response)


@unittest.skipUnless(HAS_PLAYWRIGHT, "Playwright is not installed")
class ChatMenuBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.playwright = sync_playwright().start()
        executable = shutil.which("chromium") or shutil.which("google-chrome")
        if not executable and Path(cls.playwright.chromium.executable_path).is_file():
            executable = cls.playwright.chromium.executable_path
        if not executable:
            cls.playwright.stop()
            raise unittest.SkipTest("Chromium is not installed")
        cls.browser = cls.playwright.chromium.launch(
            executable_path=executable, headless=True, args=["--no-sandbox"],
            ignore_default_args=["--hide-scrollbars"],
        )
        cls.static_files = tempfile.TemporaryDirectory()
        directory = Path(cls.static_files.name)
        shutil.copytree(ROOT / "mobile", directory, dirs_exist_ok=True)
        source = (directory / "app.js").read_text(encoding="utf-8")
        cls.frontend_version = re.search(r'FRONTEND_VERSION\s*=\s*"([^"]+)"', source)[1]

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(directory), **kwargs)

            def log_message(self, *_args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.static_files.cleanup()
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.contexts = []
        self.addCleanup(self.close_contexts)

    def close_contexts(self):
        for context in self.contexts:
            context.close()

    def open_app(self, *, desktop=False, fixture=None):
        fixture = fixture or ChatAPIFixture(self.frontend_version)
        context = self.browser.new_context(
            viewport={"width": 1440 if desktop else 390, "height": 900 if desktop else 844},
            is_mobile=not desktop, has_touch=not desktop, service_workers="block",
        )
        self.contexts.append(context)
        page = context.new_page()
        page.set_default_timeout(5000)
        page.route("**/api/**", fixture.handle)
        page.goto(self.base)
        page.wait_for_function("state.bootstrap && state.chatId === 10")
        return page, fixture

    def open_menu(self, page):
        page.locator("#moreBtn").click()
        page.wait_for_function("document.querySelector('#modal').open")
        self.assertEqual(page.locator("#modalTitle").inner_text(), "Chat options")

    def open_delete(self, page):
        self.open_menu(page)
        page.locator("#modal").get_by_role("button", name="Delete chat", exact=True).click()
        page.get_by_role("button", name="Cancel", exact=True).wait_for(state="visible")

    def wait_pending(self, page, fixture, count=1):
        deadline = time.monotonic() + 5
        while len(fixture.pending_messages) < count and time.monotonic() < deadline:
            page.wait_for_timeout(25)
        self.assertGreaterEqual(len(fixture.pending_messages), count, "Expected deliberately delayed message requests")

    def test_phone_and_desktop_menu_actions_and_escape_focus(self):
        for desktop in (False, True):
            with self.subTest(desktop=desktop):
                page, fixture = self.open_app(desktop=desktop)
                self.open_menu(page)
                self.assertEqual(fixture.capability_reads, 0)
                for label in ("New chat", "Rate this chat", "Delete chat", "Capabilities", "Skyrim tools", "Reply sounds: On"):
                    self.assertTrue(page.locator("#modal").get_by_role("button", name=label, exact=True).is_visible(), label)
                page.keyboard.press("Escape")
                page.wait_for_function("!document.querySelector('#modal').open")
                self.assertTrue(page.locator("#moreBtn").evaluate("button => button === document.activeElement"))
                self.open_menu(page)
                page.locator("#modal").get_by_role("button", name="Capabilities", exact=True).click()
                page.wait_for_function("document.querySelector('#modalBody').textContent.includes('Fixture capabilities')")
                self.assertEqual(fixture.capability_reads, 1)
                page.keyboard.press("Escape")
                self.open_menu(page)
                page.locator("#modal").get_by_role("button", name="New chat", exact=True).click()
                page.wait_for_function("state.chatId === 30")
                self.assertEqual(fixture.created_count, 1)

    def test_cancel_preserves_draft_and_sends_no_delete_request(self):
        page, fixture = self.open_app()
        page.locator("#input").fill("Keep this unsent draft")
        self.open_delete(page)
        self.assertTrue(page.get_by_role("button", name="Cancel", exact=True).evaluate("button => button === document.activeElement"))
        page.get_by_role("button", name="Cancel", exact=True).click()
        self.assertEqual(page.locator("#input").input_value(), "Keep this unsent draft")
        self.assertEqual(page.evaluate("state.chatId"), 10)
        self.assertEqual(fixture.delete_requests, [])

    def test_success_deletes_current_chat_and_switches_on_both_layouts(self):
        for desktop in (False, True):
            with self.subTest(desktop=desktop):
                page, fixture = self.open_app(desktop=desktop)
                page.locator("#input").fill("Discard after confirmation")
                self.open_delete(page)
                page.locator("#modal").get_by_role("button", name="Delete chat", exact=True).click()
                page.wait_for_function("state.chatId === 20 && document.querySelector('#messages').textContent.includes('Notes reply')")
                self.assertEqual(fixture.delete_requests, [10])
                self.assertEqual([chat["id"] for chat in fixture.chats], [20])
                self.assertEqual(page.locator("#input").input_value(), "")
                self.assertNotIn("Pirates reply", page.locator("#messages").inner_text())

    def test_last_chat_deletion_does_not_automatically_create_another_chat(self):
        fixture = ChatAPIFixture(self.frontend_version)
        fixture.delete(20)
        page, fixture = self.open_app(fixture=fixture)
        self.open_delete(page)
        page.locator("#modal").get_by_role("button", name="Delete chat", exact=True).click()
        page.wait_for_function("state.chatId === null")
        page.evaluate("void syncSharedState()")
        page.wait_for_function("!state.syncInFlight")
        self.assertEqual(fixture.chats, [])
        self.assertEqual(fixture.created_count, 0)
        self.assertTrue(page.locator("#sendBtn").is_disabled())

    def test_conflict_keeps_the_chat_and_its_draft(self):
        page, fixture = self.open_app()
        fixture.reject_deletion = True
        page.locator("#input").fill("Preserve on conflict")
        self.open_delete(page)
        page.locator("#modal").get_by_role("button", name="Delete chat", exact=True).click()
        page.wait_for_function("document.querySelector('#modalBody').textContent.includes('finishing a reply')")
        self.assertEqual(page.evaluate("state.chatId"), 10)
        self.assertEqual(page.locator("#input").input_value(), "Preserve on conflict")
        self.assertEqual([chat["id"] for chat in fixture.chats], [10, 20])

    def test_another_devices_deletion_recovers_the_selected_chat(self):
        fixture = ChatAPIFixture(self.frontend_version)
        first, _ = self.open_app(fixture=fixture)
        second, _ = self.open_app(fixture=fixture)
        self.open_delete(first)
        first.locator("#modal").get_by_role("button", name="Delete chat", exact=True).click()
        first.wait_for_function("state.chatId === 20")
        second.evaluate("void syncSharedState()")
        second.wait_for_function("state.chatId === 20 && document.querySelector('#messages').textContent.includes('Notes reply')")
        self.assertNotIn("Pirates reply", second.locator("#messages").inner_text())
        self.assertEqual(fixture.created_count, 0)

    def test_stale_sync_response_does_not_overwrite_a_new_selection(self):
        page, fixture = self.open_app()
        fixture.delay_messages_for = 10
        page.evaluate("void syncSharedState()")
        self.wait_pending(page, fixture)
        page.locator("#menuBtn").click()
        page.locator("#chatList").get_by_role("button", name=re.compile("Notes")).click()
        page.wait_for_function("state.chatId === 20")
        fixture.release_messages()
        page.wait_for_function("!state.syncInFlight")
        self.assertEqual(page.evaluate("state.chatId"), 20)
        self.assertIn("Notes reply", page.locator("#messages").inner_text())
        self.assertNotIn("Pirates reply", page.locator("#messages").inner_text())

    def test_stale_load_response_does_not_overwrite_a_newer_selection(self):
        page, fixture = self.open_app()
        fixture.delay_messages_for = 20
        page.evaluate("void loadChat(20)")
        self.wait_pending(page, fixture)
        page.evaluate("void loadChat(10)")
        page.wait_for_function("state.chatId === 10 && document.querySelector('#messages').textContent.includes('Pirates reply')")
        fixture.release_messages()
        page.wait_for_timeout(100)
        self.assertEqual(page.evaluate("state.chatId"), 10)
        self.assertIn("Pirates reply", page.locator("#messages").inner_text())
        self.assertNotIn("Notes reply", page.locator("#messages").inner_text())

    def test_stale_failed_load_does_not_cancel_a_newer_chat_selection(self):
        for status in (404, 500):
            with self.subTest(status=status):
                fixture = ChatAPIFixture(self.frontend_version)
                fixture.chats.append(fixture.chat(30, "Delayed chat"))
                fixture.messages[30] = [fixture.message(301, "Delayed reply")]
                page, fixture = self.open_app(desktop=True, fixture=fixture)
                fixture.delay_messages_for = 30
                page.locator("#chatList").get_by_role("button", name=re.compile("Delayed chat")).click()
                self.wait_pending(page, fixture)
                fixture.delay_messages_for = 20
                page.locator("#chatList").get_by_role("button", name=re.compile("Notes")).click()
                self.wait_pending(page, fixture, count=2)
                old_route, _ = fixture.pending_messages.pop(0)
                fixture.respond(old_route, {"ok": False, "error": "Obsolete load failure"}, status=status)
                # Allow the old click handler's catch path to settle while the
                # user's newer choice remains deliberately in flight.
                page.wait_for_timeout(100)
                self.assertFalse(page.locator("#modal").evaluate("dialog => dialog.open"))
                fixture.release_messages()
                page.wait_for_function("state.chatId === 20 && !state.loadingChat")
                self.assertIn("Notes reply", page.locator("#messages").inner_text())
                self.assertNotIn("Pirates reply", page.locator("#messages").inner_text())
                self.assertNotIn("Delayed reply", page.locator("#messages").inner_text())
                self.assertFalse(page.locator("#modal").evaluate("dialog => dialog.open"))

    def test_hostile_chat_title_is_rendered_as_text_in_confirmation(self):
        fixture = ChatAPIFixture(self.frontend_version)
        title = "<img src=x onerror='window.menuTitleXss=true'> Pirates"
        fixture.chats[0]["title"] = title
        page, _ = self.open_app(fixture=fixture)
        self.open_delete(page)
        self.assertIn(title, page.locator("#modalBody").inner_text())
        self.assertEqual(page.locator("#modal img").count(), 0)
        self.assertFalse(page.evaluate("Boolean(window.menuTitleXss)"))


if __name__ == "__main__":
    unittest.main()
