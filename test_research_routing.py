from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from app.tools import (
    ToolRegistry, extract_exact_quote, research_query_for_turn,
    should_force_web_search, should_research_query,
)


class ResearchRoutingTests(unittest.TestCase):
    def test_contractions_route_factual_questions_but_preserve_exclusions(self):
        for query in ("What's the most famous pirate ship", "What’s the most famous pirate ship", "whats the most famous pirate ship", "What is the most famous pirate ship"):
            with self.subTest(query=query):
                self.assertTrue(should_research_query(query))
        for query in ("What's your name?", "whats your name?", "Write me a pirate ship name", "Create a story with sources"):
            with self.subTest(query=query):
                self.assertFalse(should_research_query(query))

    def test_explicit_web_bans_override_search_and_research(self):
        for ban in ("don't search the web", "don’t search the web", "dont search the web", "do not research", "do not browse", "no web", "without web", "without internet", "without searching", "without researching", "don't use the internet", "don't look it up"):
            query = f"{ban}; verify this using sources about the latest pirate news"
            with self.subTest(ban=ban):
                self.assertFalse(should_research_query(query))
                self.assertFalse(should_force_web_search(query))
                self.assertEqual(research_query_for_turn(query, ["What is the most famous pirate ship?"]), query)

    def test_sources_followup_reuses_user_question_and_correction(self):
        previous = ["What's the most famous pirate ship", "Captain Jack Sparrow's ship is not Revenge it's the Black Pearl"]
        for query in ("Why are you not using sources for this information", "Sources?", "can you verify that?", "look it up", "Please provide sources", "Can you fact-check that?", "Please research this"):
            with self.subTest(query=query):
                result = research_query_for_turn(query, previous)
                self.assertIn("pirate ship", result)
                self.assertIn("Jack Sparrow", result)
                self.assertIn("Black Pearl", result)
                self.assertNotIn("Why are you not using sources", result)
                self.assertLessEqual(len(result), 1200)
                self.assertTrue(result.endswith("verify sources"))
        self.assertTrue(should_research_query("can you verify that?"))
        self.assertTrue(should_force_web_search("look it up"))

    def test_independent_topics_and_topic_changes_are_not_mixed(self):
        previous = ["What's the most famous pirate ship", "How does creatine affect exercise performance?", "Sources?"]
        contextual = research_query_for_turn("Can you verify that?", previous)
        self.assertIn("creatine", contextual)
        self.assertNotIn("pirate", contextual)
        standalone = "Find sources about Blackbeard's Queen Anne's Revenge"
        self.assertEqual(research_query_for_turn(standalone, previous), standalone)
        meta_topic = "Why are AI citations unreliable?"
        self.assertEqual(research_query_for_turn(meta_topic, previous), meta_topic)
        self.assertEqual(research_query_for_turn("Sources?", []), "Sources?")
        self.assertEqual(research_query_for_turn("Sources?", [None, {"role": "assistant", "content": "Invented claim"}]), "Sources?")
        self.assertEqual(research_query_for_turn(None, []), "")
        self.assertLessEqual(len(research_query_for_turn("Sources?", ["pirate " * 1000])), 1200)

    def test_relevance_precedes_authority_and_fetched_boilerplate_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            registry = ToolRegistry(Path(temporary), Path(temporary) / "data", logging.getLogger("routing"))
            results = [
                {"title": "Government information guidance", "url": "https://www.cisa.gov/advisory", "content": "Share sensitive information only on official secure websites."},
                {"title": "Pirate ships", "url": "https://www.gov.uk/pirate-error", "content": "Famous pirate ship history."},
                {"title": "Pirate ships", "url": "https://museum.example/pirate-ships", "content": "Pirate ships include Blackbeard's Queen Anne's Revenge."},
            ]
            registry.web_search = lambda query, max_results=5: {"results": results}
            fetched = []
            content = "Pirate ships included Queen Anne's Revenge, which Blackbeard commanded in the early eighteenth century."

            def fetch(url, **kwargs):
                fetched.append(url)
                return {"title": "Pirate ships", "content": content if "museum" in url else "Privacy notice: share information only on official secure websites."}

            registry.web_fetch = fetch
            bundle = registry.research_evidence("What's the most famous pirate ship?", max_sources=3)
            self.assertEqual([item["url"] for item in bundle["sources"]], ["https://museum.example/pirate-ships"])
            self.assertNotIn("https://www.cisa.gov/advisory", fetched)
            source = bundle["sources"][0]
            self.assertTrue(source["quote_verified_from_fetched_page"])
            self.assertIn(source["quote"], content)
            self.assertEqual(extract_exact_quote("Share information only on official secure websites.", "famous pirate ship"), "")

    def test_more_relevant_result_ranks_before_partial_authority_match(self):
        with tempfile.TemporaryDirectory() as temporary:
            registry = ToolRegistry(Path(temporary), Path(temporary) / "data", logging.getLogger("routing"))
            registry.web_search = lambda query, max_results=5: {"results": [
                {"title": "Ship transportation rules", "url": "https://www.gov.uk/ships", "content": "Ship licensing and transportation regulations."},
                {"title": "Pirate ships", "url": "https://museum.example/pirate-ships", "content": "Historical pirate ships included Queen Anne's Revenge."},
            ]}
            registry.web_fetch = lambda url, **kwargs: {"title": "Source", "content": (
                "Pirate ships included Queen Anne's Revenge, which Blackbeard commanded in the early eighteenth century."
                if "museum" in url else "Ship licensing rules establish standards for commercial transportation in British waters."
            )}
            sources = registry.research_evidence("famous pirate ship", max_sources=1)["sources"]
            self.assertEqual(sources[0]["url"], "https://museum.example/pirate-ships")


if __name__ == "__main__":
    unittest.main()
