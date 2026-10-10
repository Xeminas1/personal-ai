"""Optional PC specialists and laptop reviews preserve supplied evidence."""
from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from app import specialists
from app.specialists import SpecialistCoordinator


SOURCES = [{"id": 1, "url": "https://official.example/report", "title": "Report",
            "page_fetched": False, "content_origin": "search_snippet",
            "excerpt": "The result may depend on the population studied."}]


class FakeClock:
    def __init__(self):
        self.value = 0.0

    def monotonic(self):
        return self.value


class Worker:
    def __init__(self, clock):
        self.clock = clock
        self.route_info = {"compute": "remote_worker"}
        self.worker_failed_for_request = False
        self.calls = []
        self.outcomes = []
        self.durations = []
        self.local_calls = 0

    def specialist_pass(self, role, question, context, *, draft, timeout):
        self.calls.append({"role": role, "question": question, "context": context,
                           "draft": draft, "timeout": timeout})
        self.clock.value += self.durations.pop(0) if self.durations else 0.1
        outcome = self.outcomes.pop(0) if self.outcomes else "Careful interpretation; uncertainty remains."
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, dict) or outcome is None:
            return outcome
        return {"ok": True, "role": role, "model": "qwen3:14b", "output": outcome}

    def chat_raw(self, *_args, **_kwargs):
        self.local_calls += 1
        raise AssertionError("Specialists must never use inference with laptop fallback")


class LocalReviewer(Worker):
    def __init__(self, clock):
        super().__init__(clock)
        self.route_info = {"compute": "local_host"}
        self.worker_failed_for_request = True
        self.local_review_calls = []

    def local_review(self, question, draft, context, *, timeout):
        self.local_review_calls.append({"question": question, "draft": draft,
                                        "context": context, "timeout": timeout})
        self.clock.value += self.durations.pop(0) if self.durations else 0.1
        outcome = self.outcomes.pop(0) if self.outcomes else "A careful revised answer; uncertainty remains."
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, dict) or outcome is None:
            return outcome
        return {"ok": True, "role": "reviewer", "model": "qwen3:1.7b", "output": outcome}


