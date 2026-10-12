"""Per-message 0–10 feedback, ownership and non-sycophantic aggregate prompts."""
from __future__ import annotations
import json
import logging
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

from app import mobile_server
from app.database import Database
from app.prompts import build_system_prompt


class RatingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dbfile = Path(self.temp.name) / "personal_ai.db"
        db = Database(self.dbfile)
        self.owner = db.create_user("Tester")
        self.chat = db.create_chat(self.owner["id"], "Rated chat")["id"]
        self.other = db.create_chat(self.owner["id"], "Unrelated")["id"]
        self.worker = db.add_assistant_message(
            self.chat, "Worker model answer.",
            model="qwen3.5:9b-q8_0", compute_source="remote_worker",
        )
        self.app = db.add_assistant_message(
            self.chat, "App fallback.", compute_source="application",
        )
        self.user_message = db.add_message(self.chat, "user", "User words")
        self.other_answer = db.add_assistant_message(
            self.other, "Other chat answer.",
            model="qwen3:8b", compute_source="local_host",
        )
        db.close()

    def test_rating_zero_ten_edits_and_model_only_patterns(self):
        db = Database(self.dbfile)
        try:
            db.rate_assistant_message(self.owner["id"], self.chat, self.worker, 0, "understanding", "Missed the question.")
            first = next(x for x in db.get_recent_messages(self.chat) if x["id"] == self.worker)
            self.assertEqual(first["rating_score"], 0)
            self.assertEqual(first["rating_aspect"], "understanding")
            db.rate_assistant_message(self.owner["id"], self.chat, self.worker, 10, "understanding", "Much better.")
            db.rate_assistant_message(self.owner["id"], self.chat, self.app, 10, "accuracy", "Needs verification")
            updated = next(x for x in db.get_recent_messages(self.chat) if x["id"] == self.worker)
            self.assertEqual(updated["rating_score"], 10)
            self.assertEqual(db.conn.execute(
                "SELECT count(*) FROM feedback WHERE assistant_message_id=?",
                (self.worker,),
            ).fetchone()[0], 1)
            self.assertEqual(db.rating_patterns(self.owner["id"]), [{
                "aspect": "understanding", "count": 1,
                "average": 10.0, "positive": 1, "needs_work": 0,
            }])
            context = build_system_prompt(self.owner, [], feedback_rows=[])
            self.assertIn("A high score does not prove", context)
        finally:
            db.close()

    def test_invalid_and_cross_chat_ids_are_rejected(self):
        db = Database(self.dbfile)
        try:
            for m,score,aspect,note in (
                (self.user_message, 10, "overall", ""),
                (self.other_answer, 10, "overall", ""),
                (99999, 10, "overall", ""),
                (self.worker, True, "overall", ""),
                (self.worker, 11, "overall", ""),
                (self.worker, -1, "overall", ""),
                (self.worker, 7.5, "overall", ""),
                (self.worker, 6, "custom", ""),
                (self.worker, 6, "overall", "a"*351),
            ):
                with self.subTest(message=m, score=score, aspect=aspect):
                    with self.assertRaises(ValueError):
                        db.rate_assistant_message(self.owner["id"], self.chat, m, score, aspect, note)
            self.assertEqual(db.conn.execute("SELECT count(*) FROM feedback").fetchone()[0], 0)
        finally:
            db.close()

    def test_http_saved_exact_message_and_validated_type(self):
        path = self.dbfile
        class Backend:
            def __init__(self):
                self.db = Database(path)
                self.user = self.db.get_user()
            def get_chat(self, i):
                return self.db.get_chat(i)
            def messages(self, i):
                return self.db.get_recent_messages(i)
            def rate_message(self, chat, mid, score, aspect, note):
                self.db.rate_assistant_message(self.user["id"], chat, mid, score, aspect, note)
                return {"message_id": mid, "score": score, "aspect": aspect}
            def close(self):
                self.db.close()

        server = mobile_server.XemAiMobileServer(("127.0.0.1", 0), mobile_server.XemAiMobileHandler)
        server.xemai_logger = logging.getLogger("message-rating-tests")
        op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        base = f"http://127.0.0.1:{server.server_port}"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        with patch.object(mobile_server.XemAiMobileHandler, "_backend", side_effect=Backend):
            try:
                def post(body, chat_id=None):
                    request = urllib.request.Request(
                        base + f"/api/chats/{chat_id or self.chat}/ratings",
                        data=json.dumps(body).encode(), method="POST",
                        headers={"Content-Type":"application/json"},
                    )
                    try:
                        with op.open(request, timeout=4) as response:
                            return response.status, json.load(response)
                    except urllib.error.HTTPError as e:
                        return e.code, json.load(e)
                success = post({
                    "message_id": self.worker, "score": 9,
                    "aspect": "usefulness", "note": "Helped with my project.",
                })
                self.assertEqual(success[0], 200)
                self.assertEqual(success[1]["score"], 9)
                with op.open(base + f"/api/chats/{self.chat}/messages") as response:
                    rated = {m["id"]:m for m in json.load(response)["messages"]}
                self.assertEqual(rated[self.worker]["rating_score"], 9)
                self.assertEqual(rated[self.worker]["rating_aspect"], "usefulness")
                self.assertEqual(post({"message_id": self.worker, "score": True})[0], 400)
                self.assertEqual(post({"message_id": self.other_answer, "score": 10})[0], 400)
                self.assertEqual(post({"message_id": self.user_message, "score": 10})[0], 400)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=4)


if __name__ == "__main__":
    unittest.main()
