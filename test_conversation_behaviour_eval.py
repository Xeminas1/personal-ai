"""Regression checks for the synthetic conversation evaluation rubric."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

MODULE_PATH = Path(__file__).resolve().parent / "tests" / "conversation_behaviour_eval.py"
spec = importlib.util.spec_from_file_location("conversation_behaviour_eval", MODULE_PATH)
evaluation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(evaluation)


class ConversationBehaviourEvalTests(unittest.TestCase):
    def test_five_distinct_scenarios(self):
        self.assertEqual(len(evaluation.SCENARIOS), 5)
        self.assertEqual(len({c["id"] for c in evaluation.SCENARIOS}), 5)
        for scenario in evaluation.SCENARIOS:
            self.assertGreaterEqual(len(scenario["turns"]), 3)
            self.assertEqual(scenario["turns"][-1]["role"], "user")
            self.assertTrue(scenario["expect"])

    def test_score_bounds(self):
        self.assertEqual(evaluation.validate_scores({key: 2 for key in evaluation.RUBRIC}), 10)
        self.assertEqual(evaluation.validate_scores({key: 0 for key in evaluation.RUBRIC}), 0)
        with self.assertRaises(ValueError):
            evaluation.validate_scores({key: 3 for key in evaluation.RUBRIC})
        with self.assertRaises(ValueError):
            evaluation.validate_scores({key: True for key in evaluation.RUBRIC})
        with self.assertRaises(ValueError):
            evaluation.validate_scores({"context": 2})

    def test_report_requires_all_scenarios(self):
        ids = [scenario["id"] for scenario in evaluation.SCENARIOS]
        responses = {key: "Synthetic example response" for key in ids}
        scores = {key: {dimension: 1 for dimension in evaluation.RUBRIC} for key in ids}
        notes = {key: "Synthetic test, not a live model evaluation" for key in ids}
        report = evaluation.make_report("test-model", responses, scores, notes)
        self.assertEqual(report["total"], 25)
        self.assertEqual(report["maximum"], 50)
        self.assertEqual(len(report["cases"]), 5)
        with self.assertRaises(ValueError):
            evaluation.make_report("test-model", {}, scores, notes)


if __name__ == "__main__":
    unittest.main()
