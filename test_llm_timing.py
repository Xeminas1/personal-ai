from __future__ import annotations

import logging
import re
import unittest
from unittest.mock import patch

from app.llm import OllamaClient, OllamaError


class LlmTimingTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.getLogger(f"test_llm_timing.{self.id()}")
        self.client = OllamaClient(
            "https://worker.invalid",
            "qwen3:8b",
            self.logger,
            extra_headers={"Authorization": "Bearer private-worker-key"},
            provider_name="hybrid_worker",
        )

    @staticmethod
    def timing_fields(records):
        events = [record.getMessage() for record in records if record.getMessage().startswith("LLM timing |")]
        if len(events) != 1:
            raise AssertionError(f"Expected one timing event, received {len(events)}")
        return events[0], dict(re.findall(r"(\w+)=(\S+)", events[0]))

    def test_preserves_response_and_request_with_model_timings(self):
        messages = [{"role": "user", "content": "private-user-prompt"}]
        tools = [{"type": "function", "function": {"name": "lookup"}}]
        response = {
            "model": "qwen3:8b",
            "message": {
                "content": "private-answer",
                "thinking": "private-internal-thinking",
                "tool_calls": [{"function": {"name": "lookup"}}],
            },
            "load_duration": 1_250_900_000,
            "prompt_eval_duration": 2_100_000_000,
            "eval_duration": 6_500_000_000,
            "total_duration": 10_000_000_000,
            "prompt_eval_count": 2048,
            "eval_count": 120,
            "done": True,
        }
        with patch.object(self.client, "_request", return_value=response) as request:
            with patch("app.llm.time.monotonic", side_effect=[10.0, 20.25]):
                with self.assertLogs(self.logger, level="INFO") as captured:
                    result = self.client.chat_raw(messages, json_mode=True, tools=tools)

        self.assertIs(result, response)
        self.assertEqual(result["message"]["thinking"], "private-internal-thinking")
        request.assert_called_once_with("/api/chat", payload={
            "model": "qwen3:8b", "messages": messages, "stream": False,
            "format": "json", "tools": tools,
        })
        event, fields = self.timing_fields(captured.records)
        self.assertEqual(fields["elapsed_ms"], "10250")
        self.assertEqual(fields["load_ms"], "1250")
        self.assertEqual(fields["prompt_ms"], "2100")
        self.assertEqual(fields["generation_ms"], "6500")
        self.assertEqual(fields["total_ms"], "10000")
        self.assertEqual(fields["prompt_tokens"], "2048")
        self.assertEqual(fields["generated_tokens"], "120")
        self.assertEqual(fields["thinking_chars"], str(len("private-internal-thinking")))
        self.assertEqual(fields["tool_calls"], "1")
        self.assertEqual(fields["success"], "True")
        for private_value in ("private-user-prompt", "private-answer", "private-internal-thinking", "private-worker-key"):
            self.assertNotIn(private_value, event)

    def test_missing_metrics_do_not_change_a_valid_text_reply(self):
        response = {"message": {"content": "Ready."}}
        with patch.object(self.client, "_request", return_value=response):
            with self.assertLogs(self.logger, level="INFO") as captured:
                self.assertEqual(self.client.chat([]), "Ready.")
        _, fields = self.timing_fields(captured.records)
        for name in ("load_ms", "prompt_ms", "generation_ms", "total_ms", "prompt_tokens", "generated_tokens"):
            self.assertEqual(fields[name], "-1")
        self.assertEqual(fields["thinking_chars"], "0")
        self.assertEqual(fields["tool_calls"], "0")

    def test_malformed_metrics_cannot_break_a_valid_reply(self):
        for invalid in (None, True, False, -1, -1.0, "123", float("nan"), float("inf"), {}, []):
            with self.subTest(metric=repr(invalid)):
                response = {
                    "message": {"content": "Still usable.", "thinking": {"private": "thought"}},
                    **{key: invalid for key in (
                        "load_duration", "prompt_eval_duration", "eval_duration", "total_duration",
                        "prompt_eval_count", "eval_count",
                    )},
                }
                with patch.object(self.client, "_request", return_value=response):
                    with self.assertLogs(self.logger, level="INFO") as captured:
                        self.assertIs(self.client.chat_raw([]), response)
                event, fields = self.timing_fields(captured.records)
                for name in ("load_ms", "prompt_ms", "generation_ms", "total_ms", "prompt_tokens", "generated_tokens", "thinking_chars"):
                    self.assertEqual(fields[name], "-1")
                self.assertEqual(fields["success"], "True")
                self.assertNotIn("thought", event)

    def test_failure_logs_elapsed_time_and_preserves_original_error(self):
        failure = OllamaError("private-error-with-worker-key")
        with patch.object(self.client, "_request", side_effect=failure):
            with patch("app.llm.time.monotonic", side_effect=[3.0, 3.5]):
                with self.assertLogs(self.logger, level="INFO") as captured:
                    with self.assertRaises(OllamaError) as raised:
                        self.client.chat_raw([{"role": "user", "content": "private-user-prompt"}])
        self.assertIs(raised.exception, failure)
        event, fields = self.timing_fields(captured.records)
        self.assertEqual(fields["elapsed_ms"], "500")
        self.assertEqual(fields["success"], "False")
        for name in ("load_ms", "prompt_ms", "generation_ms", "total_ms", "prompt_tokens", "generated_tokens", "thinking_chars", "tool_calls"):
            self.assertEqual(fields[name], "-1")
        self.assertNotIn("private-error", event)
        self.assertNotIn("private-user-prompt", event)
        self.assertNotIn("private-worker-key", event)

    def test_empty_response_validation_still_marks_failure(self):
        with patch.object(self.client, "_request", return_value={"message": {"content": ""}}):
            with self.assertLogs(self.logger, level="INFO") as captured:
                with self.assertRaisesRegex(OllamaError, "empty response"):
                    self.client.chat_raw([])
        _, fields = self.timing_fields(captured.records)
        self.assertEqual(fields["success"], "False")


if __name__ == "__main__":
    unittest.main()
