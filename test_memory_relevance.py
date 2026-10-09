"""Memory context must help the current question without unrelated fact padding."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.database import Database


class MemoryRelevanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.db = Database(Path(temporary.name) / "personal_ai.db")
        self.addCleanup(self.db.close)
        self.user_id = self.db.create_user("Test")["id"]
        self.chat_id = self.db.create_chat(self.user_id, "Memories")["id"]

    def remember(self, content, *, kind="project", confidence=0.95, user_id=None, chat_id=None):
        return self.db.add_memory(
            self.user_id if user_id is None else user_id,
            self.chat_id if chat_id is None else chat_id,
            kind, content, confidence,
        )

    def used(self, memory_id):
        return self.db.conn.execute(
            "SELECT last_used_at FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()[0]

    def test_older_topical_memory_beats_newer_unrelated_beliefs(self):
        topic = self.remember("The Skyrim scope sway project needs a steady aiming transition.")
        noisy = [self.remember(f"User believes the distant nebula contains planet {index}.", kind="user_belief") for index in range(40)]
        result = self.db.relevant_memories(self.user_id, "How should I improve Skyrim scope sway?", limit=3)
        self.assertEqual([row["id"] for row in result], [topic])
        self.assertIsNotNone(self.used(topic))
        self.assertTrue(all(self.used(memory_id) is None for memory_id in noisy))

    def test_stopwords_do_not_make_unrelated_fact_kinds_relevant(self):
        memories = [
            self.remember("The user's project is in a distant nebula."),
            self.remember("The user believes that the nebula is nearby.", kind="user_belief"),
            self.remember("The user has a telescope in the attic.", kind="profile"),
            self.remember("The user should use telescope alignment for this project.", kind="successful_strategy"),
        ]
        result = self.db.relevant_memories(self.user_id, "What is the answer to my question about the project?")
        self.assertEqual(result, [])
        self.assertTrue(all(self.used(memory_id) is None for memory_id in memories))
        self.assertEqual(len(self.db.list_memories(self.user_id)), len(memories))

    def test_global_preferences_are_capped_after_topical_context(self):
        topic = self.remember("Pirate ship history includes Queen Anne's Revenge.")
        globals_ = [self.remember(f"Prefer concise explanations with style marker {index}.", kind="preference", confidence=1.0) for index in range(8)]
        low_confidence = self.remember("Perhaps prefer whimsical explanations.", kind="preference", confidence=0.84)
        result = self.db.relevant_memories(self.user_id, "Which pirate ship did Blackbeard command?", limit=25)
        self.assertEqual([row["id"] for row in result], [topic, *reversed(globals_[-5:])])
        self.assertIsNone(self.used(low_confidence))
        self.assertTrue(all(self.used(memory_id) is None for memory_id in globals_[:-5]))
        # High-confidence defaults must not push the topical answer out of a
        # small context window, even when those defaults were saved later.
        self.assertEqual([row["id"] for row in self.db.relevant_memories(self.user_id, "pirate ship", limit=1)], [topic])

    def test_current_user_active_scope_and_last_used_follow_returned_limit(self):
        older = self.remember("Skyrim scope tuning uses a steady transition.")
        newer = self.remember("Skyrim scope tuning uses a smooth transition.")
        inactive = self.remember("Skyrim scope tuning uses an obsolete transition.")
        self.db.deactivate_memory(self.user_id, inactive)
        other_user = self.db.create_user("Other")["id"]
        other_chat = self.db.create_chat(other_user, "Other")["id"]
        foreign = self.remember("Skyrim scope tuning belongs to another user.", user_id=other_user, chat_id=other_chat)
        for limit in (0, -1, -100):
            self.assertEqual(self.db.relevant_memories(self.user_id, "Skyrim scope", limit=limit), [])
        self.assertTrue(all(self.used(memory_id) is None for memory_id in (older, newer, inactive, foreign)))
        one = self.db.relevant_memories(self.user_id, "Skyrim scope", limit=1)
        self.assertEqual([row["id"] for row in one], [newer])
        self.assertIsNotNone(self.used(newer))
        self.assertTrue(all(self.used(memory_id) is None for memory_id in (older, inactive, foreign)))
        two = self.db.relevant_memories(self.user_id, "Skyrim scope", limit=2)
        self.assertEqual([row["id"] for row in two], [newer, older])

    def test_named_topic_tokens_and_possessives_remain_useful(self):
        matching = self.remember("Jack’s Black Pearl appears in the pirate films.", kind="user_belief", confidence=0.6)
        unrelated = self.remember("Space telescope measurements concern a distant nebula.", kind="profile")
        result = self.db.relevant_memories(self.user_id, "What do you remember about Jack's Black Pearl?")
        self.assertEqual([row["id"] for row in result], [matching])
        self.assertEqual(result[0]["kind"], "user_belief")
        self.assertEqual(result[0]["confidence"], 0.6)
        self.assertIsNone(self.used(unrelated))

    def test_explicit_personal_recall_includes_own_context_with_limit_and_usage(self):
        project = self.remember("Build a telescope mount.")
        profile = self.remember("I work as an illustrator.", kind="profile")
        belief = self.remember("I believe afternoon sessions are more productive.", kind="user_belief")
        inactive = self.remember("I used to work in a bakery.", kind="profile")
        self.db.deactivate_memory(self.user_id, inactive)
        other_user = self.db.create_user("Other")["id"]
        other_chat = self.db.create_chat(other_user, "Other")["id"]
        foreign = self.remember("Another user's profile.", kind="profile", user_id=other_user, chat_id=other_chat)
        for limit in (0, -1):
            self.assertEqual(self.db.relevant_memories(self.user_id, "What do you remember about me?", limit=limit), [])
        result = self.db.relevant_memories(self.user_id, "What do you remember about me?", limit=2)
        self.assertEqual([row["id"] for row in result], [belief, profile])
        self.assertIsNotNone(self.used(belief))
        self.assertIsNotNone(self.used(profile))
        self.assertTrue(all(self.used(memory_id) is None for memory_id in (project, inactive, foreign)))
        result = self.db.relevant_memories(self.user_id, "Please list my memories.", limit=10)
        self.assertEqual([row["id"] for row in result], [belief, profile, project])

    def test_explicit_project_and_preference_recall_stays_in_requested_kind(self):
        projects = [self.remember("Build a telescope mount."), self.remember("Plan a pottery workshop.")]
        preferences = [self.remember("Enjoy dry humour.", kind="preference", confidence=0.75), self.remember("Use concise replies.", kind="preference", confidence=1.0)]
        profile = self.remember("I work as an illustrator.", kind="profile")
        for question in ("What projects am I working on?", "Which are my current projects?", "Show me my projects"):
            with self.subTest(question=question):
                result = self.db.relevant_memories(self.user_id, question)
                self.assertEqual([row["id"] for row in result], list(reversed(projects)))
                self.assertTrue(all(row["kind"] == "project" for row in result))
        for question in ("What are my preferences?", "List my preferences", "What do you remember about my preferences?"):
            with self.subTest(question=question):
                result = self.db.relevant_memories(self.user_id, question)
                self.assertEqual([row["id"] for row in result], list(reversed(preferences)))
                self.assertTrue(all(row["kind"] == "preference" for row in result))
        self.assertIsNone(self.used(profile))
        # Merely mentioning a project or a recall phrase within a factual
        # question must not inject the whole set of personal context.
        result = self.db.relevant_memories(self.user_id, "What is the answer to my question about the project?")
        self.assertEqual([row["id"] for row in result], [preferences[1]])
        result = self.db.relevant_memories(self.user_id, "What do you remember about me and pirate ship history?")
        self.assertEqual([row["id"] for row in result], [preferences[1]])


if __name__ == "__main__":
    unittest.main()
