"""Exercise durable specialist contributions with temporary SQLite data."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from app.database import Database


class SpecialistMetadataTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "personal_ai.db"
        self.db = Database(self.path)
        self.addCleanup(lambda: self.db.close())
        self.user_id = self.db.create_user("Test")["id"]
        self.chat_id = self.db.create_chat(self.user_id, "Specialist replies")["id"]

    def legacy_database(self):
        path = self.root / "legacy.db"
        connection = sqlite3.connect(path)
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
            CREATE TABLE message_inference (
                message_id INTEGER PRIMARY KEY, model TEXT,
                compute_source TEXT NOT NULL CHECK(compute_source IN ('local_host','remote_worker','application')),
                FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE
            );
            CREATE TABLE memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
                source_chat_id INTEGER, kind TEXT NOT NULL, content TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.7, active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL, last_used_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(source_chat_id) REFERENCES chats(id) ON DELETE SET NULL
            );
            INSERT INTO users(name, personality_notes, communication_preferences, created_at)
                VALUES ('Legacy test', 'Keep notes.', 'Keep preferences.', '2026-01-01');
            INSERT INTO chats(user_id, title, created_at, updated_at)
                VALUES (1, 'Keep chat', '2026-01-01', '2026-01-02');
            INSERT INTO messages(chat_id, role, content, created_at)
                VALUES (1, 'user', 'Keep question.', '2026-01-01');
            INSERT INTO messages(chat_id, role, content, created_at)
                VALUES (1, 'assistant', 'Keep answer.', '2026-01-02');
            INSERT INTO message_inference(message_id, model, compute_source)
                VALUES (2, 'qwen3:8b', 'remote_worker');
            INSERT INTO memories(user_id, source_chat_id, kind, content, confidence, created_at)
                VALUES (1, 1, 'preference', 'Keep memory.', 0.8, '2026-01-02');
        """)
        tables = ("users", "chats", "messages", "message_inference", "memories")
        columns = {
            table: [row[1] for row in connection.execute(f"PRAGMA table_info({table})")]
            for table in tables
        }
        before = {table: connection.execute(f"SELECT * FROM {table}").fetchall() for table in tables}
        connection.close()
        return path, columns, before

    def test_legacy_migration_preserves_existing_columns_and_inference(self):
        path, columns, before = self.legacy_database()
        migrated = Database(path)
        try:
            for table, names in columns.items():
                selection = ", ".join(names)
                self.assertEqual([tuple(row) for row in migrated.conn.execute(f"SELECT {selection} FROM {table}")], before[table])
            schema = {row["name"]: row for row in migrated.conn.execute("PRAGMA table_info(messages)")}
            self.assertEqual(schema["specialist_roles"]["type"], "TEXT")
            self.assertEqual(schema["specialist_roles"]["notnull"], 0)
            self.assertIsNone(schema["specialist_roles"]["dflt_value"])
            self.assertEqual([row[0] for row in migrated.conn.execute("SELECT specialist_roles FROM messages")], [None, None])
            messages = migrated.get_recent_messages(1)
            self.assertTrue(all(isinstance(row, dict) and row["specialist_roles"] == [] for row in messages))
            self.assertEqual((messages[-1]["inference_model"], messages[-1]["inference_compute"]), ("qwen3:8b", "remote_worker"))
            self.assertEqual(migrated.conn.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(migrated.conn.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            migrated.close()

    def test_concurrent_legacy_open_migrates_once(self):
        path, _, _ = self.legacy_database()
        def open_and_read(_):
            database = Database(path)
            try:
                return database.get_recent_messages(1)[-1]["specialist_roles"]
            finally:
                database.close()
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(list(pool.map(open_and_read, range(4))), [[], [], [], []])
        connection = sqlite3.connect(path)
        try:
            self.assertEqual([row[1] for row in connection.execute("PRAGMA table_info(messages)")].count("specialist_roles"), 1)
        finally:
            connection.close()

    def test_roles_survive_reopen_without_changing_answer_model_ownership(self):
        supported = self.db.add_assistant_message(
            self.chat_id, "Main PC answer", model="qwen3:8b", compute_source="remote_worker",
            specialist_roles=["research", "reviewer"],
        )
        local = self.db.add_assistant_message(
            self.chat_id, "Main laptop answer", model="qwen3:1.7b", compute_source="local_host",
            specialist_roles=("skyrim",),
        )
        legacy = self.db.add_assistant_message(self.chat_id, "No specialist contribution")
        empty = self.db.add_assistant_message(self.chat_id, "Explicitly empty", specialist_roles=[])
        raw = {row["id"]: row["specialist_roles"] for row in self.db.conn.execute("SELECT id, specialist_roles FROM messages")}
        self.assertEqual(raw[supported], '["research","reviewer"]')
        self.assertEqual(raw[local], '["skyrim"]')
        self.assertIsNone(raw[legacy])
        self.assertEqual(raw[empty], "[]")
        self.db.close()
        self.db = Database(self.path)
        messages = {row["id"]: row for row in self.db.get_recent_messages(self.chat_id)}
        self.assertEqual(messages[supported]["specialist_roles"], ["research", "reviewer"])
        self.assertEqual((messages[supported]["inference_model"], messages[supported]["inference_compute"]), ("qwen3:8b", "remote_worker"))
        self.assertEqual(messages[local]["specialist_roles"], ["skyrim"])
        self.assertEqual((messages[local]["inference_model"], messages[local]["inference_compute"]), ("qwen3:1.7b", "local_host"))
        for message_id in (legacy, empty):
            self.assertEqual(messages[message_id]["specialist_roles"], [])
            self.assertIsNone(messages[message_id]["inference_model"])
            self.assertIsNone(messages[message_id]["inference_compute"])
        # The API can serialize these rows directly without exposing internal notes.
        self.assertEqual(json.loads(json.dumps(messages[supported]))["specialist_roles"], ["research", "reviewer"])

    def test_invalid_roles_rejected_before_any_message_or_timestamp_write(self):
        before_chat = tuple(self.db.get_chat(self.chat_id))
        for roles in (
            "research", {"research"}, {"role": "research"}, 1, True,
            ["Research"], ["private-invalid-role"], ["research", "research"],
            ["research", "skyrim", "reviewer"], [None], [True], [["research"]],
            ["research", "private-invalid-role"], ["reviewer\nprivate"],
        ):
            with self.subTest(roles=roles):
                with self.assertRaises(ValueError) as raised:
                    self.db.add_assistant_message(
                        self.chat_id, "Should not be saved", model="qwen3:8b",
                        compute_source="remote_worker", specialist_roles=roles,
                    )
                self.assertNotIn("private", str(raised.exception))
                self.assertEqual(self.db.get_recent_messages(self.chat_id), [])
                self.assertEqual(tuple(self.db.get_chat(self.chat_id)), before_chat)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM message_inference").fetchone()[0], 0)

    def test_corrupt_or_unknown_stored_metadata_is_hidden(self):
        invalid = (
            None, "", "not JSON", '"research"', "null", "{}", "1",
            '["Research"]', '["research","unknown"]', '["reviewer","reviewer"]',
            '["research","skyrim","reviewer"]', "[true]", '["<img src=x onerror=alert(1)>"]',
            '["research"]' + " " * 257,
        )
        expected = {}
        for raw in invalid:
            identifier = self.db.add_assistant_message(self.chat_id, "Stored answer")
            self.db.conn.execute("UPDATE messages SET specialist_roles = ? WHERE id = ?", (raw, identifier))
            expected[identifier] = []
        valid = self.db.add_assistant_message(self.chat_id, "Supported answer", specialist_roles=["skyrim", "reviewer"])
        expected[valid] = ["skyrim", "reviewer"]
        self.db.conn.commit()
        self.assertEqual({row["id"]: row["specialist_roles"] for row in self.db.get_recent_messages(self.chat_id)}, expected)

    def test_inference_failure_rolls_back_specialist_answer_and_timestamp(self):
        before_chat = tuple(self.db.get_chat(self.chat_id))
        self.db.conn.executescript("""
            CREATE TRIGGER reject_inference BEFORE INSERT ON message_inference
            BEGIN SELECT RAISE(ABORT, 'inference unavailable'); END;
        """)
        with patch("app.database.now_iso", return_value="2099-01-01"):
            with self.assertRaises(sqlite3.IntegrityError):
                self.db.add_assistant_message(
                    self.chat_id, "Should roll back", model="qwen3:8b",
                    compute_source="remote_worker", specialist_roles=["research", "reviewer"],
                )
        self.assertEqual(self.db.get_recent_messages(self.chat_id), [])
        self.assertEqual(tuple(self.db.get_chat(self.chat_id)), before_chat)

    def test_deletion_removes_metadata_and_keeps_other_chat_and_memory(self):
        message = self.db.add_assistant_message(
            self.chat_id, "Delete this answer", model="qwen3:8b",
            compute_source="remote_worker", specialist_roles=["research", "reviewer"],
        )
        self.db.add_feedback(self.user_id, self.chat_id, message, 7, "Keep no deleted feedback")
        memory = self.db.add_memory(self.user_id, self.chat_id, "preference", "Keep test memory")
        other_chat = self.db.create_chat(self.user_id, "Keep other chat")["id"]
        keep = self.db.add_assistant_message(other_chat, "Keep answer", specialist_roles=["skyrim"])
        self.assertTrue(self.db.delete_chat(self.user_id, self.chat_id))
        self.assertEqual(self.db.get_recent_messages(self.chat_id), [])
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM message_inference").fetchone()[0], 0)
        self.assertEqual(self.db.conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0], 0)
        self.assertEqual(self.db.get_recent_messages(other_chat)[0]["id"], keep)
        self.assertEqual(self.db.get_recent_messages(other_chat)[0]["specialist_roles"], ["skyrim"])
        saved = self.db.conn.execute("SELECT * FROM memories WHERE id = ?", (memory,)).fetchone()
        self.assertEqual(saved["content"], "Keep test memory")
        self.assertIsNone(saved["source_chat_id"])
        self.assertEqual(self.db.conn.execute("PRAGMA foreign_key_check").fetchall(), [])


if __name__ == "__main__":
    unittest.main()
