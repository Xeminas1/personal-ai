"""Exercise durable answer provenance against real SQLite databases."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.database import Database


class ReplyMetadataTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "personal_ai.db"
        self.db = Database(self.path)
        self.addCleanup(lambda: self.db.close())
        self.user = self.db.create_user("Test")
        self.chat_id = self.db.create_chat(self.user["id"], "Replies")["id"]

    def test_legacy_database_migration_preserves_data_and_unknown_provenance(self):
        legacy_path = self.root / "legacy.db"
        connection = sqlite3.connect(legacy_path)
        # The pre-provenance schema, populated before the new Database opens it.
        connection.executescript("""
            PRAGMA foreign_keys = ON;
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                personality_notes TEXT NOT NULL DEFAULT '',
                communication_preferences TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
            );
            CREATE TABLE chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );
            CREATE TABLE messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT, chat_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
                content TEXT NOT NULL, created_at TEXT NOT NULL,
                FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE
            );
            CREATE TABLE memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                source_chat_id INTEGER, kind TEXT NOT NULL, content TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.7, active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL, last_used_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(source_chat_id) REFERENCES chats(id) ON DELETE SET NULL
            );
            INSERT INTO users(name, personality_notes, created_at)
                VALUES ('Legacy user', 'Preserve notes.', '2026-01-01');
            INSERT INTO chats(user_id, title, created_at, updated_at)
                VALUES (1, 'Legacy chat', '2026-01-01', '2026-01-02');
            INSERT INTO messages(chat_id, role, content, created_at)
                VALUES (1, 'user', 'Legacy question', '2026-01-01');
            INSERT INTO messages(chat_id, role, content, created_at)
                VALUES (1, 'assistant', 'Legacy answer', '2026-01-02');
            INSERT INTO memories(user_id, source_chat_id, kind, content, confidence, created_at)
                VALUES (1, 1, 'preference', 'Preserve memory.', 0.8, '2026-01-02');
        """)
        tables = ("users", "chats", "messages", "memories")
        before = {table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in tables}
        connection.close()

        migrated = Database(legacy_path)
        try:
            for table in tables:
                self.assertEqual([tuple(row) for row in migrated.conn.execute(f"SELECT * FROM {table}")], before[table])
            self.assertEqual(migrated.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(migrated.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(migrated.conn.execute("SELECT COUNT(*) FROM message_inference").fetchone()[0], 0)
            for message in migrated.get_recent_messages(1):
                self.assertIsNone(message["inference_model"])
                self.assertIsNone(message["inference_compute"])
        finally:
            migrated.close()

    def test_answer_metadata_survives_restart_without_labeling_other_messages(self):
        unlabeled_ids = [
            self.db.add_message(self.chat_id, "user", "Question"),
            self.db.add_message(self.chat_id, "assistant", "Older answer"),
            self.db.add_message(self.chat_id, "assistant", "Reply error"),
            self.db.add_assistant_message(self.chat_id, "Unknown provenance"),
        ]
        answers = {
            self.db.add_assistant_message(self.chat_id, "PC answer", model="qwen3:8b", compute_source="remote_worker"):
                ("qwen3:8b", "remote_worker"),
            self.db.add_assistant_message(self.chat_id, "Laptop answer", model="qwen3:1.7b", compute_source="local_host"):
                ("qwen3:1.7b", "local_host"),
            self.db.add_assistant_message(self.chat_id, "Template answer", compute_source="application"):
                (None, "application"),
        }
        self.db.close()
        self.db = Database(self.path)
        messages = {row["id"]: row for row in self.db.get_recent_messages(self.chat_id)}
        for message_id in unlabeled_ids:
            self.assertIsNone(messages[message_id]["inference_model"])
            self.assertIsNone(messages[message_id]["inference_compute"])
        for message_id, provenance in answers.items():
            self.assertEqual((messages[message_id]["inference_model"], messages[message_id]["inference_compute"]), provenance)
            self.assertEqual(messages[message_id]["role"], "assistant")

    def test_recent_history_order_limit_and_chat_scope_are_unchanged(self):
        expected = []
        for index in range(4):
            expected.append(self.db.add_message(self.chat_id, "user", f"Question {index}"))
            expected.append(self.db.add_assistant_message(self.chat_id, f"Answer {index}", model="qwen3:8b", compute_source="remote_worker"))
        other_chat = self.db.create_chat(self.user["id"], "Other")["id"]
        self.db.add_assistant_message(other_chat, "Other answer", model="qwen3:1.7b", compute_source="local_host")
        messages = self.db.get_recent_messages(self.chat_id, limit=3)
        self.assertEqual([row["id"] for row in messages], expected[-3:])
        self.assertEqual([row["role"] for row in messages], ["assistant", "user", "assistant"])
        self.assertTrue({"id", "chat_id", "role", "content", "created_at"}.issubset(messages[0].keys()))
        self.assertEqual(self.db.get_recent_messages(self.chat_id, limit=0), [])

    def test_invalid_metadata_is_rejected_before_any_answer_write(self):
        before_chat = tuple(self.db.get_chat(self.chat_id))
        for model, compute in (
            ("qwen3:8b", None), ("qwen3:8b", "application"),
            (None, "private-invalid-source"), (None, []),
            ("", "local_host"), (" ", "remote_worker"),
            ("private-label\nsecret", "remote_worker"),
            ("a" * 257, "remote_worker"), (12, "local_host"),
        ):
            with self.subTest(model=model, compute=compute):
                with self.assertRaises(ValueError) as raised:
                    self.db.add_assistant_message(self.chat_id, "Should not exist", model=model, compute_source=compute)
                self.assertNotIn("private", str(raised.exception))
                self.assertEqual(self.db.get_recent_messages(self.chat_id), [])
                self.assertEqual(tuple(self.db.get_chat(self.chat_id)), before_chat)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM message_inference").fetchone()[0], 0)

    def test_metadata_insert_failure_rolls_back_answer_and_chat_timestamp(self):
        before_chat = tuple(self.db.get_chat(self.chat_id))
        self.db.conn.executescript("""
            CREATE TRIGGER reject_metadata BEFORE INSERT ON message_inference
            BEGIN SELECT RAISE(ABORT, 'metadata unavailable'); END;
        """)
        with patch("app.database.now_iso", return_value="2099-01-01"):
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.add_assistant_message(self.chat_id, "Should roll back", model="qwen3:8b", compute_source="remote_worker")
        self.assertEqual(self.db.get_recent_messages(self.chat_id), [])
        self.assertEqual(tuple(self.db.get_chat(self.chat_id)), before_chat)
        self.db.conn.execute("DROP TRIGGER reject_metadata")
        self.db.conn.commit()
        self.db.add_assistant_message(self.chat_id, "Connection still usable", model="qwen3:8b", compute_source="remote_worker")
        self.assertEqual(len(self.db.get_recent_messages(self.chat_id)), 1)

    def test_message_and_chat_deletion_cascade_to_metadata(self):
        first = self.db.add_assistant_message(self.chat_id, "First", model="qwen3:8b", compute_source="remote_worker")
        second = self.db.add_assistant_message(self.chat_id, "Second", compute_source="application")
        self.db.conn.execute("DELETE FROM messages WHERE id = ?", (first,))
        self.db.conn.commit()
        self.assertEqual(self.db.conn.execute("SELECT message_id FROM message_inference").fetchone()[0], second)
        self.db.conn.execute("DELETE FROM chats WHERE id = ?", (self.chat_id,))
        self.db.conn.commit()
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM message_inference").fetchone()[0], 0)
        self.assertEqual(self.db.conn.execute("PRAGMA foreign_key_check").fetchall(), [])


if __name__ == "__main__":
    unittest.main()
