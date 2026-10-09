"""Exercise reply sound delivery and real WebAudio nodes in Chromium."""
from __future__ import annotations

import importlib.util
import re
import shutil
import tempfile
import threading
import unittest
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from test_chat_menu import ChatAPIFixture


ROOT = Path(__file__).resolve().parent
HAS_PLAYWRIGHT = importlib.util.find_spec("playwright") is not None

PROBE_SCRIPT = """() => {
  window.audioProbe = {contexts: [], oscillators: [], gains: [], errors: []};
  window.addEventListener('error', event => audioProbe.errors.push(event.message));
  window.addEventListener('unhandledrejection', event => audioProbe.errors.push(String(event.reason)));
  const NativeAudio = window.AudioContext;
  if (!NativeAudio) return;
  window.AudioContext = class extends NativeAudio {
    constructor(...args) {
      super(...args);
      audioProbe.contexts.push(this);
      const oscillatorFactory = this.createOscillator.bind(this);
      this.createOscillator = () => {
        const node = oscillatorFactory();
        const record = {node, start: null, stop: null, connected: false};
        audioProbe.oscillators.push(record);
        const start = node.start.bind(node), stop = node.stop.bind(node), connect = node.connect.bind(node);
        node.start = time => { record.start = time; return start(time); };
        node.stop = time => { record.stop = time; return stop(time); };
        node.connect = target => { record.connected = target instanceof GainNode; return connect(target); };
        return node;
      };
      const gainFactory = this.createGain.bind(this);
      this.createGain = () => {
        const node = gainFactory();
        const record = {node, envelope: [], destination: false, peak: 0, latePeak: 0};
        audioProbe.gains.push(record);
        for (const method of ['setValueAtTime', 'linearRampToValueAtTime']) {
          const operation = node.gain[method].bind(node.gain);
          node.gain[method] = (value, time) => {
            record.envelope.push({method, value, time});
            return operation(value, time);
          };
        }
        const connect = node.connect.bind(node);
        node.connect = target => {
          record.destination = target === this.destination;
          const analyser = this.createAnalyser();
          analyser.fftSize = 512;
          const samples = new Float32Array(analyser.fftSize);
          connect(analyser); analyser.connect(target);
          const began = performance.now();
          const timer = setInterval(() => {
            analyser.getFloatTimeDomainData(samples);
            const peak = samples.reduce((maximum, sample) => Math.max(maximum, Math.abs(sample)), 0);
            record.peak = Math.max(record.peak, peak);
            if (performance.now() - began > 400) record.latePeak = Math.max(record.latePeak, peak);
            if (performance.now() - began > 550) { clearInterval(timer); analyser.disconnect(); }
          }, 3);
          return analyser;
        };
        return node;
      };
    }
  };
}"""