class SpecialistTests(unittest.TestCase):
    def setUp(self):
        self.clock = FakeClock()
        self.worker = Worker(self.clock)
        timer = patch.object(specialists.time, "monotonic", self.clock.monotonic)
        timer.start()
        self.addCleanup(timer.stop)

    def coordinator(self, question="Compare these findings", *, config=None, sources=SOURCES, **kwargs):
        return SpecialistCoordinator(config or {}, self.worker, question,
            source_context=json.dumps({"sources": sources}), **kwargs)

    def test_simple_auto_questions_have_no_extra_passes_even_with_sources(self):
        for question in ("What's the most famous pirate ship?", "What is 2 plus 2?",
                         "Who voices Paarthurnax?"):
            with self.subTest(question=question):
                coordinator = self.coordinator(question, is_skyrim="Paarthurnax" in question)
                self.assertIsNone(coordinator.prepare())
                self.assertIsNone(coordinator.review("A substantive answer."))
        self.assertEqual(self.worker.calls, [])

    def test_default_research_and_skyrim_roles_then_reviewer(self):
        for options, role in (({}, "research"), ({"is_skyrim": True, "diagnostic": True}, "skyrim")):
            with self.subTest(role=role):
                self.worker.calls.clear()
                coordinator = self.coordinator(**options)
                self.assertIsNotNone(coordinator.prepare())
                self.assertIsNotNone(coordinator.review("Original careful answer.", sources=SOURCES))
                self.assertEqual([call["role"] for call in self.worker.calls], [role, "reviewer"])
                self.assertEqual(coordinator.applied_roles, [role, "reviewer"])
                self.assertEqual(self.worker.local_calls, 0)

    def test_generic_complex_and_explicit_deep_are_reviewer_only(self):
        for question in ("Evaluate a detailed study plan", "Use specialists to explain this idea"):
            with self.subTest(question=question):
                self.worker.calls.clear()
                coordinator = self.coordinator(question, sources=[])
                self.assertIsNone(coordinator.prepare())
                result = coordinator.review("A useful draft.")
                self.assertEqual(result["compute"], "remote_worker")
                self.assertEqual([call["role"] for call in self.worker.calls], ["reviewer"])

    def test_off_quick_self_description_application_and_fallback_skip(self):
        for question, config in (("Compare these studies quickly", {}),
                                 ("Use specialists, but no agents", {}),
                                 ("Compare these studies; no extra review", {}),
                                 ("Compare these studies without extra review", {}),
                                 ("Compare these studies; skip extra review", {}),
                                 ("Compare these studies; no second pass", {}),
                                 ("Compare these sources", {"specialist_mode": "off"}),
                                 ("Compare these sources", {"specialists_enabled": False}),
                                 ("What version are you?", {})):
            with self.subTest(question=question, config=config):
                coordinator = self.coordinator(question, config=config)
                self.assertIsNone(coordinator.prepare())
                self.assertIsNone(coordinator.review("Original answer."))
        for flags in ({"application_answer": True}, {"self_query": True}):
            self.assertIsNone(self.coordinator().review("Original answer.", **flags))
        self.worker.route_info = {"compute": "local_host"}
        self.assertIsNone(self.coordinator().prepare())
        self.assertIsNone(self.coordinator().review("Original answer."))
        self.worker.route_info = {"compute": "remote_worker"}
        self.worker.worker_failed_for_request = True
        self.assertIsNone(self.coordinator().review("Original answer."))
        self.assertEqual(self.worker.calls, [])
        self.assertEqual(self.worker.local_calls, 0)

    def test_flags_external_correction_and_hard_two_pass_limit(self):
        coordinator = self.coordinator(config={"specialist_research_enabled": False})
        self.assertIsNone(coordinator.prepare())
        self.assertIsNotNone(coordinator.review("Original draft."))
        self.worker.calls.clear()
        coordinator = self.coordinator(config={"specialist_max_passes": 999})
        self.assertIsNotNone(coordinator.prepare())
        coordinator.note_external_pass()
        self.assertIsNone(coordinator.review("Original draft."))
        self.assertEqual(len(self.worker.calls), 1)
        coordinator = self.coordinator(config={"specialist_reviewer_enabled": False})
        self.assertIsNone(coordinator.review("Original draft."))

    def test_failed_preparation_does_not_wait_for_the_same_unavailable_worker_again(self):
        for failure in (None, TimeoutError("Worker unavailable"),
                        {"ok": True, "role": "research", "model": "qwen3:8b", "output": "bad\ud800"}):
            with self.subTest(failure=type(failure).__name__):
                self.worker.calls.clear()
                self.worker.outcomes = [failure]
                coordinator = self.coordinator()
                self.assertIsNone(coordinator.prepare())
                self.assertIsNone(coordinator.review("Successful original answer.", sources=SOURCES))
                self.assertEqual(len(self.worker.calls), 1)
                self.assertEqual(coordinator.applied_roles, [])
    def test_budget_is_elapsed_optional_work_not_base_generation_time(self):
        self.worker.durations = [20, 10]
        coordinator = self.coordinator(config={"specialist_budget_seconds": 35})
        self.assertIsNotNone(coordinator.prepare())
        self.clock.value += 300  # Existing base inference is outside this extra-work budget.
        self.assertIsNotNone(coordinator.review("Original draft."))
        self.assertEqual([call["timeout"] for call in self.worker.calls], [25, 15])
        self.assertIsNone(coordinator.prepare())
        self.assertIsNone(coordinator.review("Another draft."))
        self.assertEqual(len(self.worker.calls), 2)

    def test_late_results_and_sub_two_second_remaining_budget_are_skipped(self):
        self.worker.durations = [16]
        coordinator = self.coordinator(config={"specialist_budget_seconds": 15})
        self.assertIsNone(coordinator.prepare())
        self.assertIsNone(coordinator.review("Original draft."))
        self.assertEqual(self.worker.calls[0]["timeout"], 15)
        self.assertEqual(coordinator.applied_roles, [])
        self.worker.calls.clear()
        coordinator = self.coordinator(config={"specialist_budget_seconds": 1.9})
        self.assertIsNone(coordinator.prepare())
        self.assertEqual(self.worker.calls, [])

    def test_budget_clamping_and_invalid_values(self):
        for budget, expected in ((999, 60), (float("inf"), 45), (None, 45), ("invalid", 45)):
            with self.subTest(budget=budget):
                coordinator = self.coordinator(config={"specialist_budget_seconds": budget})
                self.assertEqual(coordinator._budget, expected)
        coordinator = self.coordinator(config={"specialist_max_passes": 0})
        self.assertIsNone(coordinator.prepare())

    def test_failures_malformed_roles_models_outputs_and_tools_preserve_draft(self):
        good = {"ok": True, "role": "reviewer", "model": "qwen3:14b", "output": "Revised."}
        outcomes = [RuntimeError("private exception sentinel"), None, {**good, "ok": False},
                    {**good, "role": "arbitrary"}, {**good, "model": "invalid\nmodel"},
                    {**good, "model": "m" * 257}, {**good, "output": 42},
                    {**good, "output": "x" * 12001}, {**good, "output": "bad\x00body"},
                    {**good, "output": "unpaired surrogate \ud800"},
                    {**good, "tool_calls": [{"function": "workspace_write"}]}]
        for outcome in outcomes:
            with self.subTest(outcome=type(outcome).__name__):
                self.worker.outcomes = [outcome]
                coordinator = self.coordinator()
                self.assertIsNone(coordinator.review("Original draft."))
                self.assertEqual(coordinator.applied_roles, [])

    def test_reviewer_rejects_fabricated_or_removed_prose_references(self):
        draft = "The result remains uncertain. [1]\nSources: https://official.example/report"
        rejected = ["The result is certain. [9]", "The result remains uncertain. [1]",
                    "The result remains uncertain. Sources: https://official.example/report",
                    "The result remains uncertain. [1]\nSources: https://official.example/report\n"
                    "[Trial results](https://invented.example/study)",
                    "The result remains uncertain. `[1]`\nSources: https://official.example/report",
                    "The result remains uncertain. [1]\n`https://official.example/report`",
                    "The result remains uncertain. [1]\nSources: https://official.example/report\n"
                    "[Details](https://private:credential@example.test/report)"]
        for revised in rejected:
            with self.subTest(revised=revised):
                self.worker.outcomes = [revised]
                coordinator = self.coordinator()
                self.assertIsNone(coordinator.review(draft, sources=SOURCES))
                self.assertEqual(coordinator.applied_roles, [])

    def test_reviewer_accepts_citation_consolidation_url_equivalence_and_old_navigation(self):
        draft = ("It may help. [1] [1]\nSources: https://official.example/report#old\n"
                 "Open https://navigation.example/help for navigation.")
        revised = ("It may help. [1]\nSources: https://official.example/report#new\n"
                   "Open https://navigation.example/help for navigation.")
        self.worker.outcomes = [revised]
        coordinator = self.coordinator()
        self.assertEqual(coordinator.review(draft, sources=SOURCES)["answer"], revised)
        self.assertEqual(coordinator.applied_roles, ["reviewer"])
        self.worker.outcomes = ["A cautious answer without the invalid reference."]
        self.assertIsNotNone(self.coordinator().review("An unsupported claim. [9]", sources=SOURCES))

    def test_code_literals_are_ignored_and_reference_check_exceptions_keep_original(self):
        self.worker.outcomes = ["A clearer explanation. `array[999]`"]
        self.assertIsNotNone(self.coordinator().review("An explanation. `array[999]`"))
        with patch.object(specialists, "reference_issues", side_effect=RuntimeError("Check unavailable")):
            self.assertIsNone(self.coordinator().prepare())
            self.assertIsNone(self.coordinator().review("Original draft."))

    def test_research_notes_use_no_web_supplied_catalog_and_reject_new_references(self):
        coordinator = self.coordinator("Compare these sources; don't search the web.")
        self.worker.outcomes = ["This snippet is a lead, not a checked page. [1]"]
        self.assertIsNotNone(coordinator.prepare())
        context = self.worker.calls[-1]["context"]
        self.assertIn("user forbids web searching", context)
        self.assertIn('"page_fetched": false', context)
        self.assertIn("Preserve the user's constraints, uncertainty, caveats and lack of evidence", context)
        for notes in ("The result is verified. [9]", "[Research](https://invented.example/study)"):
            self.worker.outcomes = [notes]
            self.assertIsNone(self.coordinator().prepare())

    def test_bounded_context_keeps_evidence_notes_history_and_role_priority(self):
        for skyrim in (False, True):
            with self.subTest(skyrim=skyrim):
                self.worker.calls.clear()
                coordinator = self.coordinator("Analyse this evidence " + "q" * 5000,
                    is_skyrim=skyrim, diagnostic=skyrim,
                    user_context="runtime=1.6.1170; supplied image unclear; " + "u" * 20_000,
                    history_context="Earlier user topic, not verified assistant claims. " + "h" * 20_000)
                self.assertIsNotNone(coordinator.prepare())
                self.assertIsNotNone(coordinator.review("Original draft.", sources=SOURCES))
                for call in self.worker.calls:
                    self.assertLessEqual(len(call["question"]), 4000)
                    self.assertLessEqual(len(call["context"]), 16_000)
                    self.assertIn("runtime=1.6.1170", call["context"])
                    self.assertIn("Earlier user topic", call["context"])
                    self.assertIn("omitted", call["context"])
                    source = call["context"].index("SUPPLIED SOURCE CATALOG")
                    evidence = call["context"].index("CURRENT USER / ATTACHMENT EVIDENCE")
                    self.assertLess(evidence, source) if skyrim else self.assertLess(source, evidence)
                self.assertIn("UNVERIFIED EARLIER SPECIALIST NOTES", self.worker.calls[-1]["context"])
        count = len(self.worker.calls)
        self.assertIsNone(self.coordinator().review("x" * 12001))
        self.assertEqual(len(self.worker.calls), count)


