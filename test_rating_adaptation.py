"""Feedback-derived strategies are cautious descriptive comparisons, not truth."""
from __future__ import annotations
import tempfile
import unittest
from pathlib import Path

from app.database import Database
from app.rating_adaptation import response_traits, derive_style_preferences, prompt_context


class RatingAdaptationTests(unittest.TestCase):
    def test_requires_contrasting_owner_scored_examples(self):
        short = "This directly answers your question and separates fact from inference."
        long = ("A detailed answer on a different task. " * 32).strip()
        data = (
            [{"score": 10, "aspect": "overall", "content": short} for _ in range(6)]
            + [{"score": 2, "aspect": "overall", "content": long} for _ in range(6)]
        )
        prefs = derive_style_preferences(data)
        self.assertEqual([x["trait"] for x in prefs], ["concise"])
        self.assertEqual(prefs[0]["average_with"], 10)
        self.assertEqual(prefs[0]["average_without"], 2)
        self.assertEqual(prefs[0]["rated_with"], 6)
        guidance = prompt_context(prefs)
        self.assertIn("TENTATIVE", guidance)
        self.assertIn("not evidence", guidance)
        self.assertNotIn(short, guidance)
        self.assertNotIn("different task", guidance)
        self.assertEqual(derive_style_preferences(data[:7]), [])

    def test_accuracy_scores_never_become_style_reward(self):
        content = "A short, confident assertion that might be unverified."
        records = (
            [{"score": 10, "aspect": "accuracy", "content": content} for _ in range(10)]
            + [{"score": 0, "aspect": "accuracy", "content": "Long " * 220} for _ in range(10)]
        )
        self.assertEqual(derive_style_preferences(records), [])
        self.assertEqual(derive_style_preferences([{"score": True, "aspect": "overall", "content": content} for _ in range(15)]), [])

    def test_structured_case_and_restrictions(self):
        self.assertIn("structured", response_traits("1. Check the source\n2. Verify the test"))
        self.assertNotIn("structured", response_traits("Only one item\n1. Test"))
        self.assertIn("concise", response_traits("Answer the question directly, with a relevant caveat."))
        self.assertEqual(response_traits(None), set())
        self.assertEqual(prompt_context([]), "")

    def test_db_excludes_app_answers_and_factual_accuracy_reward(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Database(Path(tmp) / "ai.db")
            try:
                u = db.create_user("Owner")
                chat = db.create_chat(u["id"], "Test")["id"]
                for idx in range(12):
                    concise = idx < 6
                    message = db.add_assistant_message(
                        chat, "Direct, grounded answer to user inquiry." if concise
                        else ("Long explanation. " * 100),
                        model="qwen3:8b", compute_source="local_host",
                    )
                    db.rate_assistant_message(
                        u["id"], chat, message, 10 if concise else 1,
                        "overall",
                    )
                app = db.add_assistant_message(chat, "App fallback.", compute_source="application")
                db.rate_assistant_message(u["id"], chat, app, 10, "overall")
                fact = db.add_assistant_message(chat, "Factual answer.", model="qwen3:8b", compute_source="remote_worker")
                db.rate_assistant_message(u["id"], chat, fact, 10, "accuracy")
                examples = db.rated_model_responses(u["id"])
                self.assertEqual(len(examples), 12)
                self.assertNotIn("App fallback.", str(examples))
                self.assertNotIn("Factual answer.", str(examples))
                preferred = derive_style_preferences(examples)
                self.assertEqual([p["trait"] for p in preferred], ["concise"])
                self.assertNotIn("Direct, grounded answer", prompt_context(preferred))
            finally:
                db.close()


if __name__ == "__main__":
    unittest.main()
