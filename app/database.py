from __future__ import annotations

import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, timeout=30.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA busy_timeout = 10000")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self._create_schema()

    def close(self) -> None:
        self.conn.close()

    def _create_schema(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                personality_notes TEXT NOT NULL DEFAULT '',
                communication_preferences TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS chats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('user','assistant','system')),
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS message_inference (
                message_id INTEGER PRIMARY KEY,
                model TEXT,
                compute_source TEXT NOT NULL CHECK(
                    compute_source IN ('local_host','remote_worker','application')
                ),
                FOREIGN KEY(message_id) REFERENCES messages(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                source_chat_id INTEGER,
                kind TEXT NOT NULL,
                content TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.7,
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(source_chat_id) REFERENCES chats(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                assistant_message_id INTEGER NOT NULL,
                score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 10),
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE,
                FOREIGN KEY(assistant_message_id) REFERENCES messages(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS chat_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                chat_id INTEGER NOT NULL,
                score INTEGER NOT NULL CHECK(score BETWEEN 0 AND 10),
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY(chat_id) REFERENCES chats(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_messages_chat
                ON messages(chat_id, id);
            CREATE INDEX IF NOT EXISTS idx_memories_user
                ON memories(user_id, active, id);
            CREATE INDEX IF NOT EXISTS idx_feedback_user
                ON feedback(user_id, id);
            """
        )
        self.conn.commit()

    def get_user(self):
        return self.conn.execute(
            "SELECT * FROM users ORDER BY id LIMIT 1"
        ).fetchone()

    def create_user(self, name: str):
        cur = self.conn.execute(
            """
            INSERT INTO users(name, created_at)
            VALUES (?, ?)
            """,
            (name.strip(), now_iso()),
        )
        self.conn.commit()
        return self.conn.execute(
            "SELECT * FROM users WHERE id = ?", (cur.lastrowid,)
        ).fetchone()

    def update_user_style(self, user_id: int, style: str) -> None:
        self.conn.execute(
            """
            UPDATE users
            SET communication_preferences = ?
            WHERE id = ?
            """,
            (style.strip(), user_id),
        )
        self.conn.commit()

    def append_personality_note(self, user_id: int, note: str) -> None:
        row = self.conn.execute(
            "SELECT personality_notes FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        existing = row["personality_notes"].strip() if row else ""
        if note.lower() in existing.lower():
            return
        combined = (existing + "\n" + note.strip()).strip()
        self.conn.execute(
            "UPDATE users SET personality_notes = ? WHERE id = ?",
            (combined, user_id),
        )
        self.conn.commit()

    def create_chat(self, user_id: int, title: str):
        ts = now_iso()
        cur = self.conn.execute(
            """
            INSERT INTO chats(user_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, title.strip() or "Untitled", ts, ts),
        )
        self.conn.commit()
        return self.get_chat(cur.lastrowid)

    def get_chat(self, chat_id: int):
        return self.conn.execute(
            "SELECT * FROM chats WHERE id = ?", (chat_id,)
        ).fetchone()

    def rename_chat(self, chat_id: int, title: str) -> None:
        clean = " ".join(title.strip().split())[:80] or "Untitled"
        self.conn.execute(
            "UPDATE chats SET title = ?, updated_at = ? WHERE id = ?",
            (clean, now_iso(), chat_id),
        )
        self.conn.commit()

    def list_chats(self, user_id: int):
        return self.conn.execute(
            """
            SELECT * FROM chats
            WHERE user_id = ?
            ORDER BY updated_at DESC, id DESC
            """,
            (user_id,),
        ).fetchall()

    def add_message(self, chat_id: int, role: str, content: str) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO messages(chat_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (chat_id, role, content, now_iso()),
        )
        self.conn.execute(
            "UPDATE chats SET updated_at = ? WHERE id = ?",
            (now_iso(), chat_id),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def add_assistant_message(
        self,
        chat_id: int,
        content: str,
        *,
        model: str | None = None,
        compute_source: str | None = None,
    ) -> int:
        """Save a completed answer and optional provenance atomically.

        Omitted provenance stays unknown. Invalid labels are rejected before
        any write, without including their values in the error message.
        Application-generated answers have no inference model.
        """
        if compute_source is not None and compute_source not in (
            "local_host", "remote_worker", "application"
        ):
            raise ValueError("Invalid answer compute source.")
        if model is not None:
            if not isinstance(model, str):
                raise ValueError("Invalid answer model label.")
            model = model.strip()
            if not model or len(model) > 256 or not model.isprintable():
                raise ValueError("Invalid answer model label.")
            if compute_source is None or compute_source == "application":
                raise ValueError("Answer model requires an inference compute source.")

        timestamp = now_iso()
        with self.conn:
            cur = self.conn.execute(
                """
                INSERT INTO messages(chat_id, role, content, created_at)
                VALUES (?, 'assistant', ?, ?)
                """,
                (chat_id, content, timestamp),
            )
            message_id = int(cur.lastrowid)
            if compute_source is not None:
                self.conn.execute(
                    """
                    INSERT INTO message_inference(message_id, model, compute_source)
                    VALUES (?, ?, ?)
                    """,
                    (message_id, model, compute_source),
                )
            self.conn.execute(
                "UPDATE chats SET updated_at = ? WHERE id = ?",
                (timestamp, chat_id),
            )
        return message_id

    def get_recent_messages(self, chat_id: int, limit: int = 30):
        rows = self.conn.execute(
            """
            SELECT recent.*, inference.model AS inference_model,
                inference.compute_source AS inference_compute
            FROM (
                SELECT * FROM messages
                WHERE chat_id = ?
                ORDER BY id DESC
                LIMIT ?
            ) AS recent
            LEFT JOIN message_inference AS inference
                ON inference.message_id = recent.id
            ORDER BY recent.id ASC
            """,
            (chat_id, limit),
        ).fetchall()
        return rows

    @staticmethod
    def _normalise(text: str) -> str:
        return re.sub(r"\s+", " ", text.strip().lower())

    def add_memory(
        self,
        user_id: int,
        source_chat_id: int | None,
        kind: str,
        content: str,
        confidence: float = 0.7,
    ) -> int | None:
        norm = self._normalise(content)
        if not norm:
            return None

        existing = self.conn.execute(
            """
            SELECT id, content FROM memories
            WHERE user_id = ? AND active = 1
            ORDER BY id DESC
            LIMIT 300
            """,
            (user_id,),
        ).fetchall()

        for row in existing:
            if self._normalise(row["content"]) == norm:
                return int(row["id"])

        cur = self.conn.execute(
            """
            INSERT INTO memories(
                user_id, source_chat_id, kind, content,
                confidence, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
                source_chat_id,
                kind[:50],
                content.strip(),
                max(0.0, min(1.0, float(confidence))),
                now_iso(),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def list_memories(self, user_id: int, limit: int = 100):
        return self.conn.execute(
            """
            SELECT * FROM memories
            WHERE user_id = ? AND active = 1
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()

    def deactivate_memory(self, user_id: int, memory_id: int) -> bool:
        cur = self.conn.execute(
            """
            UPDATE memories
            SET active = 0
            WHERE user_id = ? AND id = ?
            """,
            (user_id, memory_id),
        )
        self.conn.commit()
        return cur.rowcount > 0

    def repair_invalid_memory_confidence(self, user_id: int) -> int:
        cur = self.conn.execute(
            """
            UPDATE memories
            SET confidence = 1.0
            WHERE user_id = ?
              AND active = 1
              AND kind = 'preference'
              AND confidence <= 0.0
            """,
            (user_id,),
        )
        self.conn.commit()
        return cur.rowcount

    def relevant_memories(
        self,
        user_id: int,
        query: str,
        limit: int = 25,
    ):
        memories = self.conn.execute(
            """
            SELECT * FROM memories
            WHERE user_id = ? AND active = 1
            ORDER BY id DESC
            LIMIT 300
            """,
            (user_id,),
        ).fetchall()

        q_tokens = {
            t for t in re.findall(r"[a-zA-Z0-9_'-]{3,}", query.lower())
        }

        scored = []
        for recency_index, row in enumerate(memories):
            content_tokens = {
                t for t in re.findall(
                    r"[a-zA-Z0-9_'-]{3,}", row["content"].lower()
                )
            }
            overlap = len(q_tokens & content_tokens)
            kind_bonus = 1.0 if row["kind"] in {
                "preference", "profile", "project", "successful_strategy"
            } else 0.0
            recency_bonus = max(0.0, 1.0 - recency_index / 300.0) * 0.25
            score = overlap * 2.0 + kind_bonus + recency_bonus

            if row["kind"] in {"preference", "profile"} and row["confidence"] >= 0.85:
                score += 2.0

            scored.append((score, row))

        scored.sort(key=lambda x: x[0], reverse=True)
        selected = [row for score, row in scored[:limit] if score > 0]

        if len(selected) < min(5, limit):
            selected_ids = {r["id"] for r in selected}
            for row in memories:
                if row["id"] not in selected_ids:
                    selected.append(row)
                    selected_ids.add(row["id"])
                if len(selected) >= min(5, limit):
                    break

        if selected:
            ids = [r["id"] for r in selected]
            placeholders = ",".join("?" for _ in ids)
            self.conn.execute(
                f"""
                UPDATE memories
                SET last_used_at = ?
                WHERE id IN ({placeholders})
                """,
                [now_iso(), *ids],
            )
            self.conn.commit()

        return selected[:limit]

    def add_feedback(
        self,
        user_id: int,
        chat_id: int,
        assistant_message_id: int,
        score: int,
        note: str = "",
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO feedback(
                user_id, chat_id, assistant_message_id,
                score, note, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user_id, chat_id, assistant_message_id,
                int(score), note.strip(), now_iso()
            ),
        )
        self.conn.commit()

    def recent_feedback(self, user_id: int, limit: int = 20):
        return self.conn.execute(
            """
            SELECT f.*, m.content AS assistant_content
            FROM feedback f
            JOIN messages m ON m.id = f.assistant_message_id
            WHERE f.user_id = ?
            ORDER BY f.id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()

    def add_chat_feedback(
        self,
        user_id: int,
        chat_id: int,
        score: int,
        note: str = "",
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO chat_feedback(
                user_id, chat_id, score, note, created_at
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, chat_id, int(score), note.strip(), now_iso()),
        )
        self.conn.commit()

    def recent_chat_feedback(self, user_id: int, limit: int = 20):
        return self.conn.execute(
            """
            SELECT cf.*, c.title AS chat_title
            FROM chat_feedback cf
            JOIN chats c ON c.id = cf.chat_id
            WHERE cf.user_id = ?
            ORDER BY cf.id DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()

    def chat_has_messages(self, chat_id: int) -> bool:
        row = self.conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM messages
            WHERE chat_id = ?
            """,
            (chat_id,),
        ).fetchone()
        return bool(row and row["count"] > 0)
