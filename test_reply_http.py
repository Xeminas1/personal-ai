"""Current compute availability must not relabel a saved reply's provenance."""
import json
import logging
import shutil
import subprocess
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import patch

from app import mobile_server
from app.database import Database


class ReplyHTTPTests(unittest.TestCase):
    def test_available_worker_and_saved_host_answer_remain_distinct(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary)
            path = data / "personal_ai.db"
            db = Database(path)
            user = db.create_user("Test")
            chat_id = db.create_chat(user["id"], "Test")["id"]
            legacy = db.add_message(chat_id, "assistant", "Legacy answer")
            host = db.add_assistant_message(chat_id, "Fallback answer", model="qwen3:1.7b", compute_source="local_host")
            app = db.add_assistant_message(chat_id, "Application snapshot", compute_source="application")
            db.close()

            class Backend:
                def __init__(self):
                    self.db = Database(path)
                    self.user = self.db.get_user()

                def get_chat(self, identifier):
                    return self.db.get_chat(identifier)

                def messages(self, identifier):
                    return self.db.get_recent_messages(identifier)

                def refresh_runtime_model(self):
                    return {"model": "qwen3:8b", "compute": "remote_worker", "worker_available": True}

                def close(self):
                    self.db.close()

            server = mobile_server.XemAiMobileServer(("127.0.0.1", 0), mobile_server.XemAiMobileHandler)
            server.xemai_logger = logging.getLogger("reply-http")
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            base = f"http://127.0.0.1:{server.server_port}"

            def read(relative):
                with opener.open(base + relative, timeout=3) as response:
                    return json.load(response)

            with patch.object(mobile_server, "DATA_DIR", data), \
                 patch.object(mobile_server.XemAiMobileHandler, "_backend", side_effect=Backend):
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                try:
                    availability = read("/api/compute")
                    self.assertEqual(availability["model"], "qwen3:8b")
                    self.assertEqual(availability["compute_source"], "remote_worker")
                    # A fresh server/database connection still knows the actual answer route.
                    messages = {m["id"]: m for m in read(f"/api/chats/{chat_id}/messages")["messages"]}
                    self.assertIsNone(messages[legacy]["inference_compute"])
                    self.assertEqual(messages[host]["inference_compute"], "local_host")
                    self.assertEqual(messages[host]["inference_model"], "qwen3:1.7b")
                    self.assertEqual(messages[app]["inference_compute"], "application")
                    self.assertIsNone(messages[app]["inference_model"])
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=3)

    @unittest.skipUnless(shutil.which("node"), "Node unavailable for optional UI verification")
    def test_phone_labels_legacy_application_and_fallback_answers_safely(self):
        script = r'''
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const code = fs.readFileSync('mobile/app.js', 'utf8');
const rendered = [];
const context = {
  document: {createElement: () => ({innerHTML: '', querySelector: () => null})},
  state: {bootstrap: {assistant_name: 'XemAi', user: {name: 'Test'}}},
  els: {messages: {appendChild: node => rendered.push(node)}},
  REPLY_ERROR_PREFIX: 'reply-error-prefix',
  renderBody: () => 'body',
  formatMessageTime: () => '12:00',
  retryLastMessage: () => {},
};
vm.createContext(context);
for (const name of ['escapeHtml', 'replyInferenceLabel', 'appendMessage']) {
  const fn = code.match(new RegExp('function ' + name + '\\([^]*?\\n\\}'));
  assert(fn, name);
  vm.runInContext(fn[0], context);
}
context.appendMessage('assistant', 'reply', null, null, {inference_model:'qwen3:1.7b', inference_compute:'local_host'});
assert(rendered.pop().innerHTML.includes('Answered by Host · qwen3:1.7b'));
context.appendMessage('assistant', 'reply', null, null, {inference_model:'qwen3:8b', inference_compute:'remote_worker'});
assert(rendered.pop().innerHTML.includes('Answered by Worker · qwen3:8b'));
context.appendMessage('assistant', 'reply', null, null, null);
assert(!rendered.pop().innerHTML.includes('message-inference'));
context.appendMessage('assistant', 'reply', null, null, {inference_compute:'application'});
assert(rendered.pop().innerHTML.includes('XemAi app reply'));
context.appendMessage('assistant', 'reply', null, null, {inference_model:'<img src=x onerror=alert(1)>', inference_compute:'local_host'});
const html = rendered.pop().innerHTML;
assert(!html.includes('<img'));
assert(html.includes('&lt;img'));
'''
        subprocess.run([shutil.which("node"), "-e", script], cwd=Path(__file__).resolve().parent, check=True, capture_output=True, text=True)


if __name__ == "__main__":
    unittest.main()
