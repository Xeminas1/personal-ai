"""Bridge-to-weights is owner reviewed, local, reversible and never trains.

All sample prompts are invented for these tests. No real private issue content
is used in source, CI or the repo.
"""
from __future__ import annotations

import json
import re
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from app.github_bridge import chat_command
from app.github_bridge_learning import append_candidate, command as bridge_collection
from app.github_bridge_weight import _EXPORT_DIR, _journal, command as weight_command
from training.prepare_dataset import _read_input, prepare, verify


class BridgeToWeightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / "data"
        self.provenance = {"model": "qwen3.5:9b-q8_0",
                           "compute": "remote_worker", "mode": "advanced-worker"}
        self.time = datetime(2026, 10, 12, tzinfo=timezone.utc)

    def call(self, text):
        return chat_command(text, self.data)

    def candidate(self, num, *, input_text=None, model_answer=None):
        return append_candidate(
            self.data,
            repo="Example/PRIVATE",
            issue=14, comment_id=1000 + num,
            question=input_text or f"Which option is correct for exercise {num}? Please check the evidence first.",
            answer=model_answer or "Of course! I checked the evidence, and the first option must always be right.",
            provenance=self.provenance, timestamp=self.time,
        )

    def _prepare_approved(self, count=10):
        self.assertIn("ENABLED", bridge_collection(self.data, "bridge learning on"))
        for i in range(1, count + 1):
            self.assertTrue(self.candidate(i))
            corrected = (f"The answer to exercise {i} must be supported by the supplied evidence; "
                         "without sources, say that it is unknown.")
            draft = self.call(f"bridge weight draft {i}: {corrected}")
            self.assertIn("PREVIEW ONLY", draft)
            code = re.search(r"bridge weight approve \d+ ([a-f0-9]{8})", draft).group(1)
            self.assertIn("approved for a future LOCAL training dataset",
                          self.call(f"bridge weight approve {i} {code}"))
        self.assertEqual(len(_journal(self.data).read_text().splitlines()), count * 2)

    def test_empty_archive_no_implicit_collection_or_weights(self):
        self.assertIn("0 approved", self.call("bridge weight status"))
        self.assertIn("Nothing exported", self.call("bridge weight export"))
        self.assertFalse(_journal(self.data).exists())
        self.assertFalse((self.data / _EXPORT_DIR).exists())
        self.assertFalse(self.candidate(1))
        self.assertIn("Unknown candidate", self.call(
            "bridge weight draft 1: A completely corrected answer here."))

    def test_cannot_export_a_draft_without_review(self):
        bridge_collection(self.data, "bridge learning on")
        self.assertTrue(self.candidate(1))
        draft = self.call("bridge weight draft 1: Confirmed by the local fictional fixture.")
        self.assertIn("PREVIEW ONLY", draft)
        self.assertIn("0 owner-reviewed", self.call("bridge weight export"))
        self.assertFalse((self.data / _EXPORT_DIR).exists())
        self.assertNotIn("model_response", draft)

    def test_stale_approval_code_does_not_authorise_new_target(self):
        bridge_collection(self.data, "bridge learning on")
        self.assertTrue(self.candidate(1))
        first = self.call("bridge weight draft 1: Use the second option only after checking the source.")
        stale = re.search(r"approve 1 ([a-f0-9]{8})", first).group(1)
        self.call("bridge weight draft 1: The source is missing, so we cannot select either option.")
        self.assertIn("Approval refused", self.call(f"bridge weight approve 1 {stale}"))
        self.assertIn("0 approved", self.call("bridge weight status"))

    def test_reject_private_prompts_or_bad_corrected_answers(self):
        bridge_collection(self.data, "bridge learning on")
        self.assertTrue(self.candidate(1, input_text="My password: FakeSecretPassword at example.net"))
        self.assertIn("contains private data", self.call(
            "bridge weight draft 1: The correct next step is to check the source."))
        self.assertTrue(self.candidate(2))
        self.assertIn("no apparent secrets", self.call(
            "bridge weight draft 2: Consult https://example.net/secret before proceeding."))
        self.assertFalse((self.data / _EXPORT_DIR).exists())

    def test_reviewed_data_exports_into_existing_training_schema(self):
        self._prepare_approved(10)
        self.assertIn("10 approved", self.call("bridge weight status"))
        pending = self.call("bridge weight export")
        self.assertIn("LOCAL DATASET EXPORT PREVIEW", pending)
        self.assertFalse((self.data / _EXPORT_DIR).exists())
        key = re.search(r"bridge weight export ([a-f0-9]{8})", pending).group(1)
        confirmed = self.call(f"bridge weight export {key}")
        self.assertIn("Local reviewed SFT source file created", confirmed)
        files = list((self.data / _EXPORT_DIR).glob("bridge_reviewed_*.jsonl"))
        self.assertEqual(len(files), 1)
        source = files[0]
        records, digest = _read_input(source)
        self.assertEqual(len(records), 10)
        self.assertEqual(len(digest), 64)
        self.assertFalse(any("first option must always be right" in r["messages"][1]["content"]
                             for r in records))
        self.assertTrue(all(r["messages"][0]["role"] == "user" and
                            r["messages"][1]["role"] == "assistant" for r in records))
        # A second, separately consented action prepares the train/holdout split.
        prepared = prepare(source, self.data / "weight_training" / "prepared",
                           seed="bridge-review-test-v1", label="bridge")
        integrity = verify(prepared)
        self.assertEqual(integrity["train_count"] + integrity["heldout_count"], 10)
        self.assertFalse(integrity["training_applied"])
        self.assertFalse(integrity["model_changed"])
        self.assertFalse((self.data / "model.gguf").exists())

    def test_revoking_changes_export_fingerprint_and_excludes_example(self):
        self._prepare_approved(11)
        preview = self.call("bridge weight export")
        old_code = re.search(r"bridge weight export ([a-f0-9]{8})", preview).group(1)
        self.assertIn("revoked from FUTURE", self.call("bridge weight revoke 1"))
        self.assertIn("refused", self.call(f"bridge weight export {old_code}"))
        new_preview = self.call("bridge weight export")
        code = re.search(r"bridge weight export ([a-f0-9]{8})", new_preview).group(1)
        self.assertNotEqual(old_code, code)
        self.assertIn("Local reviewed", self.call(f"bridge weight export {code}"))
        exported = next((self.data / _EXPORT_DIR).glob("*.jsonl"))
        rows = [json.loads(x) for x in exported.read_text().splitlines()]
        self.assertEqual(len(rows), 10)
        self.assertFalse(any("exercise 1?" in row["messages"][0]["content"] for row in rows))

    def test_corrupt_local_candidate_does_not_crash_review_or_approve(self):
        bridge_collection(self.data, "bridge learning on")
        self.assertTrue(self.candidate(1))
        archive = self.data / "github_bridge_training_candidates.jsonl"
        archive.write_text("null\n", encoding="utf-8")
        self.assertIn("malformed", self.call(
            "bridge weight draft 1: We must verify the underlying evidence first."))
        self.assertIn("Approval refused", self.call(
            "bridge weight approve 1 deadbeef"))
        self.assertFalse((self.data / _EXPORT_DIR).exists())

    def test_review_one_candidate_is_never_training_consent(self):
        bridge_collection(self.data, "bridge learning on")
        self.assertTrue(self.candidate(1))
        from app.github_bridge_review import command as lessons
        self.assertIn("PREVIEW ONLY", lessons(self.data,
            "bridge learning propose 1: Evidence is necessary for a correct answer. "
            "|| Confirm against local fictional test observations."))
        self.assertIn("OWNER-APPROVED", lessons(self.data, "bridge learning approve 1"))
        self.assertIn("0 approved", self.call("bridge weight status"))
        self.assertIn("Nothing exported", self.call("bridge weight export"))


if __name__ == "__main__":
    unittest.main()
