"""Synthetic-only regression tests for the local lesson A/B score summariser."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest

path = Path(__file__).resolve().parent / "tests" / "lesson_ab_report.py"
spec = importlib.util.spec_from_file_location("lesson_ab_report", path)
reporter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reporter)


def sample(lesson=True, graded=True):
    rows = []
    for case in (1, 2):
        for condition in ("baseline", "with_lessons"):
            rows.append({
                "case": case, "category": "synthetic",
                "question": "Fictional question " + str(case),
                "answer": "PRIVATE_FAKE_RESPONSE_DO_NOT_EXPORT",
                "model": "model-local", "compute": "local",
                "condition": condition,
                "lesson_present": bool(lesson and condition == "with_lessons"),
                "owner_score_intent_0_or_1": (
                    0 if condition == "baseline" else 1) if graded else None,
                "owner_score_evidence_0_or_1": 1 if graded else None,
            })
    return {"samples": 2, "results": rows}


class LocalLessonABReportTests(unittest.TestCase):
    def test_paired_owner_scores_not_auto_grading(self):
        report = reporter.analyse(sample())
        self.assertEqual(report["total_pairs"], 2)
        self.assertEqual(report["paired_cases_scored"], 2)
        self.assertEqual(report["metrics"]["intent"]["delta_correct"], 2)
        self.assertEqual(report["metrics"]["evidence"]["delta_correct"], 0)
        self.assertNotIn("PRIVATE_FAKE_RESPONSE", json.dumps(report))
        self.assertIn("not proof", report["purpose"])

    def test_no_lesson_injected_is_not_evidence_of_gain(self):
        report = reporter.analyse(sample(lesson=False))
        self.assertEqual(report["paired_cases_scored"], 0)
        self.assertEqual(report["pairs_without_lesson_context"], 2)
        self.assertIsNone(report["metrics"]["intent"]["delta_rate"])

    def test_ungraded_pairs_wait_for_human_review(self):
        report = reporter.analyse(sample(graded=False))
        self.assertEqual(report["paired_cases_scored"], 0)
        self.assertEqual(report["pairs_awaiting_manual_scores"], 2)

    def test_partial_pair_must_not_count(self):
        data = sample()
        data["results"][0]["owner_score_intent_0_or_1"] = None
        report = reporter.analyse(data)
        self.assertEqual(report["paired_cases_scored"], 1)
        self.assertEqual(report["pairs_awaiting_manual_scores"], 1)

    def test_non_binary_and_boolean_owner_score_rejected(self):
        for invalid in (-1, 2, True, 0.5, "1"):
            data = sample()
            data["results"][0]["owner_score_intent_0_or_1"] = invalid
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                reporter.analyse(data)

    def test_reject_unpaired_duplicate_or_mismatched_metadata(self):
        data = sample()
        data["results"][1]["question"] = "Another question"
        with self.assertRaisesRegex(ValueError, "not comparable"):
            reporter.analyse(data)
        data = sample()
        data["results"][1]["compute"] = "remote_worker"
        with self.assertRaisesRegex(ValueError, "not comparable"):
            reporter.analyse(data)
        data = sample()
        data["results"][1]["condition"] = "baseline"
        with self.assertRaises(ValueError):
            reporter.analyse(data)
        data = sample()
        data["results"][0]["lesson_present"] = True
        with self.assertRaises(ValueError):
            reporter.analyse(data)
        data = sample()
        data["results"].pop()
        with self.assertRaises(ValueError):
            reporter.analyse(data)


if __name__ == "__main__":
    unittest.main()
