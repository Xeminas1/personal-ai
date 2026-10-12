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
        records = [json.loads(row) for row in source.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(records), 10)
        expected_fields = {"reviewed", "consent", "source", "messages"}
        seen = set()
        for record in records:
            self.assertEqual(set(record), expected_fields)
            self.assertIs(record["reviewed"], True)
            self.assertIs(record["consent"], True)
            self.assertEqual(record["source"], "owner_consented")
            self.assertEqual([m["role"] for m in record["messages"]], ["user", "assistant"])
            fingerprint = record["messages"][0]["content"].casefold()
            self.assertNotIn(fingerprint, seen)
            seen.add(fingerprint)
            self.assertNotIn("first option must always be right",
                             record["messages"][1]["content"])
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
        self.assertIn("stopped safely", self.call(
            "bridge weight draft 1: We must verify the underlying evidence first."))
        self.assertIn("stopped safely", self.call(
            "bridge weight approve 1 deadbeef"))
        self.assertFalse((self.data / _EXPORT_DIR).exists())


    def test_long_truncated_candidate_requires_owner_rewrite_and_exports_only_rewrite(self):
        bridge_collection(self.data, "bridge learning on")
        long_question = ("Discuss a fictional evaluation scenario, and do not invent "
                         "missing facts. " * 24) + "The original is intentionally longer than archive limits."
        self.assertGreater(len(long_question), 1800)
        self.assertTrue(self.candidate(1, input_text=long_question))
        archive = self.data / "github_bridge_training_candidates.jsonl"
        original = json.loads(archive.read_text().splitlines()[0])
        self.assertEqual(len(original["input_excerpt"]), 1800)
        self.assertIs(original["input_was_truncated"], True)
        self.assertIn("may be clipped", self.call(
            "bridge weight draft 1: A fictional answer with valid source attribution."))
        question = ("Given a version number present only in a comment, explain why "
                    "we cannot assert the active project version from this alone.")
        answer = ("A comment mentioning a version is evidence only that a comment "
                  "contains that number, not that the running program has that version. "
                  "Check a verified active manifest or configuration before asserting it.")
        preview = self.call(f"bridge weight rewrite 1: {question} || {answer}")
        self.assertIn("OWNER-REWRITTEN", preview)
        self.assertIn(question, preview)
        self.assertNotIn(original["input_excerpt"], preview)
        code = re.search(r"bridge weight approve 1 ([a-f0-9]{8})", preview).group(1)
        self.assertIn("approved for a future LOCAL training dataset", self.call(
            f"bridge weight approve 1 {code}"))
        self.assertIn("1 approved", self.call("bridge weight status"))
        # Export minimum: add nine distinct, short fictional cases.
        for i in range(2, 11):
            self.assertTrue(self.candidate(i))
            draft = self.call(f"bridge weight draft {i}: The correct response "
                              f"for fictional case {i} must cite observed evidence.")
            self.assertIn("PREVIEW ONLY", draft)
            code2 = re.search(rf"bridge weight approve {i} ([a-f0-9]{{8}})", draft).group(1)
            self.assertIn("approved", self.call(f"bridge weight approve {i} {code2}"))
        label = self.call("bridge weight export")
        code3 = re.search(r"bridge weight export ([a-f0-9]{8})", label).group(1)
        self.assertIn("Local reviewed SFT", self.call(f"bridge weight export {code3}"))
        source = next((self.data / _EXPORT_DIR).glob("bridge_reviewed_*.jsonl"))
        rows = [json.loads(line) for line in source.read_text().splitlines()]
        self.assertEqual(rows[0]["messages"][0]["content"], question)
        self.assertEqual(rows[0]["messages"][1]["content"], answer)
        self.assertFalse(any(original["input_excerpt"] in str(row) for row in rows))
        self.assertFalse(any("first option must always be right" in str(row) for row in rows))

    def test_rewritten_approval_code_is_bound_to_both_prompt_and_answer(self):
        bridge_collection(self.data, "bridge learning on")
        self.assertTrue(self.candidate(1))
        a = self.call("bridge weight rewrite 1: Explain why the comment is not "
                      "proof of the current build version. || "
                      "The comment is not authoritative evidence of the active build version.")
        key_a = re.search(r"approve 1 ([a-f0-9]{8})", a).group(1)
        b = self.call("bridge weight rewrite 1: Explain how active version "
                      "metadata differs from comments. || "
                      "Comments can be stale; inspect verified active build metadata.")
        key_b = re.search(r"approve 1 ([a-f0-9]{8})", b).group(1)
        self.assertNotEqual(key_a, key_b)
        self.assertIn("Approval refused", self.call(f"bridge weight approve 1 {key_a}"))
        self.assertIn("approved", self.call(f"bridge weight approve 1 {key_b}"))
        self.assertEqual(len(_journal(self.data).read_text().splitlines()), 3)

    def test_rewrite_fails_closed_on_unreviewed_or_sensitive_pair(self):
        self.assertIn("Unknown candidate", self.call(
            "bridge weight rewrite 1: Explain evidence attribution. || "
            "Do not infer a version absent from the source."))
        bridge_collection(self.data, "bridge learning on")
        self.assertTrue(self.candidate(1))
        self.assertIn("Format:", self.call("bridge weight rewrite 1: No delimiter provided."))
        self.assertIn("15-1600", self.call(
            "bridge weight rewrite 1: My password: fakevalue || "
            "Do not put secrets in training examples."))
        self.assertIn("15-1600", self.call(
            "bridge weight rewrite 1: Explain the difference. || "
            "See https://example.org/private for details."))
        self.assertIn("0 approved", self.call("bridge weight status"))
        self.assertFalse((self.data / _EXPORT_DIR).exists())

    def test_existing_approved_correction_is_preserved_without_rewrite(self):
        self._prepare_approved(1)
        self.assertIn("1 approved", self.call("bridge weight status"))
        result = self.call("bridge weight rewrite 1: A new question about "
                           "fake status. || A new answer that has not been reviewed.")
        self.assertIn("PREVIEW ONLY", result)
        # A new draft supersedes previous approval until it is reviewed;
        # the already written historic approval remains in the append journal.
        self.assertIn("0 approved", self.call("bridge weight status"))
        self.assertEqual(len(_journal(self.data).read_text().splitlines()), 3)

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
