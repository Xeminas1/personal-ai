from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from app import mobile_server, worker_server


class SupportHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "app").mkdir()
        (self.root / "app/version.py").write_text('VERSION = "test"\n')
        (self.root / "main.py").write_bytes(b"# allowed source\n")
        (self.root / "config.json").write_text('{"model":"qwen3:1.7b", "password":"excluded-secret"}')
        self.addCleanup(patch.stopall)
        patch.object(mobile_server, "BASE_DIR", self.root).start()
        patch.object(worker_server, "BASE_DIR", self.root).start()
        patch("app.hybrid_autosetup._tailscale_exe", return_value=None).start()
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.mobile = self.serve(mobile_server.XemAiMobileServer, mobile_server.XemAiMobileHandler)
        self.worker = self.serve(worker_server.XemAiWorkerServer, worker_server.XemAiWorkerHandler)

    def serve(self, server_type, handler):
        server = server_type(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def close():
            server.shutdown()
            server.server_close()
            thread.join()
        self.addCleanup(close)
        return f"http://127.0.0.1:{server.server_port}"

    def request(self, base, path, *, token=None, method="GET", origin=None):
        headers = {"Content-Type": "application/json"}
        if token: headers["Authorization"] = "Bearer " + token
        if origin: headers["Origin"] = origin
        request = urllib.request.Request(base + path, headers=headers, method=method,
            data=b"{}" if method == "POST" else None)
        try:
            response = self.opener.open(request, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.headers, json.load(response)

    def test_enable_read_revoke_and_http_privacy_boundary(self):
        self.assertEqual(self.request(self.mobile, "/api/support/files")[0], 401)
        self.assertEqual(self.request(self.mobile, "/api/support/enable", method="POST")[0], 403)
        self.assertEqual(self.request(self.mobile, "/api/support/enable", method="POST", origin="https://other.example")[0], 403)
        status, headers, enabled = self.request(self.mobile, "/api/support/enable", method="POST", origin=self.mobile)
        self.assertEqual(status, 200)
        self.assertEqual(headers["Cache-Control"], "no-store")
        token = enabled["token"]
        self.assertEqual(self.request(self.worker, "/api/support/files", token=token)[0], 200)
        self.assertEqual(self.request(self.mobile, "/api/support/files", token="x" * 43)[0], 401)
        report = self.request(self.mobile, "/api/support/report", token=token)[2]
        self.assertNotIn("excluded-secret", json.dumps(report))
        self.assertFalse(report["report"]["tailscale"]["executable_found"])
        self.assertEqual(self.request(self.worker, "/api/support/file?path=main.py", token=token)[2]["file"]["content"], "# allowed source\n")
        for path in ("../main.py", "data/secrets.json", "data/personal_ai.db", "data/support_access.json"):
            self.assertEqual(self.request(self.worker, "/api/support/file?path=" + path, token=token)[0], 400)
        self.assertEqual(self.request(self.worker, "/api/support/file?path=main.py&path=config.json", token=token)[0], 400)
        self.assertEqual(self.request(self.worker, "/api/support/file?path=main.py&write=1", token=token)[0], 400)
        self.assertEqual(self.request(self.worker, "/api/support/disable", token=token, method="POST", origin=self.worker)[0], 405)
        self.assertEqual(self.request(self.mobile, "/api/support/enable", token=token, method="POST", origin=self.mobile)[0], 403)
        self.assertEqual(self.request(self.mobile, "/api/chats", token=token, method="POST", origin=self.mobile)[0], 403)
        self.assertEqual(self.request(self.mobile, "/api/update/install", token=token, method="POST", origin=self.mobile)[0], 403)
        self.assertEqual(self.request(self.mobile, "/api/support/enable?unexpected=1", method="POST", origin=self.mobile)[0], 403)
        self.assertEqual(self.request(self.mobile, "/api/support/disable", method="POST", origin=self.mobile)[0], 200)
        self.assertEqual(self.request(self.worker, "/api/support/files", token=token)[0], 401)
        self.assertFalse((self.root / "data/personal_ai.db").exists())


if __name__ == "__main__":
    unittest.main()
