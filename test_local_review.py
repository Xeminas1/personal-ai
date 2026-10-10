"""Optional laptop review uses one existing local model and bounded evidence."""
from __future__ import annotations

import copy
import json
import logging
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import llm
from app.hybrid import HybridOllamaClient, HybridWorkerClient
from app.llm import OllamaClient


class LocalModelHandler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
        self.server.requests.append((self.path, body))
        raw = json.dumps(self.server.response).encode("utf-8")
        self.send_response(self.server.response_status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class LocalReviewTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger(self.id())
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), LocalModelHandler)
        self.server.requests = []
        self.server.response_status = 200
        self.server.response = self.response()
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.client = OllamaClient(
            f"http://127.0.0.1:{self.server.server_port}", "qwen3:1.7b", self.logger,
            extra_headers={"Authorization": "Bearer private-model-credential"},
        )

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    @staticmethod
    def response(**changes):
        value = {"model": "qwen3:1.7b", "done": True, "done_reason": "stop",
                 "message": {"role": "assistant", "content": "The finding is uncertain [S1]."}}
        value.update(changes)
        return value

    def review(self, **changes):
        arguments = {"question": "Assess this finding", "draft": "Original answer [S1].",
                     "context": "[S1] The supplied source reports uncertainty."}
        arguments.update(changes)
        return self.client.local_review(**arguments)

    def hybrid(self):
        worker = HybridWorkerClient("https://worker.invalid", "private-worker-credential", "qwen3:8b", self.logger)
        hybrid = HybridOllamaClient(local_client=self.client, worker_client=worker,
            logger=self.logger, local_fallback_model="qwen3:1.7b")
        hybrid.refresh_route = Mock(side_effect=AssertionError("Local review must not refresh routing"))
        worker._request = Mock(side_effect=AssertionError("Local review must not call the PC"))
        return hybrid

    @staticmethod
    def route_snapshot(hybrid):
        return (hybrid.active_client, hybrid.model, hybrid.local_client.model,
                hybrid.worker_client.model, hybrid.worker_failed_for_request, copy.deepcopy(hybrid.route_info))

    def test_real_http_uses_selected_local_model_and_evidence_without_tools_or_discovery(self):
        self.server.response["model"] = "qwen3:1.7b:latest"
        with patch.object(self.client, "discover_runtime_model", side_effect=AssertionError("No discovery")), \
             patch.object(self.client, "installed_models", side_effect=AssertionError("No inventory")):
            result = self.review()
        self.assertEqual(result, {"ok": True, "role": "reviewer", "model": "qwen3:1.7b:latest",
                                  "output": "The finding is uncertain [S1]."})
        self.assertEqual(self.client.model, "qwen3:1.7b")
        self.assertEqual(len(self.server.requests), 1)
        path, request = self.server.requests[0]
        self.assertEqual(path, "/api/chat")
        self.assertEqual(request["model"], "qwen3:1.7b")
        self.assertFalse(request["think"])
        self.assertFalse(request["stream"])
        self.assertEqual(request["options"], {"num_ctx": 4096, "num_predict": 384})
        self.assertNotIn("tools", request)
        self.assertNotIn("format", request)
        prompt = json.loads(request["messages"][1]["content"])
        self.assertEqual(prompt["question"], "Assess this finding")
        self.assertEqual(prompt["draft"], "Original answer [S1].")
        self.assertIn("[S1]", prompt["context"])
        self.assertEqual(prompt["context_omitted_chars"], 0)
        self.assertIn("untrusted data", request["messages"][0]["content"])

    def test_only_supporting_context_is_trimmed_and_json_utf8_size_is_bounded(self):
        question = "Compare café findings"
        draft = "A short complete draft with its final qualification [S1]."
        context = "[S1] Evidence first.\n" + "漢字\n\"quoted\" " * 700
        self.assertLessEqual(len(context), 16000)
        self.assertIsNotNone(self.review(question=question, draft=draft, context=context))
        messages = self.server.requests[-1][1]["messages"]
        prompt = json.loads(messages[1]["content"])
        self.assertEqual(prompt["question"], question)
        self.assertEqual(prompt["draft"], draft)
        self.assertTrue(context.startswith(prompt["context"]))
        self.assertTrue(prompt["context"].startswith("[S1] Evidence first."))
        self.assertGreater(prompt["context_omitted_chars"], 0)
        self.assertEqual(prompt["context_omitted_chars"], len(context) - len(prompt["context"]))
        self.assertLessEqual(sum(len(message["content"].encode("utf-8")) for message in messages), 3500)
        # A long core is skipped intact instead of silently losing draft tail.
        count = len(self.server.requests)
        self.assertIsNone(self.review(draft="Complete " + "d" * 4000 + " final qualification."))
        self.assertEqual(len(self.server.requests), count)

    def test_invalid_inputs_and_small_budgets_skip_before_any_request(self):
        for changes in ({"question": ""}, {"question": []}, {"question": "q" * 4001},
                        {"draft": ""}, {"draft": False}, {"draft": "d" * 12001},
                        {"context": None}, {"context": "c" * 16001}, {"context": "bad\x00text"},
                        {"draft": "bad\udfff"}, {"timeout": True}, {"timeout": "10"},
                        {"timeout": 1.9}, {"timeout": float("nan")}, {"timeout": float("inf")},
                        {"timeout": 10**1000}):
            with self.subTest(changes=list(changes)):
                self.assertIsNone(self.review(**changes))
        self.assertEqual(self.server.requests, [])

    def test_actual_model_must_match_the_captured_request_and_never_changes_selection(self):
        for actual_model in ("qwen3:8b", "", None, "bad model", "qwen3:1.7b\ud800"):
            with self.subTest(model=repr(actual_model)):
                self.server.response = self.response(model=actual_model)
                self.assertIsNone(self.review())
                self.assertEqual(self.server.requests[-1][1]["model"], "qwen3:1.7b")
                self.assertEqual(self.client.model, "qwen3:1.7b")

        def changed_model(_path, *, payload, timeout):
            self.assertEqual(payload["model"], "qwen3:1.7b")
            self.client.model = "qwen3:4b"
            return self.response()

        with patch.object(self.client, "_request", side_effect=changed_model):
            self.assertIsNone(self.review())
        self.assertEqual(self.client.model, "qwen3:4b")

    def test_incomplete_tool_oversized_or_unsafe_http_responses_preserve_the_draft(self):
        invalid = [self.response(done=False), self.response(done_reason="length"),
                   self.response(stop_reason="max_tokens"), self.response(finish_reason="token_limit"),
                   self.response(error="private-provider-error"), self.response(message={}),
                   self.response(message={"content": ""}), self.response(message={"content": []}),
                   self.response(message={"role": "tool", "content": "Text"}),
                   self.response(message={"content": "Text", "tool_calls": [{"function": {"name": "private-tool"}}]})]
        invalid += [self.response(message={"content": value}) for value in (
            "a" * 4001, "private-answer\x00tail", "private-answer\x85tail", "private-answer\ud800",
        )]
        for response in invalid:
            with self.subTest(response_keys=list(response)):
                self.server.response = response
                self.assertIsNone(self.review())
                self.assertEqual(self.client.model, "qwen3:1.7b")
        qualification = " Final qualification."
        output = "a" * (4000 - len(qualification)) + qualification
        self.server.response = self.response(message={"content": output})
        self.assertEqual(self.review()["output"], output)

    def test_network_failure_keeps_logs_numeric_and_private(self):
        self.server.response_status = 500
        self.server.response = {"error": "private-provider-body"}
        with self.assertLogs(self.logger, level="INFO") as captured:
            self.assertIsNone(self.review(question="private-question", draft="private-draft", context="private-context"))
        self.assertEqual(len(captured.records), 1)
        event = captured.records[0].getMessage()
        self.assertRegex(event, r"^Local review \| elapsed_ms=\d+ success=False$")
        for secret in ("private-provider-body", "private-question", "private-draft", "private-context", "private-model-credential"):
            self.assertNotIn(secret, event)

    def test_generation_budget_accounts_for_prompt_work_and_discards_late_results(self):
        clock = SimpleNamespace(value=10.0)
        timer = SimpleNamespace(monotonic=lambda: clock.value)
        compose = llm._local_review_prompt

        def slow_prompt(*args):
            clock.value += 0.25
            return compose(*args)

        def late_request(_path, *, payload, timeout):
            self.assertAlmostEqual(timeout, 1.75)
            clock.value += 1.8
            return self.response()

        with patch.object(llm, "time", timer), patch.object(llm, "_local_review_prompt", side_effect=slow_prompt), \
             patch.object(self.client, "_request", side_effect=late_request):
            with self.assertLogs(self.logger, level="INFO") as captured:
                self.assertIsNone(self.review(timeout=2))
        self.assertIn("elapsed_ms=2050", captured.records[0].getMessage())

        clock.value = 20
        with patch.object(llm, "time", timer), patch.object(self.client, "_request", return_value=self.response()) as request:
            self.assertIsNotNone(self.review(timeout=100))
            self.assertEqual(request.call_args.kwargs["timeout"], 12)
            request.reset_mock()
            self.assertIsNotNone(self.review())
            self.assertEqual(request.call_args.kwargs["timeout"], 10)

    def test_hybrid_fallback_review_preserves_route_and_uses_local_model(self):
        hybrid = self.hybrid()
        hybrid.worker_failed_for_request = True
        original = self.route_snapshot(hybrid)
        result = hybrid.local_review("Assess this finding", "Draft [S1].", "[S1] Evidence", timeout=2)
        self.assertEqual(result["model"], "qwen3:1.7b")
        self.assertEqual(self.route_snapshot(hybrid), original)
        hybrid.refresh_route.assert_not_called()
        hybrid.worker_client._request.assert_not_called()
        self.server.response = self.response(done_reason="length")
        self.assertIsNone(hybrid.local_review("Question", "Draft", "Context", timeout=2))
        self.assertEqual(self.route_snapshot(hybrid), original)

    def test_hybrid_selected_worker_and_inconsistent_route_never_review_on_laptop(self):
        hybrid = self.hybrid()
        for active_client, compute in ((hybrid.worker_client, "remote_worker"),
                                       (hybrid.local_client, "remote_worker"),
                                       (hybrid.worker_client, "local_host")):
            with self.subTest(compute=compute):
                hybrid.active_client = active_client
                hybrid.route_info["compute"] = compute
                hybrid.model = "qwen3:8b"
                original = self.route_snapshot(hybrid)
                self.assertIsNone(hybrid.local_review("Question", "Draft", "Context", timeout=2))
                self.assertEqual(self.route_snapshot(hybrid), original)
        self.assertEqual(self.server.requests, [])
        hybrid.refresh_route.assert_not_called()
        hybrid.worker_client._request.assert_not_called()

    def test_failed_worker_replays_compact_answer_rules_with_complete_tool_history(self):
        hybrid = self.hybrid()
        hybrid.active_client = hybrid.worker_client
        hybrid.model = "qwen3:8b"
        hybrid.route_info["compute"] = "remote_worker"
        original_system = "Large PC answer rules " + "x" * 13000
        hybrid.answer_system_prompt_origin = original_system
        hybrid.local_system_prompt = "Compact trusted laptop answer rules."
        hybrid.local_answer_context = "Supplied evidence: preserve [S1] and uncertainty."
        messages = [
            {"role": "system", "content": original_system, "name": "initial_rules"},
            {"role": "system", "content": "Attachment evidence, retain unchanged."},
            {"role": "user", "content": "Earlier question"},
            {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "lookup", "arguments": {"claim": "test"}}}]},
            {"role": "tool", "tool_name": "lookup", "content": "[S1] Current supplied result"},
            {"role": "user", "content": "Assess the actual latest question"},
        ]
        original = copy.deepcopy(messages)
        tools = [{"type": "function", "function": {"name": "lookup"}}]
        with patch.object(hybrid.worker_client, "chat_raw", side_effect=TimeoutError("Offline")) as remote, \
             patch.object(self.client, "discover_runtime_model", return_value={"model": "qwen3:1.7b", "source": "test"}):
            hybrid.chat_raw(messages, json_mode=True, tools=tools)
        self.assertEqual(remote.call_args.args[0], original)
        self.assertEqual(remote.call_args.kwargs, {"json_mode": True, "tools": tools})
        local = self.server.requests[-1][1]
        self.assertEqual(local["model"], "qwen3:1.7b")
        self.assertEqual(local["format"], "json")
        self.assertEqual(local["tools"], tools)
        self.assertEqual(local["messages"][0], {"role": "system", "content": hybrid.local_system_prompt, "name": "initial_rules"})
        self.assertEqual(local["messages"][1:-1], original[1:])
        self.assertEqual(local["messages"][-1], {"role": "system", "content": hybrid.local_answer_context})
        self.assertEqual(messages, original)

    def test_selected_local_answer_adapter_is_idempotent_across_tool_rounds(self):
        hybrid = self.hybrid()
        hybrid.worker_failed_for_request = True
        hybrid.answer_system_prompt_origin = "Original answer rules."
        hybrid.local_system_prompt = "Compact trusted answer rules."
        hybrid.local_answer_context = "Evidence checklist [S1]."
        messages = [{"role": "system", "content": hybrid.local_system_prompt},
                    {"role": "user", "content": "Current question"},
                    {"role": "system", "content": hybrid.local_answer_context}]
        original = copy.deepcopy(messages)
        hybrid.chat_raw(messages)
        first = self.server.requests[-1][1]["messages"]
        self.assertEqual(first, original)
        continued = first + [{"role": "assistant", "tool_calls": [{"function": {"name": "lookup"}}]},
                             {"role": "tool", "content": "Evidence result"}]
        continued_original = copy.deepcopy(continued)
        hybrid.chat_raw(continued)
        self.assertEqual(self.server.requests[-1][1]["messages"], continued_original)
        self.assertEqual(continued, continued_original)
        self.assertEqual(sum(message.get("content") == hybrid.local_answer_context for message in continued), 1)
        hybrid.refresh_route.assert_not_called()

    def test_successful_worker_receives_original_primary_prompt_with_adapter_attributes(self):
        hybrid = self.hybrid()
        hybrid.active_client = hybrid.worker_client
        hybrid.route_info["compute"] = "remote_worker"
        hybrid.answer_system_prompt_origin = "Full PC answer rules."
        hybrid.local_system_prompt = "Compact local answer rules."
        hybrid.local_answer_context = "Compact evidence checklist."
        messages = [{"role": "system", "content": hybrid.answer_system_prompt_origin},
                    {"role": "user", "content": "Current user question"}]
        original = copy.deepcopy(messages)
        with patch.object(hybrid.worker_client, "chat_raw", return_value=self.response(model="qwen3:8b")) as remote:
            hybrid.chat_raw(messages)
        self.assertEqual(remote.call_args.args[0], original)
        self.assertEqual(messages, original)
        self.assertEqual(self.server.requests, [])

    def test_origin_binding_preserves_memory_extraction_unbound_and_absent_attributes(self):
        hybrid = self.hybrid()
        hybrid.worker_failed_for_request = True
        hybrid.answer_system_prompt_origin = "Original answer rules."
        hybrid.local_system_prompt = "Compact answer rules."
        hybrid.local_answer_context = "Evidence checklist."
        memory = [{"role": "system", "content": "Extract memories using the required JSON schema."},
                  {"role": "user", "content": "Private conversation to extract"}]
        original = copy.deepcopy(memory)
        hybrid.chat_raw(memory, json_mode=True)
        self.assertEqual(self.server.requests[-1][1]["messages"], original)
        self.assertEqual(memory, original)
        user_only = [{"role": "user", "content": "Question without an initial system"}]
        hybrid.chat_raw(user_only)
        self.assertEqual(self.server.requests[-1][1]["messages"], user_only)
        hybrid.local_system_prompt = None
        hybrid.local_answer_context = ""
        answer = [{"role": "system", "content": hybrid.answer_system_prompt_origin},
                  {"role": "user", "content": "Current question"}]
        hybrid.chat_raw(answer)
        self.assertEqual(self.server.requests[-1][1]["messages"], answer)
        # A missing origin or initial system must not turn unrelated calls into
        # answer requests even if an adapter value was left on the client.
        hybrid.local_system_prompt = "Compact answer rules."
        hybrid.local_answer_context = "Evidence checklist."
        del hybrid.answer_system_prompt_origin
        hybrid.chat_raw(answer)
        self.assertEqual(self.server.requests[-1][1]["messages"], answer)
        for name in ("local_system_prompt", "local_answer_context"):
            delattr(hybrid, name)
        hybrid.chat_raw(answer)
        self.assertEqual(self.server.requests[-1][1]["messages"], answer)


if __name__ == "__main__":
    unittest.main()
