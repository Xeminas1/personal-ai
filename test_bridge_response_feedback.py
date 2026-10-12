"""External bridge review ratings remain untrusted, source-linked and idempotent."""
from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path

from app.bridge_response_feedback import ingest_reviews, review_scores


def xemai(cid=100):
    return {"id":cid, "body":"XemAi autonomous response (opt-in, read-only):\n"
            "Model: qwen3.5:9b-q8_0\nCompute: remote_worker\n"
            "Discussion mode: advanced-worker\nI think tests need careful review."}


def reviewer(cid=101, target=100, score=8, aspect="reasoning", reason="Recognised the evidence issue and proposed a relevant test."):
    return {"id":cid, "body":(
        "ChatGPT bridge reply (manual, read-only):\nA useful disagreement.\n"
        f"XemAi review score (external, unverified): target={target}; "
        f"score={score}; aspect={aspect}; reason={reason}"
    )}


class ExternalReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def test_source_link_and_idempotent_no_automatic_learning(self):
        comments = [xemai(), reviewer()]
        self.assertEqual(ingest_reviews(self.folder, issue=1, comments=comments), 1)
        self.assertEqual(ingest_reviews(self.folder, issue=1, comments=comments), 0)
        self.assertIn("8/10", review_scores(self.folder, issue=1))
        self.assertIn("Recognised the evidence", review_scores(self.folder, issue=1, show=1))
        data = json.loads((self.folder / "bridge_external_review_scores.jsonl").read_text())
        self.assertEqual(data["source"], "github_external_unverified")
        self.assertIs(data["owner_approved"], False)
        self.assertIs(data["training_applied"], False)
        self.assertNotIn("A useful disagreement", data)
        self.assertIn("No external", review_scores(self.folder, issue=2))

    def test_reject_forged_target_self_and_private_identifier(self):
        self.assertEqual(ingest_reviews(self.folder, issue=1, comments=[
            reviewer(104, target=999),
            reviewer(105, target=105),
            {"id": 106, "body": (
                "XemAi autonomous response (opt-in, read-only):\n"
                "XemAi review score (external, unverified): "
                "target=100; score=10; aspect=reasoning; reason=I win every time."),
            },
        ]), 0)
        self.assertEqual(ingest_reviews(self.folder, issue=1, comments=[
            xemai(), reviewer(107, reason="The secret token=abcdef12345 is present.")
        ]), 0)
        self.assertEqual(ingest_reviews(self.folder, issue=1, comments=[
            xemai(), reviewer(108, reason="Great answer contact test@example.com now.")
        ]), 0)

    def test_accept_low_score_and_multiple_subsequent_reviews(self):
        comments = [
            xemai(100),
            reviewer(101, score=0, aspect="accuracy", reason="Unsupported version claim made as a definite fact."),
            reviewer(102, score=10, aspect="evidence", reason="Quoted the provided lines without making global claims."),
        ]
        self.assertEqual(ingest_reviews(self.folder, issue=1, comments=comments), 2)
        self.assertIn("0/10", review_scores(self.folder, issue=1))
        self.assertIn("10/10", review_scores(self.folder, issue=1))
        self.assertEqual(ingest_reviews(self.folder, issue=1, comments=comments), 0)


if __name__ == "__main__":
    unittest.main()
