"""Render durable specialist metadata through the actual phone/desktop UI."""
from __future__ import annotations

import unittest

import test_chat_menu as chat_menu
from test_chat_menu import ChatAPIFixture, HAS_PLAYWRIGHT


@unittest.skipUnless(HAS_PLAYWRIGHT, "Playwright is not installed")
class SpecialistBrowserTests(unittest.TestCase):
    # Share the real Chromium/static-server harness without inheriting its
    # unrelated menu tests or changing existing fixtures.
    setUpClass = classmethod(chat_menu.ChatMenuBrowserTests.setUpClass.__func__)
    tearDownClass = classmethod(chat_menu.ChatMenuBrowserTests.tearDownClass.__func__)
    setUp = chat_menu.ChatMenuBrowserTests.setUp
    close_contexts = chat_menu.ChatMenuBrowserTests.close_contexts
    open_app = chat_menu.ChatMenuBrowserTests.open_app

    def fixture(self, messages):
        fixture = ChatAPIFixture(self.frontend_version)
        fixture.messages[10] = messages
        return fixture

    @staticmethod
    def answer(identifier=101, *, roles=None, **fields):
        message = ChatAPIFixture.message(identifier, "A supported answer stays unchanged.")
        message.update(inference_model="qwen3:8b", inference_compute="remote_worker")
        if roles is not None:
            message["specialist_roles"] = roles
        message.update(fields)
        return message

    def test_supported_roles_render_below_existing_metadata_on_both_layouts(self):
        for desktop in (False, True):
            with self.subTest(desktop=desktop):
                messages = [
                    self.answer(101, roles=["research", "reviewer"]),
                    self.answer(102, roles=["skyrim", "reviewer"]),
                    self.answer(103, roles=["research", "skyrim"]),
                ]
                page, _ = self.open_app(desktop=desktop, fixture=self.fixture(messages))
                expected = ["Specialist help: Research · Reviewer",
                            "Specialist help: Skyrim · Reviewer",
                            "Specialist help: Research · Skyrim"]
                self.assertEqual(page.locator(".specialist-metadata").all_text_contents(), expected)
                self.assertEqual(page.locator(".message-body").all_text_contents(),
                                 [message["content"] for message in messages])
                self.assertEqual(page.locator(".message-inference").all_text_contents(),
                                 ["Answered by Worker · qwen3:8b"] * 3)
                for index in range(3):
                    answer = page.locator("#messages .message.assistant").nth(index)
                    placement = answer.evaluate("""element => {
                        const meta = element.querySelector('.message-meta');
                        const inference = element.querySelector('.message-inference');
                        const specialist = element.querySelector('.specialist-metadata');
                        return {
                            afterMeta: Boolean(meta.compareDocumentPosition(specialist) & Node.DOCUMENT_POSITION_FOLLOWING),
                            afterInference: Boolean(inference.compareDocumentPosition(specialist) & Node.DOCUMENT_POSITION_FOLLOWING),
                            top: specialist.getBoundingClientRect().top,
                            previousBottom: inference.getBoundingClientRect().bottom,
                            display: getComputedStyle(specialist).display,
                        };
                    }""")
                    self.assertTrue(placement["afterMeta"])
                    self.assertTrue(placement["afterInference"])
                    self.assertGreaterEqual(placement["top"], placement["previousBottom"] - 0.5)
                    self.assertNotEqual(placement["display"], "none")

    def test_legacy_unknown_and_malformed_fields_have_no_specialist_line(self):
        messages = [self.answer(101)]
        for identifier, roles in enumerate(([], ["unknown"], ["Research"],
                                             "research", {"role": "research"},
                                             [None, 42, {"role": "research"}]), start=102):
            messages.append(self.answer(identifier, roles=roles))
        # Explicit JSON null is a legacy-compatible absence as well.
        messages.append(self.answer(110, specialist_roles=None))
        page, _ = self.open_app(fixture=self.fixture(messages))
        self.assertEqual(page.locator("#messages .message.assistant").count(), len(messages))
        self.assertEqual(page.locator(".specialist-metadata").count(), 0)
        self.assertEqual(page.locator(".message-inference").count(), len(messages))

    def test_mixed_hostile_roles_are_ignored_and_supported_roles_are_bounded(self):
        hostile = "<img src=x onerror='window.specialistXss=true'>"
        messages = [
            self.answer(101, roles=[hostile, "__proto__", "constructor", None,
                                    {"role": "research"}, "research", "reviewer"]),
            self.answer(102, roles=["research", "research", "skyrim", "reviewer"]),
        ]
        page, _ = self.open_app(fixture=self.fixture(messages))
        self.assertEqual(page.locator(".specialist-metadata").all_text_contents(),
                         ["Specialist help: Research · Reviewer",
                          "Specialist help: Research · Skyrim"])
        self.assertEqual(page.locator("#messages img").count(), 0)
        self.assertNotIn(hostile, page.locator("#messages").inner_text())
        self.assertFalse(page.evaluate("Boolean(window.specialistXss)"))
        self.assertEqual(page.locator("#messages .message.assistant").count(), 2)

    def test_user_and_error_messages_do_not_display_specialist_roles(self):
        messages = [
            self.answer(101, roles=["research", "reviewer"], role="user", content="A user question"),
            self.answer(102, roles=["research", "reviewer"],
                        content="⚠️ XemAi couldn't complete that reply.\n\nTry again."),
        ]
        page, _ = self.open_app(fixture=self.fixture(messages))
        self.assertEqual(page.locator("#messages .message.user").count(), 1)
        self.assertEqual(page.locator("#messages .retry-reply-btn").count(), 1)
        self.assertEqual(page.locator(".specialist-metadata").count(), 0)

    def test_reloading_fetches_and_retains_saved_specialist_roles(self):
        message = self.answer(101, roles=["skyrim", "reviewer"])
        page, _ = self.open_app(fixture=self.fixture([message]))
        expected = "Specialist help: Skyrim · Reviewer"
        self.assertEqual(page.locator(".specialist-metadata").inner_text(), expected)
        page.reload()
        page.wait_for_function("state.bootstrap && state.chatId === 10 && !state.loadingChat")
        self.assertEqual(page.locator(".specialist-metadata").inner_text(), expected)
        self.assertEqual(page.locator(".message-body").inner_text(), message["content"])
        self.assertEqual(page.locator(".message-inference").inner_text(),
                         "Answered by Worker · qwen3:8b")

    def test_sync_rerenders_when_only_saved_specialist_roles_change(self):
        message = self.answer(101)
        page, fixture = self.open_app(fixture=self.fixture([message]))
        self.assertEqual(page.locator(".specialist-metadata").count(), 0)
        unchanged = {key: value for key, value in message.items() if key != "specialist_roles"}
        for roles, expected in ((["research", "reviewer"], "Specialist help: Research · Reviewer"),
                                (["skyrim"], "Specialist help: Skyrim"), ([], None)):
            with self.subTest(roles=roles):
                fixture.messages[10][0]["specialist_roles"] = roles
                page.wait_for_function("!state.syncInFlight && !state.loadingChat")
                page.evaluate("syncSharedState()")
                if expected:
                    page.wait_for_function("expected => document.querySelector('.specialist-metadata')?.textContent === expected",
                                           arg=expected)
                    self.assertEqual(page.locator(".specialist-metadata").count(), 1)
                else:
                    page.wait_for_function("!document.querySelector('.specialist-metadata')")
                self.assertEqual({key: value for key, value in fixture.messages[10][0].items()
                                  if key != "specialist_roles"}, unchanged)
                self.assertEqual(page.locator(".message-body").inner_text(), message["content"])
                self.assertEqual(page.locator(".message-inference").inner_text(),
                                 "Answered by Worker · qwen3:8b")


if __name__ == "__main__":
    unittest.main()
