"""Exercise sidebar, composer and vision readiness in the actual browser UI."""
from __future__ import annotations

import copy
import unittest
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import test_chat_menu as chat_menu
from test_chat_menu import ChatAPIFixture, HAS_PLAYWRIGHT


class UIAPIFixture(ChatAPIFixture):
    def __init__(self, version):
        super().__init__(version)
        self.vision_status = {"ok": True, "ready": False, "installing": False,
                              "error": "PC visual analysis is not activated."}
        self.vision_reads = 0
        self.setup_requests = 0
        self.fail_vision = False
        self.hold_vision = False
        self.pending_vision = []
        self.sent_messages = []

    def handle(self, route):
        request = route.request
        path = urlparse(request.url).path
        if path == "/api/vision/status" and request.method == "GET":
            self.vision_reads += 1
            if self.hold_vision:
                self.pending_vision.append(route)
                return
            if self.fail_vision:
                return self.respond(route, {"ok": False, "error": "PC unavailable."}, 503)
            return self.respond(route, copy.deepcopy(self.vision_status))
        if path == "/api/vision/setup" and request.method == "POST":
            self.setup_requests += 1
            self.vision_status = {"ok": True, "ready": False, "installing": True}
            return self.respond(route, copy.deepcopy(self.vision_status))
        if path == "/api/chats/10/messages" and request.method == "POST":
            self.sent_messages.append(request.post_data_json)
            return self.respond(route, {"ok": True, "status": "XemAi is thinking"}, 202)
        return super().handle(route)

    def release_vision(self):
        self.hold_vision = False
        pending, self.pending_vision = self.pending_vision, []
        for route in pending:
            self.respond(route, copy.deepcopy(self.vision_status))