class LaptopSpecialistTests(unittest.TestCase):
    coordinator = SpecialistTests.coordinator

    def setUp(self):
        SpecialistTests.setUp(self)
        self.worker = LocalReviewer(self.clock)

    def test_default_local_final_review_records_actual_route_model_and_role(self):
        statuses = []
        coordinator = self.coordinator(status_callback=statuses.append)
        self.assertIsNone(coordinator.prepare())
        self.worker.outcomes = ["The result remains uncertain. [1]"]
        result = coordinator.review("Original uncertain answer. [1]", sources=SOURCES)
        self.assertEqual(result, {"answer": "The result remains uncertain. [1]",
                                  "model": "qwen3:1.7b", "compute": "local_host"})
        self.assertEqual(coordinator.applied_roles, ["reviewer"])
        self.assertEqual(statuses, ["Laptop reviewer checking answer"])
        self.assertEqual(self.worker.local_review_calls[0]["timeout"], 10)
        self.assertEqual(self.worker.calls, [])
        self.assertIsNone(coordinator.review("Another draft."))
        self.assertEqual(len(self.worker.local_review_calls), 1)

    def test_plain_local_client_is_supported_but_unknown_hybrid_routes_are_not(self):
        del self.worker.route_info
        self.assertIsNotNone(self.coordinator().review("Original draft."))
        self.worker.local_review_calls.clear()
        self.worker.is_hybrid = True
        self.assertIsNone(self.coordinator().review("Original draft."))
        self.worker.route_info = {"compute": "unknown"}
        self.assertIsNone(self.coordinator().review("Original draft."))
        self.assertEqual(self.worker.local_review_calls, [])

    def test_local_auto_eligibility_and_opt_out_flags(self):
        eligible = [("Compare these findings", {}),
                    ("Evaluate a detailed study plan", {"sources": []}),
                    ("My Skyrim has a CTD", {"is_skyrim": True, "diagnostic": True}),
                    ("Use specialists to explain this idea", {"sources": []})]
        for question, options in eligible:
            with self.subTest(question=question):
                self.assertIsNotNone(self.coordinator(question, **options).review("Original draft."))
        count = len(self.worker.local_review_calls)
        for question in ("What's the most famous pirate ship?", "What is 2 plus 2?",
                         "Who voices Paarthurnax?", "Compare these sources quickly",
                         "Compare sources; no extra review", "Compare sources; no agents",
                         "Compare sources without extra review", "What version are you?",
                         "Which model are you running?"):
            with self.subTest(question=question):
                self.assertIsNone(self.coordinator(question).review("Original draft."))
        for config in ({"specialists_enabled": False}, {"specialist_mode": "off"},
                       {"specialist_mode": "unknown"}, {"laptop_review_enabled": False},
                       {"laptop_review_enabled": "true"}, {"laptop_review_mode": "off"},
                       {"laptop_review_mode": "unknown"}, {"specialist_reviewer_enabled": False},
                       {"specialist_max_passes": 0}):
            with self.subTest(config=config):
                self.assertIsNone(self.coordinator(config=config).review("Original draft."))
        for flags in ({"application_answer": True}, {"self_query": True}):
            self.assertIsNone(self.coordinator().review("Original draft.", **flags))
        self.assertEqual(len(self.worker.local_review_calls), count)

    def test_citation_correction_consumes_the_single_local_extra_pass(self):
        coordinator = self.coordinator()
        coordinator.note_external_pass()
        self.assertIsNone(coordinator.prepare())
        self.assertIsNone(coordinator.review("Citation repaired draft. [1]", sources=SOURCES))
        self.assertEqual(self.worker.local_review_calls, [])

    def test_pc_prepare_then_local_fallback_reuses_shared_remaining_budget(self):
        self.worker.route_info = {"compute": "remote_worker"}
        self.worker.worker_failed_for_request = False
        self.worker.durations = [20, 4]
        coordinator = self.coordinator(config={"specialist_budget_seconds": 25})
        self.assertIsNotNone(coordinator.prepare())
        self.worker.route_info = {"compute": "local_host"}
        self.worker.worker_failed_for_request = True
        self.assertIsNotNone(coordinator.review("Original draft."))
        self.assertEqual(coordinator.applied_roles, ["research", "reviewer"])
        self.assertEqual(self.worker.local_review_calls[-1]["timeout"], 5)
        self.assertEqual(len(self.worker.calls) + len(self.worker.local_review_calls), 2)
        self.assertIsNone(coordinator.review("Another draft."))

    def test_failed_pc_route_does_not_disable_later_local_review(self):
        for operation in ("prepare", "review"):
            with self.subTest(operation=operation):
                self.worker.calls.clear()
                self.worker.local_review_calls.clear()
                self.worker.route_info = {"compute": "remote_worker"}
                self.worker.worker_failed_for_request = False
                self.worker.outcomes = [TimeoutError("private worker sentinel")]
                coordinator = self.coordinator()
                failed = coordinator.prepare() if operation == "prepare" else coordinator.review("Draft.")
                self.assertIsNone(failed)
                self.assertIsNone(coordinator.review("Draft."))
                self.assertEqual(len(self.worker.calls), 1)
                self.worker.route_info = {"compute": "local_host"}
                self.worker.worker_failed_for_request = True
                result = coordinator.review("Successful original draft.")
                self.assertEqual(result["compute"], "local_host")
                self.assertEqual(coordinator.applied_roles, ["reviewer"])
                self.assertEqual(len(self.worker.local_review_calls), 1)

    def test_pc_route_never_uses_local_adapter_and_keeps_two_passes(self):
        self.worker.route_info = {"compute": "remote_worker"}
        self.worker.worker_failed_for_request = False
        coordinator = self.coordinator()
        self.assertIsNotNone(coordinator.prepare())
        self.assertEqual(coordinator.review("Original draft.")["compute"], "remote_worker")
        self.assertEqual([call["role"] for call in self.worker.calls], ["research", "reviewer"])
        self.assertEqual(self.worker.local_review_calls, [])

    def test_local_budget_limits_and_late_results_leave_original(self):
        for value, expected in ((999, 12), (float("inf"), 10), (None, 10), ("bad", 10)):
            with self.subTest(value=value):
                coordinator = self.coordinator(config={"laptop_review_budget_seconds": value})
                self.assertIsNotNone(coordinator.review("Original draft."))
                self.assertEqual(self.worker.local_review_calls[-1]["timeout"], expected)
        count = len(self.worker.local_review_calls)
        for config in ({"laptop_review_budget_seconds": 1.9},
                       {"specialist_budget_seconds": 1.9}):
            self.assertIsNone(self.coordinator(config=config).review("Original draft."))
        self.assertEqual(len(self.worker.local_review_calls), count)
        self.worker.durations = [10.1]
        coordinator = self.coordinator()
        self.assertIsNone(coordinator.review("Original draft."))
        self.assertIsNone(coordinator.review("Original draft."))
        self.assertEqual(coordinator.applied_roles, [])
        self.assertEqual(len(self.worker.local_review_calls), count + 1)

    def test_local_failure_malformed_output_and_references_preserve_original(self):
        original = "The result is uncertain. [1]\nSources: https://official.example/report"
        valid = {"ok": True, "role": "reviewer", "model": "qwen3:1.7b", "output": original}
        outcomes = [None, RuntimeError("private local sentinel"), {**valid, "role": "research"},
                    {**valid, "model": "invalid\nmodel"}, {**valid, "output": "bad\ud800"},
                    {**valid, "tool_calls": [{"function": "workspace_write"}]},
                    "A certain answer. [9]", "A certain answer. [1]",
                    original + "\n[Extra](https://invented.example/study)"]
        for outcome in outcomes:
            with self.subTest(outcome=type(outcome).__name__):
                self.worker.outcomes = [outcome]
                coordinator = self.coordinator()
                count = len(self.worker.local_review_calls)
                self.assertIsNone(coordinator.review(original, sources=SOURCES))
                self.assertIsNone(coordinator.review(original, sources=SOURCES))
                self.assertEqual(coordinator.applied_roles, [])
                self.assertEqual(len(self.worker.local_review_calls), count + 1)

    def test_local_context_prioritizes_real_evidence_and_preserves_full_draft(self):
        draft = "A full answer requiring review. " * 30
        for skyrim in (False, True):
            with self.subTest(skyrim=skyrim):
                coordinator = self.coordinator("Analyse this evidence; don't search the web.",
                    is_skyrim=skyrim, diagnostic=skyrim,
                    user_context="Parsed log: runtime=1.6.1170; not an established culprit. " + "u" * 9000,
                    history_context="Earlier user topic; assistant claims unverified. " + "h" * 9000)
                self.assertIsNone(coordinator.prepare())
                self.assertIsNotNone(coordinator.review(draft, sources=SOURCES))
                call = self.worker.local_review_calls[-1]
                self.assertEqual(call["draft"], draft)
                self.assertLessEqual(len(call["context"]), 6000)
                self.assertIn("runtime=1.6.1170", call["context"])
                self.assertIn('"content_origin": "search_snippet"', call["context"])
                self.assertIn("user forbids web searching", call["context"])
                self.assertIn("Earlier user topic", call["context"])
                self.assertIn("omitted", call["context"])
                source = call["context"].index("SUPPLIED SOURCE CATALOG")
                evidence = call["context"].index("CURRENT USER / ATTACHMENT EVIDENCE")
                history = call["context"].index("RECENT CHAT CONTEXT")
                self.assertLess(evidence, source) if skyrim else self.assertLess(source, evidence)
                self.assertGreater(history, max(source, evidence))
        count = len(self.worker.local_review_calls)
        self.assertIsNone(self.coordinator().review("x" * 12001))
        self.assertEqual(len(self.worker.local_review_calls), count)


if __name__ == "__main__":
    unittest.main()
