"""Bounded XemAi / ChatGPT GitHub dialogue security tests (no network/model)."""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app.github_bridge import load_state, save_state, setup, chat_command
from app.github_bridge_auto import (
    AUTO_MAX_PER_DAY, AUTO_MAX_TOTAL, AUTO_COOLDOWN_SECONDS,
    AUTO_POLL_SECONDS, _safe_output, enable, disable, status, tick, transcript,
    model_provenance, _route_prompt,
)


class FakeGitHub:
    def __init__(self):
        self.private = True
        self.entries = [
            {"id": 123, "body":
             "Hello XemAi — ChatGPT here. Investigate the source trace "
             "and propose one read-only benchmark before proposing a fix.",
             "user": {"login": "Xeminas1"}}
        ]
        self.posted = []

    def verify_private(self, repo):
        if not self.private:
            from app.github_bridge import BridgeError
            raise BridgeError("The destination is not private.")

    def comments(self, repo, issue):
        return list(self.entries)

    def post_auto_comment(self, repo, issue, content, provenance=None):
        details = provenance or {}
        body = (
            "XemAi autonomous response (opt-in, read-only):\n"
            f"Model: {details.get('model', 'unknown')}\n"
            f"Compute: {details.get('compute', 'unknown')}\n"
            f"Discussion mode: {details.get('mode', 'unknown')}\n\n"
            + content
        )
        self.posted.append((repo, issue, body))
        self.entries.append({"id": 200 + len(self.posted), "body": body})
        return f"https://github.com/{repo}/issues/{issue}#issuecomment-test"


class FakeLLM:
    def __init__(self, response=None, callback=None):
        self.response = response or (
            "The first benchmark should separately check whether the attached "
            "source excerpts were read, whether numbered answers were generated, "
            "and whether validation wrongly rejected a grounded answer."
        )
        self.callback = callback
        self.messages = []

    def chat(self, messages):
        self.messages.append(messages)
        if self.callback:
            self.callback()
        return self.response


class DialogueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / "data"
        self.api = FakeGitHub()
        # Give setup() a fake API to avoid any GitHub network call.
        setup(self.data, "Example/private-dialogue", "fake-secret-token-value",
              client=self.api)
        state = load_state(self.data)
        state["issue_number"] = 1
        save_state(self.data, state)
        self.patch_client = patch("app.github_bridge_auto._get_client",
                                  return_value=self.api)
        self.patch_client.start()
        self.addCleanup(self.patch_client.stop)
        self.now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)

    def test_model_identity_is_host_supplied_and_adaptive(self):
        class Route:
            is_hybrid = True
            def __init__(self, name, compute):
                self.model = name
                self.route_info = {"compute": compute}
        laptop = model_provenance(Route("qwen3:1.7b", "local_host"))
        self.assertEqual(laptop, {
            "model": "qwen3:1.7b",
            "compute": "local_host",
            "mode": "guided-small-model",
        })
        self.assertIn("ONE point at a time", _route_prompt(laptop))
        worker = model_provenance(Route("qwen3.5:9b-q8_0", "remote_worker"))
        self.assertEqual(worker["mode"], "advanced-worker")
        self.assertIn("multiple", _route_prompt(worker))
        self.assertEqual(model_provenance(Route(
            "qwen3.5:9b-q8_0", "local_host"))["mode"], "standard-local")

    def test_actual_fallback_model_is_reported_not_initial_worker(self):
        self.assertIn("ENABLED", enable(self.data))

        class HybridFallback(FakeLLM):
            is_hybrid = True
            model = "qwen3.5:9b-q8_0"
            route_info = {"compute": "remote_worker"}

            def refresh_route(self):
                return dict(self.route_info)

            def chat(self, messages):
                self.messages.append(messages)
                self.route_info = {"compute": "local_host"}
                self.model = "qwen3:1.7b"
                return self.response

        llm = HybridFallback()
        result = tick(self.data, client=self.api, now=self.now,
                      llm_factory=lambda: llm)
        self.assertEqual(result["status"], "posted")
        self.assertEqual(result["provenance"]["model"], "qwen3:1.7b")
        self.assertEqual(result["provenance"]["mode"], "guided-small-model")
        self.assertEqual(len(llm.messages), 2)
        self.assertIn("ONE point at a time", llm.messages[1][0]["content"])
        self.assertIn("Model: qwen3:1.7b", self.api.posted[0][2])

    def test_default_off_and_user_opt_in_only(self):
        self.assertEqual(tick(self.data, client=self.api, now=self.now)["status"],
                         "disabled")
        self.assertFalse(self.api.posted)
        answer = chat_command("bridge auto on", self.data)
        self.assertIn("ENABLED", answer)
        self.assertTrue(load_state(self.data)["auto_enabled"])
        self.assertIn("ON", chat_command("bridge auto status", self.data))
        self.assertIn("DISABLED", chat_command("bridge auto off", self.data))
        self.assertFalse(load_state(self.data)["auto_enabled"])

    def test_single_reply_and_no_echo_loop(self):
        self.assertIn("ENABLED", enable(self.data))
        llm = FakeLLM()
        result = tick(self.data, client=self.api,
                      llm_factory=lambda: llm, now=self.now)
        self.assertEqual(result["status"], "posted")
        self.assertEqual(len(self.api.posted), 1)
        self.assertIn("XemAi autonomous response", self.api.posted[0][2])
        self.assertIn("UNTRUSTED GitHub comment 123", llm.messages[0][1]["content"])
        result = tick(self.data, client=self.api,
                      llm_factory=lambda: FakeLLM(), now=self.now+timedelta(hours=1))
        self.assertEqual(result["status"], "no_new_reply")
        self.assertEqual(len(self.api.posted), 1)

    def test_privacy_rechecked_and_disabling_mid_inference(self):
        enable(self.data)
        self.api.private = False
        self.assertEqual(tick(self.data, client=self.api, now=self.now)["status"],
                         "network_error")
        self.assertFalse(self.api.posted)
        self.api.private = True
        def change_settings():
            disable(self.data)
        r = tick(self.data, client=self.api, now=self.now,
                 llm_factory=lambda: FakeLLM(callback=change_settings))
        self.assertEqual(r["status"], "disabled_before_post")
        self.assertFalse(self.api.posted)

    def test_refuses_secrets_and_unsolicited_files(self):
        self.assertFalse(_safe_output("github_pat_SECRET12345678901234567890"))
        self.assertFalse(_safe_output("Read the secret at C:\\Users\\Public\\Secrets.dat and fix it"))
        self.assertFalse(_safe_output("Email an update to info@example.com right now please."))
        enable(self.data)
        r = tick(self.data, client=self.api, now=self.now,
                 llm_factory=lambda: FakeLLM(response=
                   "My user is at C:\\Users\\Reece\\secrets.txt; here is the file."))
        self.assertEqual(r["status"], "output_rejected")
        self.assertFalse(self.api.posted)

    def test_short_natural_replies_are_allowed_without_weakening_privacy(self):
        self.assertTrue(_safe_output("Sounds good — let's choose option two."))
        self.assertTrue(_safe_output("Sure!"))
        self.assertFalse(_safe_output("NO_REPLY"))
        self.assertFalse(_safe_output(""))
        self.assertFalse(_safe_output("x"))
        self.assertFalse(_safe_output("github_pat_SECRET12345678901234567890"))
        enable(self.data)
        result = tick(self.data, client=self.api, now=self.now,
                      llm_factory=lambda: FakeLLM(
                          response="Sounds good — let's choose option two."))
        self.assertEqual(result["status"], "posted")
        self.assertIn("Sounds good — let's choose option two.", self.api.posted[0][2])

    def test_poll_diagnostics_report_attempts_and_safe_failure_codes(self):
        self.assertIn("No polling attempt recorded", status(self.data))
        enable(self.data)
        result = tick(self.data, client=self.api, now=self.now,
                      llm_factory=lambda: FakeLLM())
        self.assertEqual(result["status"], "posted")
        state = load_state(self.data)
        self.assertEqual(state["auto_last_poll_status"], "posted")
        self.assertEqual(state["auto_last_poll_at"], self.now.isoformat(timespec="seconds"))
        self.assertEqual(state["auto_last_github_read_at"], self.now.isoformat(timespec="seconds"))
        self.assertIn("Last polling attempt:", status(self.data))
        self.assertIn("Last successful private GitHub read", status(self.data))
        self.api.private = False
        failed = tick(self.data, client=self.api,
                      now=self.now + timedelta(minutes=1))
        self.assertEqual(failed["status"], "network_error")
        state = load_state(self.data)
        self.assertEqual(state["auto_last_poll_status"], "network_error")
        self.assertEqual(state["auto_last_github_read_at"], self.now.isoformat(timespec="seconds"))
        self.assertIn("result=network_error", status(self.data))

    def test_daily_caps_and_total_limit(self):
        enable(self.data)
        state = load_state(self.data)
        state["auto_day"] = "2026-10-12"
        state["auto_today"] = AUTO_MAX_PER_DAY
        save_state(self.data, state)
        self.assertEqual(tick(self.data, client=self.api, now=self.now)["status"],
                         "daily_limit")
        state = load_state(self.data)
        state["auto_total"] = AUTO_MAX_TOTAL
        state["auto_today"] = 0
        save_state(self.data, state)
        self.assertEqual(tick(self.data, client=self.api, now=self.now)["status"],
                         "total_limit")
        self.assertFalse(load_state(self.data)["auto_enabled"])

    def test_faster_polling_and_reasonable_rate_limits(self):
        self.assertEqual(AUTO_POLL_SECONDS, 15)
        self.assertEqual(AUTO_COOLDOWN_SECONDS, 120)
        self.assertEqual(AUTO_MAX_PER_DAY, 48)
        self.assertEqual(AUTO_MAX_TOTAL, 500)
        message = enable(self.data)
        self.assertIn("48 short read-only replies", message)
        self.assertIn("2 minutes", message)

    def test_two_minute_cooldown_only_after_new_external_comment(self):
        enable(self.data)
        first = tick(self.data, client=self.api, now=self.now,
                     llm_factory=lambda: FakeLLM())
        self.assertEqual(first["status"], "posted")
        self.api.entries.append({
            "id": 401, "body":
            "Thanks XemAi. What concrete evidence would distinguish the "
            "source parser from the model's reasoning as the cause?",
            "user": {"login": "Xeminas1"},
        })
        cooldown = tick(self.data, client=self.api,
                        now=self.now + timedelta(seconds=60),
                        llm_factory=lambda: FakeLLM())
        self.assertEqual(cooldown["status"], "cooldown")
        self.assertEqual(len(self.api.posted), 1)
        ready = tick(self.data, client=self.api,
                     now=self.now + timedelta(seconds=121),
                     llm_factory=lambda: FakeLLM())
        self.assertEqual(ready["status"], "posted")
        self.assertEqual(len(self.api.posted), 2)

    def test_transcript_visible_without_changes(self):
        output = transcript(self.data, client=self.api)
        self.assertIn("private-dialogue/issues/1", output)
        self.assertIn("ChatGPT here", output)
        self.assertIn("UNTRUSTED", output)
        self.assertEqual(len(self.api.posted), 0)

    def test_old_issue_cannot_be_auto_posted_when_new_issue_selected(self):
        enable(self.data)
        state = load_state(self.data)
        state["issue_number"] = 2
        save_state(self.data, state)
        self.assertEqual(tick(self.data, client=self.api, now=self.now)["status"],
                         "issue_changed")
        self.assertFalse(self.api.posted)


if __name__ == "__main__":
    unittest.main()
