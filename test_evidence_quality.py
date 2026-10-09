"""Offline evidence fixtures verify passage context and truthful provenance."""
from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path

from app.tools import (
    ToolRegistry, _source_authority, extract_exact_quote,
    extract_relevant_passage, format_research_appendix,
)


class EvidenceQualityTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.registry = ToolRegistry(Path(temporary.name), Path(temporary.name) / "data", logging.getLogger(self.id()))
        self.searches = []
        self.fetches = []

    def fixture(self, results, pages):
        def search(query, max_results=5):
            self.searches.append(query)
            return {"results": results}

        def fetch(url, **kwargs):
            self.fetches.append(url)
            content = pages[url]
            if isinstance(content, Exception):
                raise content
            return {"url": url, "title": "Source page", "content": content}

        self.registry.web_search = search
        self.registry.web_fetch = fetch

    @staticmethod
    def result(url, text="Supplement trial mood results"):
        return {"title": text, "url": url, "content": text}

    def test_late_passage_keeps_nearby_qualification_without_more_fetches(self):
        topic = "Supplement use improved mood in the initial small trial group."
        qualification = "However, the larger randomized trial found no benefit, so those preliminary results were not confirmed."
        page = "Website navigation and accessibility information appears here. " * 60 + topic + " " + qualification
        url = "https://research.example/trial"
        self.fixture([self.result(url)], {url: page})
        bundle = self.registry.research_evidence("Supplement trial mood results", max_sources=1)
        source = bundle["sources"][0]
        self.assertIn(topic, source["excerpt"])
        self.assertIn(qualification, source["excerpt"])
        self.assertLessEqual(len(source["excerpt"]), 1200)
        self.assertTrue(source["excerpt_truncated"])
        self.assertEqual(source["content_origin"], "fetched_page")
        self.assertTrue(source["page_fetched"])
        self.assertTrue(source["quote_verified_from_fetched_page"])
        self.assertIn(source["quote"], page)
        self.assertEqual(len(self.searches), 2)
        self.assertEqual(self.fetches, [url])
        appendix = format_research_appendix(bundle)
        self.assertTrue(appendix.startswith("Sources read:"))
        self.assertIn("each citation still needs to support its claim", appendix)

    def test_quote_never_cuts_off_a_long_sentences_negative_conclusion(self):
        sentence = (
            "The research team reported that supplement use was associated with improved mood and concentration "
            "among the adults who participated in this small observational study, but the larger randomized trial found no benefit."
        )
        self.assertEqual(extract_exact_quote(sentence, "supplement mood trial", max_words=24), "")
        passage = extract_relevant_passage(sentence, "supplement mood trial")
        self.assertIn("but the larger randomized trial found no benefit.", passage)
        self.assertEqual(passage, sentence)
        self.assertEqual(extract_exact_quote("Supplement mood results were preliminary", "supplement mood"), "")

    def test_snippets_and_unknown_provenance_never_appear_as_read_pages_or_quotes(self):
        url = "https://research.example/unread"
        self.fixture([self.result(url)], {url: RuntimeError("fetch failed")})
        bundle = self.registry.research_evidence("supplement trial mood results", max_sources=1)
        source = bundle["sources"][0]
        self.assertEqual(source["content_origin"], "search_snippet")
        self.assertFalse(source["page_fetched"])
        self.assertFalse(source["quote_verified_from_fetched_page"])
        self.assertEqual(source["quote"], "")
        self.assertEqual(self.fetches, [url])
        appendix = format_research_appendix(bundle)
        self.assertTrue(appendix.startswith("Sources retrieved:"))
        self.assertIn("Search result snippet; page not read.", appendix)
        self.assertNotIn("Sources read:", appendix)
        source["quote"] = "unverified-quote-sentinel"
        source["quote_verified_from_fetched_page"] = True
        self.assertNotIn("unverified-quote-sentinel", format_research_appendix(bundle))
        source.pop("content_origin")
        source["page_fetched"] = True
        self.assertNotIn("unverified-quote-sentinel", format_research_appendix(bundle))

    def test_a_bounded_fragment_of_one_long_sentence_is_not_a_verified_quote(self):
        url = "https://research.example/long"
        # Few unusually long tokens expose word-count-only quote validation.
        page = ("background" * 150 + " ") * 4 + "supplement mood trial results were preliminary."
        self.fixture([self.result(url)], {url: page})
        source = self.registry.research_evidence("supplement trial mood results", max_sources=1)["sources"][0]
        self.assertIn("supplement mood", source["excerpt"])
        self.assertLessEqual(len(source["excerpt"]), 1200)
        self.assertTrue(source["excerpt_truncated"])
        self.assertEqual(source["quote"], "")
        self.assertFalse(source["quote_verified_from_fetched_page"])

    def test_exact_www_prefix_preserves_official_hostname_authority(self):
        for host, expected in (("who.int", "World Health Organization"), ("w3.org", "Web standards body"),
                               ("worldbank.org", "International development institution"), ("microsoft.com", "Official vendor source")):
            with self.subTest(host=host):
                self.assertEqual(_source_authority("https://" + host, content="Official information")[1], expected)
                self.assertEqual(_source_authority("https://www." + host, content="Official information")[1], expected)
        self.assertEqual(_source_authority("https://wwwwho.int", content="Official information")[1], "General web source")

    def test_comparable_sources_prefer_a_second_host_with_same_fetch_budget(self):
        urls = ["https://museum.example/one", "https://museum.example/two", "https://archive.example/one"]
        page = "Pirate ships included Queen Anne Revenge, which Blackbeard commanded in the eighteenth century."
        self.fixture([self.result(url, "Pirate ships Queen Anne Revenge") for url in urls], dict.fromkeys(urls, page))
        sources = self.registry.research_evidence("Pirate ships Queen Anne Revenge", max_sources=2)["sources"]
        self.assertEqual([source["url"] for source in sources], [urls[0], urls[2]])
        self.assertEqual(len(self.fetches), 2)
        self.assertEqual(len(self.searches), 2)

    def test_diversity_does_not_replace_stronger_relevance_or_authority(self):
        for stronger_authority in (False, True):
            with self.subTest(stronger_authority=stronger_authority):
                domain = "www.gov.uk" if stronger_authority else "museum.example"
                urls = [f"https://{domain}/one", f"https://{domain}/two", "https://archive.example/one"]
                direct = "Pirate ships Queen Anne Revenge"
                alternative = direct if stronger_authority else "Ship transportation rules"
                results = [self.result(urls[0], direct), self.result(urls[1], direct), self.result(urls[2], alternative)]
                page = "Pirate ships included Queen Anne Revenge, which Blackbeard commanded in the eighteenth century."
                self.fixture(results, {urls[0]: page, urls[1]: page, urls[2]: alternative + "."})
                sources = self.registry.research_evidence(direct, max_sources=2)["sources"]
                self.assertEqual([source["url"] for source in sources], urls[:2])

    def test_a_short_quote_does_not_outrank_a_more_relevant_qualified_passage(self):
        direct_url, partial_url = "https://research.example/direct", "https://research.example/partial"
        direct = (
            "The research team reported that supplement use was associated with improved mood and concentration "
            "among the adults who participated in this small observational study, but the larger randomized trial found no benefit."
        )
        partial = "A trial is a research procedure used to measure health outcomes."
        self.fixture([self.result(direct_url), self.result(partial_url, "Trial results")], {direct_url: direct, partial_url: partial})
        sources = self.registry.research_evidence("Supplement trial mood results", max_sources=2)["sources"]
        self.assertEqual(sources[0]["url"], direct_url)
        self.assertEqual(sources[0]["quote"], "")
        self.assertIn("found no benefit", sources[0]["excerpt"])
        self.assertTrue(sources[1]["quote_verified_from_fetched_page"])
        self.assertEqual(len(self.fetches), 2)


if __name__ == "__main__":
    unittest.main()
