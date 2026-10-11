"""Bridge learning is local, opt-in and NEVER changes model weights."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.github_bridge import chat_command, load_state, save_state
from app.github_bridge_learning import command, archive_path, append_candidate


class LearningArchiveTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.data = Path(temp.name) / "data"
        self.provenance = {
            "model": "qwen3:1.7b", "compute": "local_host",
            "mode": "guided-small-model",
        }
        self.time = datetime(2026, 10, 12, 9, tzinfo=timezone.utc)

    def record(self, question="Can we check the logs?", answer="We should inspect the evidence first."):
        return append_candidate(
            self.data, repo="Example/private-dialogue", issue=1,
            comment_id=123, question=question, answer=answer,
            provenance=self.provenance, timestamp=self.time,
        )

    def test_default_off_and_no_write(self):
        self.assertFalse(self.record())
        self.assertFalse(archive_path(self.data).exists())
        self.assertIn("OFF", chat_command("bridge learning status", self.data))
        self.assertNotIn("learning_enabled", load_state(self.data))

    def test_opt_in_generates_review_pending_local_example(self):
        self.assertIn("ENABLED", chat_command("bridge learning on", self.data))
        self.assertTrue(self.record())
        contents = archive_path(self.data).read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(contents), 1)
        row = json.loads(contents[0])
        self.assertEqual(row["model"], "qwen3:1.7b")
        self.assertEqual(row["compute"], "local_host")
        self.assertEqual(row["review_status"], "unverified")
        self.assertIs(row["training_applied"], False)
        self.assertNotIn("repo", row)
        self.assertNotIn("data", row)
        self.assertIn("1/2000", command(self.data, "bridge learning status"))
        self.assertIn("DISABLED", chat_command("bridge learning off", self.data))
        self.assertFalse(self.record())
        self.assertEqual(len(archive_path(self.data).read_text().splitlines()), 1)

    def test_rejects_exposed_credentials(self):
        command(self.data, "bridge learning on")
        self.assertFalse(self.record(
            question="My credential is github_pat_SOME_FAKE_EXAMPLE",
        ))
        self.assertFalse(archive_path(self.data).exists())


if __name__ == "__main__":
    unittest.main()
