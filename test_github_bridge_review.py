"""Owner-controlled learning review and reversible topical recall tests."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.github_bridge import chat_command
from app.github_bridge_learning import append_candidate, archive_path, command as collect
from app.github_bridge_review import (
    command, journal_path, recall_context, review_counts,
)


class OwnerReviewTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.data = Path(tmp.name) / "data"
        collect(self.data, "bridge learning on")
        self.provenance = {
            "model": "qwen3.5:9b-q8_0",
            "compute": "remote_worker",
            "mode": "advanced-worker",
        }
        self.assertTrue(append_candidate(
            self.data, repo="Example/private", issue=1,
            comment_id=123,
            question="Inspect Skyrim Papyrus input routing and identify gaps.",
            answer="The Skyrim version cannot be concluded from the snippets alone.",
            provenance=self.provenance,
            timestamp=datetime(2026, 10, 12, tzinfo=timezone.utc),
        ))

    def bridge(self, value):
        return chat_command(value, self.data)

    def test_queue_show_and_never_auto_promote(self):
        result = self.bridge("bridge learning review")
        self.assertIn("#1 [unverified", result)
        shown = self.bridge("bridge learning show 1")
        self.assertIn("LOCAL UNTRUSTED", shown)
        self.assertIn("qwen3.5:9b-q8_0", shown)
        self.assertFalse(journal_path(self.data).exists())
        self.assertEqual(review_counts(self.data)["approved"], 0)
        self.assertEqual(recall_context(self.data, "What is Skyrim version?"), "")

    def test_proposal_approval_recall_and_revoke(self):
        original = archive_path(self.data).read_bytes()
        self.assertIn("PREVIEW ONLY", self.bridge(
            "bridge learning propose 1: Skyrim version claims need cited source evidence. "
            "|| Source fixture in test_attachment_challenges.py declares 0.6.15"
        ))
        self.assertEqual(review_counts(self.data)["proposed"], 1)
        self.assertEqual(recall_context(self.data, "Skyrim version"), "")
        self.assertIn("OWNER-APPROVED", self.bridge("bridge learning approve 1"))
        self.assertEqual(review_counts(self.data)["approved"], 1)
        recalled = recall_context(self.data, "Explain Skyrim version source evidence")
        self.assertIn("Skyrim version claims", recalled)
        self.assertIn("not independently fact-checked", recalled)
        self.assertEqual(recall_context(self.data, "How to change my bicycle tyre"), "")
        self.assertIn("OWNER-REVIEWED", self.bridge("bridge learning approved"))
        self.assertIn("1;", self.bridge("bridge learning status"))
        self.assertEqual(archive_path(self.data).read_bytes(), original)
        self.assertIn("revoked", self.bridge("bridge learning revoke 1"))
        self.assertEqual(recall_context(self.data, "Skyrim version"), "")
        events = [json.loads(x) for x in journal_path(self.data).read_text().splitlines()]
        self.assertEqual([x["action"] for x in events],
                         ["proposed", "approved", "revoked"])
        self.assertEqual(events[1]["review"], "owner_attestation_required")

    def test_reject_unverified_and_require_evidence(self):
        self.assertIn("First propose", self.bridge("bridge learning approve 1"))
        self.assertIn("Format:", self.bridge("bridge learning propose 1: just a lesson"))
        self.assertIn("rejected", self.bridge("bridge learning reject 1"))
        self.assertEqual(review_counts(self.data)["approved"], 0)
        self.assertIn("No owner-approved lessons", self.bridge("bridge learning approved"))

    def test_never_accept_private_paths_secrets_or_invalid_lengths(self):
        self.assertIn("without secrets", self.bridge(
            "bridge learning propose 1: Follow github_pat_EXAMPLE_SECRET token string "
            "|| Given evidence should not contain a real secret"
        ))
        self.assertIn("without secrets", self.bridge(
            "bridge learning propose 1: A useful lesson about verification "
            "|| Personal path C:\\Users\\Tester\\secret.txt"
        ))
        self.assertEqual(review_counts(self.data)["approved"], 0)
        self.assertFalse(journal_path(self.data).exists())

    def test_archive_corruption_fails_closed_and_preserves_state(self):
        journal = journal_path(self.data)
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal.write_text("{broken JSON\n", encoding="utf-8")
        response = command(self.data, "bridge learning review")
        self.assertIn("could not be read safely", response)
        self.assertEqual(recall_context(self.data, "Skyrim version"), "")
        self.assertEqual(journal.read_text(), "{broken JSON\n")

    def test_recall_is_topic_scoped_and_never_uses_unapproved_response(self):
        self.assertEqual(recall_context(self.data, "Skyrim Papyrus input routing"), "")
        proposed = self.bridge(
            "bridge learning propose 1: Don't invent Skyrim Papyrus input routing facts "
            "|| Read-only stage-1 benchmark explains limits of source excerpts"
        )
        self.assertIn("PREVIEW ONLY", proposed)
        self.assertEqual(recall_context(self.data, "Skyrim Papyrus input routing"), "")
        self.assertIn("OWNER-APPROVED", self.bridge("bridge learning approve 1"))
        note = recall_context(self.data, "Skyrim Papyrus input routing")
        self.assertIn("Don't invent Skyrim Papyrus", note)
        self.assertNotIn("version cannot be concluded", note)
        self.assertNotIn("Inspect Skyrim Papyrus", note)


if __name__ == "__main__":
    unittest.main()
