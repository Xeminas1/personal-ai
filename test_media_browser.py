"""Decode real image/video fixtures in Chromium; no model or public web needed."""
from __future__ import annotations

import importlib.util
import base64
import json
import re
import shutil
import subprocess
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


@unittest.skipUnless(HAS_PLAYWRIGHT, "Playwright is not installed")
class BrowserMediaTests(unittest.TestCase):
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
        )
        cls.files = tempfile.TemporaryDirectory()
        directory = Path(cls.files.name)
        shutil.copytree(ROOT / "mobile", directory, dirs_exist_ok=True)
        shutil.copyfile(directory / "index.html", directory / "xemai.html")
        cls.frontend_version = re.search(r'FRONTEND_VERSION\s*=\s*"([^"]+)"', (directory / "app.js").read_text(encoding="utf-8"))[1]
        (directory / "index.html").write_text('<!doctype html><script src="/media.js"></script>', encoding="utf-8")
        cls.has_ffmpeg = bool(shutil.which("ffmpeg"))
        if cls.has_ffmpeg:
            subprocess.run([
                "ffmpeg", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=red:size=1800x900:rate=10:duration=0.5",
                "-f", "lavfi", "-i", "color=green:size=1800x900:rate=10:duration=0.5",
                "-f", "lavfi", "-i", "color=blue:size=1800x900:rate=10:duration=0.5",
                "-filter_complex", "[0:v][1:v][2:v]concat=n=3:v=1:a=0,format=yuv420p[v]",
                "-map", "[v]", "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8",
                str(directory / "sample.webm"),
            ], check=True, capture_output=True, timeout=60)
            subprocess.run([
                "ffmpeg", "-loglevel", "error", "-y", "-f", "lavfi", "-i",
                "color=red:size=16x16:rate=1:duration=181",
                "-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "8",
                str(directory / "long.webm"),
            ], check=True, capture_output=True, timeout=30)

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
        self.page.goto(self.base)
        self.page.evaluate("""() => {
            window.mediaURLs = { created: 0, revoked: 0 };
            const create = URL.createObjectURL.bind(URL);
            const revoke = URL.revokeObjectURL.bind(URL);
            URL.createObjectURL = (value) => { mediaURLs.created++; return create(value); };
            URL.revokeObjectURL = (value) => { mediaURLs.revoked++; return revoke(value); };
        }""")

    def require_video(self):
        if not self.has_ffmpeg:
            self.skipTest("FFmpeg is required to create the test video fixture")

    def open_chat_app(self):
        class MediaFixture(ChatAPIFixture):
            def __init__(self, version):
                super().__init__(version)
                self.status_reads = 0
                self.setup_requests = 0
                self.uploads = []

            def handle(self, route):
                request = route.request
                path = urlparse(request.url).path
                if path == "/api/vision/status":
                    self.status_reads += 1
                    return self.respond(route, {"ok": True, "ready": False, "installing": False, "error": "Vision model is not installed yet."})
                if path == "/api/vision/setup":
                    self.setup_requests += 1
                    return self.respond(route, {"ok": True, "ready": False, "installing": True})
                if path == "/api/chats/10/attachments":
                    body = request.post_data_json
                    self.uploads.append(body)
                    size = len(base64.b64decode(body["data"]))
                    return self.respond(route, {"ok": True, "attachment": {
                        "name": body["name"], "mime": body["mime"], "size": size,
                        "path": "attachments/chat_10/fixture_" + body["name"],
                    }})
                return super().handle(route)

        fixture = MediaFixture(self.frontend_version)
        self.page.set_viewport_size({"width": 390, "height": 844})
        self.page.route("**/api/**", fixture.handle)
        self.page.goto(self.base + "/xemai.html")
        self.page.wait_for_function("state.bootstrap && state.chatId === 10")
        return fixture

    def test_real_png_jpeg_webp_are_resized_and_normalized(self):
        for mime in ("image/png", "image/jpeg", "image/webp"):
            with self.subTest(mime=mime):
                result = self.page.evaluate("""async (mime) => {
                    const canvas = document.createElement('canvas');
                    canvas.width = 2400; canvas.height = 1200;
                    const context = canvas.getContext('2d');
                    context.fillStyle = '#f00'; context.fillRect(100, 100, 200, 200);
                    const blob = await new Promise(resolve => canvas.toBlob(resolve, mime));
                    const prepared = await XemAiMedia.prepare(new File([blob], 'camera.capture.png', {type:mime}));
                    const image = new Image();
                    image.src = 'data:image/jpeg;base64,' + prepared.data;
                    await image.decode();
                    const check = document.createElement('canvas');
                    check.width = check.height = 1;
                    check.getContext('2d').drawImage(image, 0, 0);
                    const pixel = [...check.getContext('2d').getImageData(0, 0, 1, 1).data];
                    return {
                        name:prepared.name, mime:prepared.mime, visual:prepared.visual,
                        width:image.width, height:image.height, bytes:atob(prepared.data).length,
                        pixel, urls: {...mediaURLs}
                    };
                }""", mime)
                self.assertEqual(result["mime"], "image/jpeg")
                self.assertEqual(result["name"], "camera.capture.jpg")
                self.assertEqual(result["visual"], {"kind": "image", "frames": []})
                self.assertEqual((result["width"], result["height"]), (1280, 640))
                self.assertLessEqual(result["bytes"], 1_000_000)
                self.assertEqual(result["urls"]["created"], result["urls"]["revoked"])
                if mime != "image/jpeg":
                    self.assertTrue(all(channel >= 250 for channel in result["pixel"][:3]))

    def test_real_video_seeks_different_frames_and_excludes_original_clip(self):
        self.require_video()
        result = self.page.evaluate("""async () => {
            const blob = await (await fetch('/sample.webm')).blob();
            const prepared = await XemAiMedia.prepare(new File([blob], 'Skyrim 🎮.webm', {type:'video/webm'}));
            const encoded = Uint8Array.from(atob(prepared.data), char => char.charCodeAt(0));
            const container = JSON.parse(new TextDecoder().decode(encoded));
            const pixels = [];
            const dimensions = [];
            for (const frame of container.frames) {
                const image = new Image(); image.src = 'data:image/jpeg;base64,' + frame.data;
                await image.decode();
                dimensions.push([image.width, image.height]);
                const canvas = document.createElement('canvas'); canvas.width = canvas.height = 1;
                canvas.getContext('2d').drawImage(image, 0, 0);
                pixels.push([...canvas.getContext('2d').getImageData(0, 0, 1, 1).data]);
            }
            return {
                mime:prepared.mime, name:prepared.name, kind:prepared.visual.kind,
                duration:container.duration, times:container.frames.map(frame=>frame.time),
                frameBytes:container.frames.map(frame=>atob(frame.data).length),
                format:container.format, originalName:container.original_name,
                keys:Object.keys(container), bytes:encoded.length,
                sameFrames:JSON.stringify(prepared.visual.frames) === JSON.stringify(container.frames),
                dimensions,pixels,urls:{...mediaURLs}
            };
        }""")
        self.assertEqual(result["format"], "xemai-video-frames-v1")
        self.assertEqual(result["mime"], "application/vnd.xemai.video-frames+json")
        self.assertEqual(result["name"], "Skyrim 🎮.xemai-video.json")
        self.assertEqual(result["originalName"], "Skyrim 🎮.webm")
        self.assertEqual(result["kind"], "video")
        self.assertEqual(set(result["keys"]), {"format", "original_name", "duration", "frames"})
        self.assertEqual(len(result["times"]), 4)
        self.assertAlmostEqual(result["duration"], 1.5, places=2)
        self.assertEqual(result["times"], sorted(result["times"]))
        self.assertEqual(result["times"][0], 0)
        self.assertGreater(result["times"][-1], 1.3)
        self.assertLess(result["times"][-1], result["duration"])
        self.assertTrue(all(size <= 600_000 for size in result["frameBytes"]))
        self.assertLessEqual(result["bytes"], 5_000_000)
        self.assertTrue(result["sameFrames"])
        self.assertEqual(result["dimensions"], [[1280, 640]] * 4)
        first, middle, last = result["pixels"][0], result["pixels"][1], result["pixels"][-1]
        self.assertGreater(first[0], 200)
        self.assertLess(first[2], 20)
        self.assertGreater(middle[1], 80)
        self.assertLess(middle[0], 20)
        self.assertGreater(last[2], 200)
        self.assertLess(last[0], 20)
        self.assertEqual(result["urls"], {"created": 1, "revoked": 1})

    def test_limits_and_unsupported_formats_reject_before_decoding(self):
        result = self.page.evaluate("""async () => {
            const cases = [
                [new File([], 'empty.png', {type:'image/png'}), 'empty_file'],
                [new File(['text'], 'example.svg', {type:'image/svg+xml'}), 'unsupported_type'],
                [new File(['x'], 'photo.jpg', {type:'image/jpeg'}), 'too_large', 25000001],
                [new File(['x'], 'clip.webm', {type:'video/webm'}), 'too_large', 250000001]
            ];
            const outcomes = [];
            for (const [file, expected, size] of cases) {
                if (size) Object.defineProperty(file, 'size', {value:size});
                try { await XemAiMedia.prepare(file); outcomes.push('unexpected success'); }
                catch (error) { outcomes.push([error.name,error.code,expected]); }
            }
            return {outcomes, urls:{...mediaURLs}};
        }""")
        for name, actual, expected in result["outcomes"]:
            self.assertEqual(name, "MediaPreparationError")
            self.assertEqual(actual, expected)
        self.assertEqual(result["urls"], {"created": 0, "revoked": 0})

    def test_invalid_image_and_video_revoke_object_urls(self):
        result = self.page.evaluate("""async () => {
            const failures = [];
            for (const type of ['image/png','video/webm']) {
                try { await XemAiMedia.prepare(new File(['not valid media'], 'broken', {type})); }
                catch (error) { failures.push([error.name,error.code]); }
            }
            return {failures,urls:{...mediaURLs}};
        }""")
        self.assertEqual(result["failures"], [["MediaPreparationError", "image_decode"], ["MediaPreparationError", "video_decode"]])
        self.assertEqual(result["urls"], {"created": 2, "revoked": 2})

    def test_real_long_video_duration_is_rejected_and_cleaned_up(self):
        self.require_video()
        result = self.page.evaluate("""async () => {
            const blob = await (await fetch('/long.webm')).blob();
            try { await XemAiMedia.prepare(new File([blob], 'long.webm', {type:'video/webm'})); return {}; }
            catch(error) { return {name:error.name,code:error.code,urls:{...mediaURLs}}; }
        }""")
        self.assertEqual(result["name"], "MediaPreparationError")
        self.assertEqual(result["code"], "video_duration")
        self.assertEqual(result["urls"], {"created": 1, "revoked": 1})

    def test_missing_seek_event_times_out_and_releases_video(self):
        self.require_video()
        result = self.page.evaluate("""async () => {
            const blob = await (await fetch('/sample.webm')).blob();
            const originalAdd = HTMLMediaElement.prototype.addEventListener;
            const originalTimeout = window.setTimeout;
            HTMLMediaElement.prototype.addEventListener = function(event,...args) {
                if (event !== 'seeked') return originalAdd.call(this,event,...args);
            };
            window.setTimeout = (callback,delay,...args) => originalTimeout(callback,delay === 10000 ? 100 : delay,...args);
            try {
                await XemAiMedia.prepare(new File([blob], 'clip.webm', {type:'video/webm'}));
                return {};
            } catch(error) {
                return {name:error.name,code:error.code,urls:{...mediaURLs}};
            } finally {
                HTMLMediaElement.prototype.addEventListener = originalAdd;
                window.setTimeout = originalTimeout;
            }
        }""")
        self.assertEqual(result["name"], "MediaPreparationError")
        self.assertEqual(result["code"], "media_timeout")
        self.assertEqual(result["urls"], {"created": 1, "revoked": 1})

    def test_skyrim_tools_status_does_not_download_until_explicit_click(self):
        fixture = self.open_chat_app()
        self.page.locator("#moreBtn").click()
        self.page.locator('[data-chat-action="skyrim"]').click()
        self.page.wait_for_function("document.querySelector('#modalBody [role=status]').textContent.includes('not installed')")
        self.assertEqual(fixture.status_reads, 1)
        self.assertEqual(fixture.setup_requests, 0)
        self.assertIn("Vortex diagnostics", self.page.locator("#modalBody").inner_text())
        self.assertIn("original video and audio are not uploaded", self.page.locator("#modalBody").inner_text())
        modal_bounds = self.page.locator("#modal").bounding_box()
        title_bounds = self.page.locator("#modalTitle").bounding_box()
        actions_bounds = self.page.locator("#modalActions").bounding_box()
        self.assertGreaterEqual(title_bounds["y"], modal_bounds["y"])
        self.assertLessEqual(title_bounds["y"] + title_bounds["height"], modal_bounds["y"] + modal_bounds["height"])
        self.assertGreaterEqual(actions_bounds["y"], modal_bounds["y"])
        self.assertLessEqual(actions_bounds["y"] + actions_bounds["height"], modal_bounds["y"] + modal_bounds["height"])
        self.page.screenshot(path="/tmp/xemai-skyrim-tools-phone.png", full_page=True)
        self.page.get_by_role("button", name="Enable PC visual analysis", exact=True).click()
        self.page.wait_for_function("document.querySelector('#modalBody [role=status]').textContent.includes('downloading')")
        self.assertEqual(fixture.setup_requests, 1)
        self.assertTrue(self.page.get_by_role("button", name="Enable PC visual analysis", exact=True).is_disabled())

    def test_chat_image_upload_sends_only_normalized_jpeg(self):
        fixture = self.open_chat_app()
        data = self.page.evaluate("""() => {
            const canvas = document.createElement('canvas'); canvas.width = 2400; canvas.height = 1200;
            const context = canvas.getContext('2d'); context.fillStyle = 'red'; context.fillRect(0,0,2400,1200);
            return canvas.toDataURL('image/png').split(',')[1];
        }""")
        raw = base64.b64decode(data)
        self.page.locator("#fileInput").set_input_files({"name": "skyrim-screen.png", "mimeType": "image/png", "buffer": raw})
        self.page.wait_for_function("state.pendingAttachments.length === 1 && !state.uploadingAttachments")
        self.assertEqual(len(fixture.uploads), 1)
        upload = fixture.uploads[0]
        self.assertEqual(set(upload), {"name", "mime", "data"})
        self.assertEqual(upload["mime"], "image/jpeg")
        self.assertEqual(upload["name"], "skyrim-screen.jpg")
        prepared = base64.b64decode(upload["data"])
        self.assertTrue(prepared.startswith(b"\xff\xd8\xff"))
        self.assertNotEqual(prepared, raw)
        self.assertLessEqual(len(prepared), 1_000_000)
        dimensions = self.page.evaluate("""async data => {
            const image = new Image(); image.src = 'data:image/jpeg;base64,' + data;
            await image.decode(); return [image.width,image.height];
        }""", upload["data"])
        self.assertEqual(dimensions, [1280, 640])

    def test_chat_video_upload_sends_frames_container_and_never_original_clip(self):
        self.require_video()
        fixture = self.open_chat_app()
        clip = (Path(self.files.name) / "sample.webm").read_bytes()
        self.page.locator("#fileInput").set_input_files({"name": "skyrim.webm", "mimeType": "video/webm", "buffer": clip})
        self.page.wait_for_function("state.pendingAttachments.length === 1 && !state.uploadingAttachments")
        self.assertEqual(len(fixture.uploads), 1)
        upload = fixture.uploads[0]
        self.assertEqual(set(upload), {"name", "mime", "data"})
        self.assertEqual(upload["mime"], "application/vnd.xemai.video-frames+json")
        self.assertEqual(upload["name"], "skyrim.xemai-video.json")
        payload = base64.b64decode(upload["data"])
        self.assertNotEqual(payload, clip)
        self.assertNotIn(base64.b64encode(clip).decode("ascii"), json.dumps(upload))
        container = json.loads(payload)
        self.assertEqual(container["format"], "xemai-video-frames-v1")
        self.assertEqual(len(container["frames"]), 4)
        self.assertNotIn("audio", container)
        self.assertEqual(set(container), {"format", "original_name", "duration", "frames"})
        self.assertTrue(all(base64.b64decode(frame["data"]).startswith(b"\xff\xd8\xff") for frame in container["frames"]))

    def test_sampler_failure_never_uploads_or_adds_pending_attachment(self):
        fixture = self.open_chat_app()
        self.page.locator("#fileInput").set_input_files({"name": "broken.webm", "mimeType": "video/webm", "buffer": b"not a playable video"})
        self.page.wait_for_function("document.querySelector('#modal').open && document.querySelector('#modalTitle').textContent === 'Attachment failed'")
        self.page.wait_for_function("state.uploadingAttachments === 0")
        self.assertEqual(fixture.uploads, [])
        self.assertEqual(self.page.evaluate("state.pendingAttachments"), [])
        self.assertIn("could not read this video codec", self.page.locator("#modalBody").inner_text())


if __name__ == "__main__":
    unittest.main()
