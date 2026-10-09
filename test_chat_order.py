"""Check chat recency with real SQLite writes within the same second."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from app.database import Database


class ChatOrderTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.db = Database(Path(temporary.name) / "chats.db")
        self.addCleanup(self.db.close)
        self.user_id = self.db.create_user("Test")["id"]

    def assert_older_chat_activity_moves_first(self, operation):
        with patch("app.database.datetime") as clock:
            clock.now.return_value = datetime(2026, 1, 1, 12, 0, 0, 100000, timezone.utc)
            older = self.db.create_chat(self.user_id, "Older")
            clock.now.return_value = datetime(2026, 1, 1, 12, 0, 0, 200000, timezone.utc)
            newer = self.db.create_chat(self.user_id, "Newer")
            self.assertEqual([chat["id"] for chat in self.db.list_chats(self.user_id)],
                             [newer["id"], older["id"]])
            clock.now.return_value = datetime(2026, 1, 1, 12, 0, 0, 300000, timezone.utc)
            operation(older["id"])

        chats = self.db.list_chats(self.user_id)
        self.assertEqual([chat["id"] for chat in chats], [older["id"], newer["id"]])
        self.assertNotEqual(chats[0]["updated_at"], chats[1]["updated_at"])
        self.assertIn(".300", chats[0]["updated_at"])

    def test_new_user_message_moves_older_chat_first_within_one_second(self):
        self.assert_older_chat_activity_moves_first(
            lambda chat_id: self.db.add_message(chat_id, "user", "Newest activity"))

    def test_completed_assistant_reply_moves_older_chat_first_within_one_second(self):
        self.assert_older_chat_activity_moves_first(
            lambda chat_id: self.db.add_assistant_message(
                chat_id, "Newest reply", model="qwen3:8b", compute_source="remote_worker"))

    def test_rename_moves_older_chat_first_within_one_second(self):
        self.assert_older_chat_activity_moves_first(
            lambda chat_id: self.db.rename_chat(chat_id, "Updated title"))

    def test_exact_timestamp_ties_are_deterministic_and_user_scoped(self):
        with patch("app.database.now_iso", return_value="2026-01-01T12:00:00+00:00"):
            older = self.db.create_chat(self.user_id, "Older")
            newer = self.db.create_chat(self.user_id, "Newer")
            foreign_user = self.db.create_user("Other")["id"]
            self.db.create_chat(foreign_user, "Other user's chat")
        self.assertEqual([chat["id"] for chat in self.db.list_chats(self.user_id)],
                         [newer["id"], older["id"]])


if __name__ == "__main__":
    unittest.main()
