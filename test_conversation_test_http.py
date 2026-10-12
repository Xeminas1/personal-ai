"""Conversation test export boundaries on the actual mobile HTTP handler."""
from __future__ import annotations
import io
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest.mock import patch
from app import mobile_server


class ConversationTestHTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / "data"
        self.addCleanup(patch.stopall)
        patch.object(mobile_server, "DATA_DIR", self.data).start()
        self.run_id = "a" * 32
        self.path = self.data / "conversation_tests" / ("run_" + self.run_id)
        self.path.mkdir(parents=True)
        (self.path / "state.json").write_text(json.dumps({
            "run_id":self.run_id, "state":"completed", "export_ready":True,
        }))
        with zipfile.ZipFile(self.path / "results_for_review.zip", "w") as archive:
            archive.writestr("results.json", '{"scored":false,"training_applied":false}')
        self.server = mobile_server.XemAiMobileServer(("127.0.0.1",0), mobile_server.XemAiMobileHandler)
        self.thread = threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.base = "http://127.0.0.1:" + str(self.server.server_port)
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, query, token=None):
        headers = {"Authorization":"Bearer "+token} if token else {}
        request = urllib.request.Request(self.base+"/api/conversation-test/results"+query, headers=headers)
        try:
            response = self.opener.open(request,timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status,response.headers,response.read()

    def test_download_only_the_generated_zip_without_caching(self):
        status, headers, raw = self.request("?run="+self.run_id)
        self.assertEqual(status,200)
        self.assertEqual(headers["Content-Type"],"application/zip")
        self.assertEqual(headers["Cache-Control"],"no-store")
        self.assertIn(self.run_id,headers["Content-Disposition"])
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            self.assertEqual(archive.namelist(),["results.json"])
        self.assertEqual(self.request("?run="+self.run_id,token="x"*43)[0],403)

    def test_arbitrary_paths_duplicate_parameters_and_unready_runs_are_rejected(self):
        for query in ("", "?run=../secrets", "?run="+self.run_id+"&path=../../config.json",
                      "?run="+self.run_id+"&run="+self.run_id):
            self.assertEqual(self.request(query)[0],400,query)
        self.assertEqual(self.request("?run="+"b"*32)[0],404)
        (self.path/"state.json").write_text(json.dumps({
            "run_id":self.run_id,"state":"running","export_ready":False,
        }))
        self.assertEqual(self.request("?run="+self.run_id)[0],404)

    def test_symlink_export_cannot_read_an_unrelated_file(self):
        archive = self.path/"results_for_review.zip"
        archive.unlink()
        private = self.data/"unrelated.txt"
        private.write_text("PRIVATE_FILE_CONTENT")
        try:
            archive.symlink_to(private)
        except (OSError,NotImplementedError):
            self.skipTest("Symlink creation is unavailable on this host.")
        status,_,raw = self.request("?run="+self.run_id)
        self.assertEqual(status,400)
        self.assertNotIn(b"PRIVATE_FILE_CONTENT",raw)


if __name__=="__main__":
    unittest.main()