@unittest.skipUnless(HAS_PLAYWRIGHT, "Playwright is not installed")
class UIUpdateBrowserTests(unittest.TestCase):
    # Reuse the existing real Chromium/static-server harness without inheriting
    # its test methods or changing the chat menu fixtures.
    setUpClass = classmethod(chat_menu.ChatMenuBrowserTests.setUpClass.__func__)
    tearDownClass = classmethod(chat_menu.ChatMenuBrowserTests.tearDownClass.__func__)
    setUp = chat_menu.ChatMenuBrowserTests.setUp
    close_contexts = chat_menu.ChatMenuBrowserTests.close_contexts
    open_menu = chat_menu.ChatMenuBrowserTests.open_menu

    def open_app(self, *, desktop=False, fixture=None):
        return chat_menu.ChatMenuBrowserTests.open_app(
            self, desktop=desktop, fixture=fixture or UIAPIFixture(self.frontend_version))

    @staticmethod
    def open_drawer(page, desktop):
        if not desktop:
            page.locator("#menuBtn").click()
            page.wait_for_function("document.querySelector('#drawer').classList.contains('open')")

    @staticmethod
    def chat_titles(page):
        return page.locator("#chatList .chat-title-text").all_text_contents()

    def test_sidebar_and_menu_remove_duplicate_support_update_actions(self):
        for desktop in (False, True):
            with self.subTest(desktop=desktop):
                page, fixture = self.open_app(desktop=desktop)
                self.open_drawer(page, desktop)
                sidebar = page.locator("#drawer")
                for label in ("Capabilities", "Live support", "Update XemAi"):
                    self.assertEqual(sidebar.get_by_role("button", name=label, exact=True).count(), 0)
                self.assertTrue(sidebar.get_by_role("button", name="Skyrim tools").is_visible())
                self.assertEqual(page.locator("#supportBtn, #updateBtn, #capabilitiesBtn").count(), 0)
                if not desktop:
                    page.locator("#closeDrawerBtn").click()
                self.open_menu(page)
                menu = page.locator("#modal")
                for label in ("Live support", "Update XemAi"):
                    self.assertEqual(menu.get_by_role("button", name=label, exact=True).count(), 0)
                self.assertEqual(menu.get_by_role("button", name="Capabilities", exact=True).count(), 1)
                self.assertEqual(fixture.setup_requests, 0)

    def test_sidebar_orders_actual_dates_and_updates_without_switching_chat(self):
        fixture = UIAPIFixture(self.frontend_version)
        newest = fixture.chat(10, "Newest lower ID")
        newest.update(created_at="2026-01-01T12:00:00+00:00",
                      updated_at="2026-01-02T12:00:00.001+00:00")
        older = fixture.chat(20, "Older higher ID")
        older["updated_at"] = "2026-01-01T12:00:00+00:00"
        fallback = fixture.chat(40, "Creation fallback")
        fallback.update(updated_at="invalid date", created_at="2026-01-01T09:00:00+00:00")
        offset = fixture.chat(30, "Offset equivalent")
        offset.update(updated_at="2026-01-01T10:00:00+02:00",
                      created_at="2025-12-01T00:00:00+00:00")
        tie = fixture.chat(31, "Tie lower ID")
        tie.update(updated_at="2026-01-01T08:00:00+00:00",
                   created_at="2025-12-02T00:00:00+00:00")
        tie_newer_id = {**tie, "id": 32, "title": "Tie higher ID"}
        fixture.chats = [offset, older, tie, fallback, newest, tie_newer_id]
        page, fixture = self.open_app(fixture=fixture)
        self.assertEqual(self.chat_titles(page), ["Newest lower ID", "Older higher ID",
            "Creation fallback", "Tie higher ID", "Tie lower ID", "Offset equivalent"])
        older["updated_at"] = "2026-01-03T00:00:00+00:00"
        page.evaluate("syncSharedState()")
        page.wait_for_function("document.querySelector('#chatList .chat-title-text').textContent === 'Older higher ID'")
        self.assertEqual(page.evaluate("state.chatId"), 10)
        self.assertIn("Pirates reply", page.locator("#messages").inner_text())

    def test_chat_sidebar_can_scroll_on_phone_and_desktop(self):
        for desktop in (False, True):
            with self.subTest(desktop=desktop):
                fixture = UIAPIFixture(self.frontend_version)
                start = datetime(2025, 12, 1, tzinfo=timezone.utc)
                for index in range(80):
                    chat = fixture.chat(100 + index, f"Older chat {index:02d}")
                    timestamp = (start - timedelta(days=index)).isoformat()
                    chat.update(created_at=timestamp, updated_at=timestamp)
                    fixture.chats.append(chat)
                page, _ = self.open_app(desktop=desktop, fixture=fixture)
                self.open_drawer(page, desktop)
                listing = page.locator("#chatList")
                metrics = listing.evaluate("element => ({height: element.clientHeight, total: element.scrollHeight, overflow: getComputedStyle(element).overflowY, bar: getComputedStyle(element, '::-webkit-scrollbar').width, gutter: element.offsetWidth - element.clientWidth})")
                self.assertGreater(metrics["height"], 0)
                self.assertGreater(metrics["total"], metrics["height"])
                self.assertIn(metrics["overflow"], ("auto", "scroll"))
                self.assertNotIn(metrics["bar"], ("0px", "0"))
                self.assertGreater(metrics["gutter"], 0, "Scrollbar must be visible, including on phones")
                if desktop:
                    # Exercise the native thumb, rather than only checking CSS.
                    bounds = listing.bounding_box()
                    thumb_height = metrics["height"] ** 2 / metrics["total"]
                    x = bounds["x"] + bounds["width"] - metrics["gutter"] / 2
                    y = bounds["y"] + thumb_height / 2
                    page.mouse.move(x, y)
                    page.mouse.down()
                    page.mouse.move(x, y + 100, steps=10)
                    page.mouse.up()
                    page.wait_for_function("document.querySelector('#chatList').scrollTop > 0")
                    listing.evaluate("element => element.scrollTop = 0")
                listing.hover()
                page.mouse.wheel(0, 700)
                page.wait_for_function("document.querySelector('#chatList').scrollTop > 0")
                self.assertTrue(page.locator("#drawerNewBtn").is_visible())
                self.assertTrue(page.locator("#skyrimBtn").is_visible())

    def test_upward_svg_send_control_is_accessible_and_sends(self):
        page, fixture = self.open_app()
        button = page.get_by_role("button", name="Send message", exact=True)
        self.assertEqual(button.get_attribute("type"), "submit")
        self.assertEqual(button.locator("svg").count(), 1)
        self.assertEqual(button.locator("svg").get_attribute("aria-hidden"), "true")
        geometry = button.locator("svg path").evaluate("path => { const start = path.getPointAtLength(0); const middle = path.getPointAtLength(path.getTotalLength() / 2); const box = path.getBBox(); return {startY: start.y, middleY: middle.y, width: box.width, height: box.height}; }")
        self.assertGreater(geometry["startY"], geometry["middleY"])
        self.assertGreater(geometry["width"], 0)
        self.assertGreaterEqual(geometry["height"], geometry["width"])
        page.locator("#input").fill("Send using the new arrow")
        with page.expect_response(lambda response: urlparse(response.url).path == "/api/chats/10/messages"
                                  and response.request.method == "POST"):
            button.locator("svg").click()
        page.wait_for_function("document.querySelector('#input').value === ''")
        self.assertEqual(fixture.sent_messages, [{"text": "Send using the new arrow", "attachments": []}])

    def test_vision_neutral_ready_down_installing_and_ready_without_auto_download(self):
        fixture = UIAPIFixture(self.frontend_version)
        fixture.hold_vision = True
        fixture.vision_status = {"ok": True, "ready": True, "installing": False}
        page, fixture = self.open_app(fixture=fixture)
        indicator = page.locator("#visionSidebarIndicator")
        self.assertNotEqual(indicator.get_attribute("data-state"), "ready")
        self.assertNotIn("✓", indicator.text_content())
        self.assertEqual(fixture.setup_requests, 0)
        fixture.release_vision()
        page.wait_for_function("document.querySelector('#visionSidebarIndicator').dataset.state === 'ready'")
        page.locator("#menuBtn").click()
        page.locator("#skyrimBtn").click()
        page.wait_for_function("document.querySelector('#visionReadyState')?.dataset.state === 'ready'")
        self.assertIn("✓", page.locator("#visionReadyState").inner_text())
        self.assertTrue(page.locator("#visionSetupBtn").is_disabled())
        self.assertEqual(fixture.setup_requests, 0)

        # A failed fresh check removes the ready tick immediately.
        fixture.fail_vision = True
        page.locator("#visionCheckBtn").click()
        page.wait_for_function("document.querySelector('#visionReadyState').dataset.state === 'unavailable'")
        self.assertNotIn("✓", indicator.text_content())
        self.assertNotIn("✓", page.locator("#visionReadyState").inner_text())
        self.assertEqual(fixture.setup_requests, 0)

        fixture.fail_vision = False
        page.locator("#visionSetupBtn").click()
        page.wait_for_function("document.querySelector('#visionReadyState').dataset.state === 'installing'")
        self.assertEqual(fixture.setup_requests, 1)
        self.assertNotIn("✓", indicator.text_content())
        self.assertTrue(page.locator("#visionSetupBtn").is_disabled())
        fixture.vision_status = {"ok": True, "ready": True, "installing": False}
        page.locator("#visionCheckBtn").click()
        page.wait_for_function("document.querySelector('#visionReadyState').dataset.state === 'ready'")
        self.assertEqual(fixture.setup_requests, 1)
        self.assertGreaterEqual(fixture.vision_reads, 4)

    def test_vision_background_checks_and_strict_ready_boolean(self):
        fixture = UIAPIFixture(self.frontend_version)
        fixture.vision_status = {"ok": True, "ready": "true", "installing": False}
        page, fixture = self.open_app(fixture=fixture)
        page.wait_for_function("document.querySelector('#visionSidebarIndicator').dataset.state === 'unavailable'")
        self.assertNotIn("✓", page.locator("#visionSidebarIndicator").text_content())
        initial_reads = fixture.vision_reads
        page.clock.install()
        fixture.vision_status = {"ok": True, "ready": True, "installing": False}
        page.clock.fast_forward(31000)
        page.wait_for_function("document.querySelector('#visionSidebarIndicator').dataset.state === 'ready'")
        self.assertGreater(fixture.vision_reads, initial_reads)
        self.assertEqual(fixture.setup_requests, 0)

    def test_reply_sound_toggle_persists_after_reopening_menu(self):
        page, _ = self.open_app()
        self.open_menu(page)
        enabled = page.get_by_role("button", name="Reply sounds: On", exact=True)
        self.assertEqual(enabled.get_attribute("aria-pressed"), "true")
        enabled.click()
        self.assertEqual(page.get_by_role("button", name="Reply sounds: Off", exact=True).get_attribute("aria-pressed"), "false")
        self.assertEqual(page.evaluate("localStorage.getItem('xemai.replySound')"), "false")
        page.keyboard.press("Escape")
        self.open_menu(page)
        page.get_by_role("button", name="Reply sounds: Off", exact=True).click()
        self.assertEqual(page.evaluate("window.XemAiNotifications.isEnabled()"), True)

    def test_offline_clears_ready_and_rejects_stale_status_until_reconnected(self):
        fixture = UIAPIFixture(self.frontend_version)
        fixture.vision_status = {"ok": True, "ready": True, "installing": False}
        page, fixture = self.open_app(fixture=fixture)
        page.wait_for_function("document.querySelector('#visionSidebarIndicator').dataset.state === 'ready'")
        fixture.hold_vision = True
        page.evaluate("window.__heldVision = refreshVisionStatus(); undefined")
        page.wait_for_function("document.querySelector('#visionSidebarIndicator').dataset.state === 'checking'")
        page.evaluate("window.dispatchEvent(new Event('offline'))")
        indicator = page.locator("#visionSidebarIndicator")
        self.assertEqual(indicator.get_attribute("data-state"), "unavailable")
        self.assertNotIn("✓", indicator.text_content())
        self.assertIn("offline", indicator.get_attribute("aria-label"))
        fixture.release_vision()
        page.evaluate("window.__heldVision")
        self.assertEqual(indicator.get_attribute("data-state"), "unavailable")
        reads = fixture.vision_reads
        page.evaluate("refreshVisionStatus()")
        self.assertEqual(fixture.vision_reads, reads)
        page.evaluate("window.dispatchEvent(new Event('online'))")
        page.wait_for_function("document.querySelector('#visionSidebarIndicator').dataset.state === 'ready'")
        self.assertGreater(fixture.vision_reads, reads)
        self.assertEqual(fixture.setup_requests, 0)


if __name__ == "__main__":
    unittest.main()