@unittest.skipUnless(HAS_PLAYWRIGHT, "Playwright is not installed")
class ReplyNotificationBrowserTests(unittest.TestCase):
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
            executable_path=executable, headless=True,
            args=["--no-sandbox", "--autoplay-policy=document-user-activation-required"],
        )
        cls.files = tempfile.TemporaryDirectory()
        directory = Path(cls.files.name)
        shutil.copytree(ROOT / "mobile", directory, dirs_exist_ok=True)
        shutil.copyfile(directory / "index.html", directory / "xemai.html")
        cls.frontend_version = re.search(r'FRONTEND_VERSION\s*=\s*"([^"]+)"', (directory / "app.js").read_text(encoding="utf-8"))[1]
        (directory / "index.html").write_text("""<!doctype html>
          <button id="gesture">Interact</button><script src="/notifications.js"></script>
          <script>document.addEventListener('pointerdown', () => XemAiNotifications.unlock());
          document.addEventListener('keydown', () => XemAiNotifications.unlock());</script>""", encoding="utf-8")

        class QuietHandler(SimpleHTTPRequestHandler):
            def log_message(self, *_args):
                pass

        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), partial(QuietHandler, directory=str(directory)))
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=3)
        cls.files.cleanup()
        cls.browser.close()
        cls.playwright.stop()

    def setUp(self):
        self.context = self.browser.new_context(service_workers="block")
        self.addCleanup(self.context.close)
        self.page = self.context.new_page()
        self.page.add_init_script("(" + PROBE_SCRIPT + ")()")
        self.page.goto(self.base)

    def observe(self, rows, chat=10, *, baseline=False):
        return self.page.evaluate("args => XemAiNotifications.observe(args.chat, args.rows, {baseline:args.baseline})",
                                  {"chat": chat, "rows": rows, "baseline": baseline})

    def count_tones(self):
        return self.page.evaluate("audioProbe.oscillators.length")

    def unlock(self):
        self.page.locator("#gesture").click()
        self.page.wait_for_function("audioProbe.contexts[0]?.state === 'running'")

    def open_chat_app(self):
        fixture = ChatAPIFixture(self.frontend_version)
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.route("**/api/**", fixture.handle)
        self.page.goto(self.base + "/xemai.html")
        self.page.wait_for_function("state.bootstrap && state.chatId === 10 && !state.loadingChat")
        return fixture

    def sync_app(self):
        self.page.wait_for_function("!state.syncInFlight")
        self.page.evaluate("syncSharedState()")

    def test_reply_to_sent_question_chimes_after_switch_without_replacing_visible_chat(self):
        class PendingReplyFixture(ChatAPIFixture):
            def __init__(self, version):
                super().__init__(version)
                self.generating = False
                self.sent_text = None

            def handle(self, route):
                request = route.request
                path = urlparse(request.url).path
                if path == "/api/chats/10/messages" and request.method == "POST":
                    self.sent_text = request.post_data_json["text"]
                    user_message = self.message(102, self.sent_text)
                    user_message["role"] = "user"
                    self.messages[10].append(user_message)
                    self.generating = True
                    return self.respond(route, {"ok": True, "accepted": True, "status": "XemAi is thinking"}, 202)
                if path == "/api/chats/10/activity":
                    return self.respond(route, {"ok": True, "active": self.generating, "status": "XemAi is thinking" if self.generating else None})
                return super().handle(route)

        fixture = PendingReplyFixture(self.frontend_version)
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.route("**/api/**", fixture.handle)
        self.page.goto(self.base + "/xemai.html")
        self.page.wait_for_function("state.bootstrap && state.chatId === 10 && !state.loadingChat")
        self.page.locator("#input").fill("Explain this mod conflict")
        self.page.locator("#sendBtn").click()
        self.page.wait_for_function("!state.busy && state.pendingReplyChats.has(10)")
        self.assertEqual(fixture.sent_text, "Explain this mod conflict")
        self.page.locator("#menuBtn").click()
        self.page.locator("#chatList .chat-item", has_text="Notes").click()
        self.page.wait_for_function("state.chatId === 20 && !state.loadingChat")
        self.assertEqual(self.count_tones(), 0)
        fixture.messages[10].append(fixture.message(103, "Completed the mod conflict answer"))
        fixture.generating = False
        self.sync_app()
        self.page.wait_for_function("audioProbe.oscillators.length === 2")
        self.assertEqual(self.page.evaluate("state.chatId"), 20)
        self.assertIn("Notes reply", self.page.locator("#messages").inner_text())
        self.assertNotIn("Completed the mod conflict answer", self.page.locator("#messages").inner_text())
        self.assertFalse(self.page.evaluate("state.pendingReplyChats.has(10)"))
        self.page.wait_for_timeout(300)
        self.sync_app()
        self.assertEqual(self.count_tones(), 2)
        self.assertEqual(self.page.evaluate("state.chatId"), 20)

    def test_app_sync_notifies_new_reply_but_history_switch_and_external_deletion_stay_silent(self):
        fixture = self.open_chat_app()
        self.assertEqual(self.count_tones(), 0)
        self.page.locator("#input").click()
        self.page.wait_for_function("audioProbe.contexts[0]?.state === 'running'")
        user_message = fixture.message(102, "Question")
        user_message["role"] = "user"
        fixture.messages[10].append(user_message)
        self.sync_app()
        self.assertEqual(self.count_tones(), 0)
        fixture.messages[10].append(fixture.message(103, "New worker reply"))
        self.sync_app()
        self.assertEqual(self.count_tones(), 2)
        self.sync_app()
        self.assertEqual(self.count_tones(), 2)
        self.page.wait_for_timeout(300)
        self.page.evaluate("loadChat(20)")
        self.sync_app()
        self.assertEqual(self.count_tones(), 2)
        self.page.evaluate("audioProbe.contexts[0].suspend()")
        fixture.messages[20].append(fixture.message(202, "Arrived before deletion"))
        self.sync_app()
        self.assertEqual(self.count_tones(), 2)
        fixture.delete(20)
        self.sync_app()
        self.page.wait_for_function("state.chatId === 10 && !state.loadingChat")
        self.page.locator("#input").click()
        self.page.wait_for_function("audioProbe.contexts[0].state === 'running'")
        self.assertEqual(self.count_tones(), 2)

    def test_actual_toggle_mutes_pending_sound_before_unlock_and_persists_across_reload(self):
        fixture = self.open_chat_app()
        self.page.locator("#moreBtn").click()
        toggle = self.page.locator('[data-chat-action="sounds"]')
        self.assertEqual(toggle.get_attribute("aria-pressed"), "true")
        self.page.wait_for_function("audioProbe.contexts[0]?.state === 'running'")
        self.page.evaluate("audioProbe.contexts[0].suspend()")
        fixture.messages[10].append(fixture.message(102, "Pending reply"))
        self.sync_app()
        self.assertEqual(self.count_tones(), 0)
        toggle.click()
        self.assertEqual(toggle.get_attribute("aria-pressed"), "false")
        self.assertEqual(toggle.inner_text(), "Reply sounds: Off")
        self.assertEqual(self.count_tones(), 0)
        self.page.keyboard.press("Escape")
        self.assertEqual(self.count_tones(), 0)
        self.page.reload()
        self.page.wait_for_function("state.bootstrap && state.chatId === 10 && !state.loadingChat")
        self.page.locator("#moreBtn").click()
        toggle = self.page.locator('[data-chat-action="sounds"]')
        self.assertEqual(toggle.get_attribute("aria-pressed"), "false")
        self.assertEqual(self.count_tones(), 0)
        toggle.click()
        self.page.wait_for_function("audioProbe.contexts[0]?.state === 'running'")
        fixture.messages[10].append(fixture.message(103, "Audible new reply"))
        self.sync_app()
        self.assertEqual(self.count_tones(), 2)

    def test_only_new_assistant_arrivals_sound_once_and_old_history_never_repeats(self):
        self.unlock()
        history = [{"id": 1, "role": "user"}, {"id": 2, "role": "assistant"}]
        self.assertFalse(self.observe(history))  # Even an omitted baseline is safe on first sight.
        self.assertFalse(self.observe(history, baseline=True))
        self.assertFalse(self.observe(history))
        self.assertFalse(self.observe(history + [{"id": 3, "role": "user"}]))
        self.assertEqual(self.count_tones(), 0)
        replies = history + [{"id": 3, "role": "user"}, {"id": 4, "role": "assistant"}, {"id": 5, "role": "assistant"}]
        self.assertTrue(self.observe(replies))
        self.assertEqual(self.count_tones(), 2)  # One two-note chime for the entire batch.
        self.assertFalse(self.observe(replies))
        self.assertFalse(self.observe(history, baseline=True))  # A stale response cannot lower the mark.
        self.assertFalse(self.observe(replies))
        self.assertFalse(self.observe([{"id": 90, "role": "assistant"}], chat=11, baseline=True))
        self.assertFalse(self.observe(replies, chat="10", baseline=True))
        self.page.wait_for_timeout(300)
        self.assertTrue(self.observe([{"id": "6", "role": "assistant", "content": "An error reply also arrived"}]))
        self.assertEqual(self.count_tones(), 4)

    def test_real_audio_graph_is_quiet_short_fades_and_returns_to_silence(self):
        self.unlock()
        self.observe([], baseline=True)
        self.observe([{"id": 1, "role": "assistant"}])
        self.page.wait_for_timeout(600)
        graph = self.page.evaluate("""() => ({
          state:audioProbe.contexts[0].state, errors:audioProbe.errors,
          tones:audioProbe.oscillators.map(row => ({
            type:row.node.type, frequency:row.node.frequency.value,
            duration:row.stop-row.start, connected:row.connected, start:row.start, stop:row.stop
          })),
          gains:audioProbe.gains.map(row => ({
            envelope:row.envelope, destination:row.destination, peak:row.peak, latePeak:row.latePeak
          }))
        })""")
        self.assertEqual(graph["state"], "running")
        self.assertEqual(graph["errors"], [])
        self.assertEqual(len(graph["tones"]), 2)
        self.assertLess(max(row["stop"] for row in graph["tones"]) - min(row["start"] for row in graph["tones"]), 0.35)
        for tone, gain in zip(graph["tones"], graph["gains"]):
            self.assertEqual(tone["type"], "sine")
            self.assertTrue(250 <= tone["frequency"] <= 1000)
            self.assertTrue(0.05 <= tone["duration"] <= 0.2)
            self.assertTrue(tone["connected"] and gain["destination"])
            self.assertEqual(gain["envelope"][0]["value"], 0)
            self.assertEqual(gain["envelope"][-1]["value"], 0)
            self.assertTrue(any(0 < entry["value"] <= 0.05 for entry in gain["envelope"]))
            self.assertGreater(gain["peak"], 0.001)  # Real audio samples, not just mocked method calls.
            self.assertLessEqual(gain["peak"], 0.05)
            self.assertLess(gain["latePeak"], 0.00001)

    def test_autoplay_blocked_attempt_retries_on_real_gesture_and_coalesces_pending_arrivals(self):
        # Playwright evaluate grants protocol user activation. Run the blocked
        # attempt from document startup instead, before any evaluation/click.
        self.page.add_init_script("""window.addEventListener('DOMContentLoaded', () => {
          XemAiNotifications.observe(10, [], {baseline:true});
          XemAiNotifications.observe(10, [{id:1,role:'assistant'}]);
          XemAiNotifications.observe(10, [{id:1,role:'assistant'},{id:2,role:'assistant'}]);
          const before = audioProbe.contexts.length;
          XemAiNotifications.unlock();
          setTimeout(() => { audioProbe.blockedAttempt = {
            before, state:audioProbe.contexts[0].state, tones:audioProbe.oscillators.length,
            activated:navigator.userActivation.hasBeenActive
          }; }, 20);
        });""")
        self.page.reload()
        self.page.wait_for_timeout(100)
        self.assertEqual(self.page.evaluate("audioProbe.blockedAttempt"),
                         {"before": 0, "state": "suspended", "tones": 0, "activated": False})
        self.unlock()
        self.page.wait_for_function("audioProbe.oscillators.length === 2")
        self.assertFalse(self.observe([{"id": 2, "role": "assistant"}]))
        self.assertEqual(self.count_tones(), 2)

    def test_mute_persists_drops_pending_and_muted_arrivals_and_cancels_running_sound(self):
        self.observe([], baseline=True)
        self.observe([{"id": 1, "role": "assistant"}])
        self.page.evaluate("XemAiNotifications.setEnabled(false)")
        self.assertFalse(self.page.evaluate("XemAiNotifications.isEnabled()"))
        self.page.locator("#gesture").click()
        self.assertEqual(self.count_tones(), 0)
        self.page.reload()
        self.assertFalse(self.page.evaluate("XemAiNotifications.isEnabled()"))
        self.observe([{"id": 1, "role": "assistant"}], baseline=True)
        self.observe([{"id": 2, "role": "assistant"}])
        self.page.evaluate("XemAiNotifications.setEnabled(true)")
        self.unlock()
        self.assertEqual(self.count_tones(), 0)
        self.observe([{"id": 3, "role": "assistant"}])
        self.assertEqual(self.count_tones(), 2)
        self.page.evaluate("XemAiNotifications.setEnabled(false)")
        self.page.wait_for_timeout(50)
        self.assertEqual(self.page.evaluate("audioProbe.errors"), [])
        self.assertTrue(self.page.evaluate("audioProbe.oscillators.every(row => row.stop === undefined)"))

    def test_suspended_audio_recovery_queues_one_chime_and_forgetting_chat_drops_it(self):
        self.unlock()
        self.observe([], baseline=True)
        self.page.evaluate("audioProbe.contexts[0].suspend()")
        self.observe([{"id": 1, "role": "assistant"}])
        self.observe([{"id": 2, "role": "assistant"}])
        self.assertEqual(self.count_tones(), 0)
        self.unlock()
        self.page.wait_for_function("audioProbe.oscillators.length === 2")
        self.page.wait_for_timeout(300)
        self.page.evaluate("audioProbe.contexts[0].suspend()")
        self.observe([{"id": 3, "role": "assistant"}])
        self.page.evaluate("XemAiNotifications.forgetChat(10)")
        self.unlock()
        self.assertEqual(self.count_tones(), 2)
        self.assertFalse(self.observe([{"id": 3, "role": "assistant"}], baseline=True))
        self.assertEqual(self.count_tones(), 2)

    def test_invalid_ids_and_bounded_eviction_do_not_create_false_arrivals(self):
        self.unlock()
        self.observe([], baseline=True)
        invalid = [{"id": value, "role": "assistant"} for value in (True, False, 0, -1, 1.5, "1.0", "01", "-2", "1e3", "9007199254740992", None)]
        self.assertFalse(self.observe(invalid))
        for chat in (True, 0, "01", "chat-10", None):
            self.assertFalse(self.observe([{"id": 10, "role": "assistant"}], chat=chat))
        self.assertEqual(self.count_tones(), 0)
        for chat in range(11, 150):
            self.observe([{"id": 20, "role": "assistant"}], chat=chat, baseline=True)
        # Eviction safely treats the old chat as an unseen history load.
        self.assertFalse(self.observe([{"id": 30, "role": "assistant"}], chat=10))
        self.assertEqual(self.count_tones(), 0)
        many = [{"id": i, "role": "assistant"} for i in range(1, 10001)]
        self.observe(many, baseline=True)
        self.assertFalse(self.observe(many[-50:]))
        self.assertTrue(self.observe([{"id": 10001, "role": "assistant"}]))
        self.assertEqual(self.count_tones(), 2)

    def test_missing_audio_and_unavailable_storage_never_block_chat_observation(self):
        page = self.context.new_page()
        page.add_init_script("""Object.defineProperty(window,'AudioContext',{value:undefined});
          Object.defineProperty(window,'webkitAudioContext',{value:undefined});
          Object.defineProperty(window,'localStorage',{get(){throw new DOMException('Storage unavailable');}});""")
        page.goto(self.base)
        result = page.evaluate("""async () => {
          const initial = XemAiNotifications.isEnabled();
          XemAiNotifications.observe(10, [], {baseline:true});
          const arrival = XemAiNotifications.observe(10, [{id:1,role:'assistant'}]);
          const unlocked = await XemAiNotifications.unlock();
          XemAiNotifications.setEnabled(false);
          return {initial,arrival,unlocked,enabled:XemAiNotifications.isEnabled()};
        }""")
        self.assertEqual(result, {"initial": True, "arrival": True, "unlocked": False, "enabled": False})


if __name__ == "__main__":
    unittest.main()
