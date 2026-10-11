"""Technology Watch follow-up grounding, release scoring and server restart tests."""
from __future__ import annotations

import json
import logging
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app import ai_watch, gui_backend, mobile_server, restart_supervisor
from app.database import Database
from app.watch_evaluation import (
    classify_candidate, enrich, proposal_id, transition,
)
from app.watch_intelligence import (
    watch_focus, watch_context, answer_off_topic,
    explicit_independent_research, watch_fallback,
)

WATCH = {
    "source": "Google DeepMind",
    "title": "EmbeddingGemma 2: an open, lightweight multimodal embedding model",
    "url": "https://deepmind.google/blog/embeddinggemma-2/",
    "summary": "EmbeddingGemma 2 maps texts and images into a shared space.",
    "area": "screenshots and vision",
    "proposal": "Compare screenshot-identification accuracy.",
}
OLLAMA = {
    "source": "Ollama",
    "title": "Ollama: v0.40.3",
    "url": "https://github.com/ollama/ollama/releases/tag/v0.40.3",
    "summary": "",
    "area": "reasoning and knowledge",
}
WEATHER = {
    "source": "Google DeepMind",
    "title": "Introducing WeatherNext 3, our advanced weather AI model",
    "url": "https://deepmind.google/blog/introducing-weathernext-3/",
    "summary": "Specialised weather prediction and weather forecasting.",
    "area": "reasoning and knowledge",
}
VIDEO = {
    "source": "Google DeepMind",
    "title": "Introducing agentic video understanding with Gemini",
    "url": "https://deepmind.google/blog/introducing-agentic-video-in-gemini/",
    "summary": "Agentic video frame navigation.",
    "area": "software engineering",
}


class WatchFollowupTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.data = Path(self.folder.name) / "data"
        self.data.mkdir()
        self.sample = {
            "last_attempt": "2026-10-11T18:00:00+00:00",
            "last_success": "2026-10-11T18:00:00+00:00",
            "reports": [WATCH, VIDEO, WEATHER, OLLAMA],
            "seen": {},
            "evaluations": {},
        }
        ai_watch._store(self.data, self.sample)
        self.report = ai_watch.current_report(self.data, {"ai_watch_enabled": True})

    def test_relevance_is_not_broad_keyword_labeling(self):
        result = self.report["reports"]
        self.assertIn("retrieval", result[0]["area"])
        self.assertEqual(result[0]["priority"], "high")
        self.assertIn("video", result[1]["area"])
        self.assertEqual(result[1]["priority"], "medium")
        self.assertIn("weather", result[2]["area"])
        self.assertEqual(result[2]["priority"], "low")
        self.assertIn("inference", result[3]["area"])
        self.assertEqual(result[3]["priority"], "high")
        self.assertNotEqual(result[0]["proposal"], WATCH["proposal"])
        self.assertNotIn("general chat reasoning", result[2]["proposal"].lower())

    def test_exact_followups_and_no_unrelated_web_research(self):
        history = [
            {"role": "assistant", "content":
             "AI Technology Watch — newly detected updates\n" + WATCH["title"]},
            {"role": "user", "content": "whats your analysis?"},
        ]
        for q in (
            "whats your analysis?",
            "tell me, could any of that benefit you?",
            "so with you telling me about these improvements from ai technology watch, "
            "if i said yes hypothetically to all of it, what would you do",
        ):
            self.assertTrue(watch_focus(q, history, "AI Technology Watch", self.report), q)
            ctx = watch_context(self.report, q)
            self.assertIn("EmbeddingGemma", ctx)
            self.assertIn("saved announcements", ctx)
            self.assertNotIn("MyAnalyst", ctx)
            self.assertFalse(explicit_independent_research(q))
        self.assertFalse(watch_focus("What is the capital of Peru?", history,
                                     "AI Technology Watch", self.report))
        self.assertFalse(watch_focus("whats your analysis?", history,
                                     "New chat", {"reports": []}))
        self.assertTrue(explicit_independent_research(
            "Please research independent benchmarks about these watch announcements"
        ))

    def test_off_topic_guard_catches_user_observed_failure(self):
        bad = (
            "The provided sources describe two data analysis platforms and "
            "an unrelated UAP mission report with a strange white light."
        )
        self.assertTrue(answer_off_topic(bad, self.report, "whats your analysis?"))
        good = (
            "The EmbeddingGemma release could help XemAi retrieval but would "
            "need measured precision/recall experiments before installation."
        )
        self.assertFalse(answer_off_topic(good, self.report, "whats your analysis?"))
        hypothetical = (
            "I would first measure Ollama local inference compatibility, "
            "then ask permission before changing the code or downloading models."
        )
        self.assertFalse(answer_off_topic(
            hypothetical, self.report, "if i said yes hypothetically to all of it"
        ))
        fallback = watch_fallback(self.report, "if i said yes hypothetically to all of it")
        self.assertIn("hypothetically approved evaluation", fallback)
        self.assertIn("permission", fallback)

    def test_status_transitions_do_not_install_or_claim_verified_benchmarks(self):
        id = proposal_id(WATCH["url"])
        self.assertIsNone(transition(self.data, "I'd like you to approve everything."))
        self.assertIn("Approve", transition(
            self.data, f"record ai watch benchmark {id} | accuracy | 50 | 70 | higher"
        ))
        self.assertIn("evaluation planning only", transition(
            self.data, f"approve ai watch test {id}"
        ))
        self.assertEqual(ai_watch.current_report(self.data, {})["reports"][0][
            "evaluation_status"
        ], "approved_for_testing")
        result = transition(
            self.data, f"record ai watch benchmark {id} | accuracy | 50 | 70 | higher"
        )
        self.assertIn("USER-REPORTED", result)
        entry = ai_watch.current_report(self.data, {})["reports"][0]
        self.assertEqual(entry["evaluation_status"], "benchmarked_user_reported")
        self.assertEqual(entry["benchmark_result"]["outcome"], "improved")
        self.assertIn("not_independently_verified", entry["benchmark_result"]["verification"])
        self.assertIn(id, ai_watch.chat_command(
            "show AI technology watch report", self.data
        ))
        reject = transition(self.data, f"reject ai watch proposal {id}")
        self.assertIn("Rejected", reject)
        self.assertEqual(ai_watch.current_report(self.data, {})["reports"][0][
            "evaluation_status"
        ], "rejected")

    def test_full_chat_uses_saved_watch_and_retries_unrelated_web_answer(self):
        db = Database(self.data / "personal_ai.db")
        user = db.create_user("Tester")
        chat = db.create_chat(user["id"], "AI Technology Watch")
        db.add_assistant_message(
            chat["id"], "AI Technology Watch — newly detected updates\n" +
            WATCH["title"], compute_source="application",
        )
        db.close()
        backend = gui_backend.ChatBackend.__new__(gui_backend.ChatBackend)
        backend.logger = logging.getLogger("watch-followup-test")
        backend.config = {
            "model": "qwen3:8b", "auto_memory": False,
            "specialists_enabled": False, "laptop_answer_guidance": False,
            "evidence_research_mode": "auto",
        }
        llm = Mock()
        llm.model = "qwen3:8b"
        llm.route_info = {"compute": "remote_worker"}
        llm.agent_chat.side_effect = [
            "The sources discuss MyAnalyst and an unrelated UAP mission report.",
            "EmbeddingGemma 2 could improve XemAi memory retrieval, but we "
            "would need benchmark results before testing any changes.",
        ]
        with patch.object(gui_backend, "DATA_DIR", self.data), \
             patch.object(gui_backend, "build_llm_client", return_value=llm), \
             patch.object(backend, "refresh_runtime_model",
                return_value={"model":"qwen3:8b","compute":"remote_worker",
                              "worker_available":True}), \
             patch.object(gui_backend, "should_research_query",
                          side_effect=AssertionError("watch should not launch web research")), \
             patch.object(gui_backend, "source_context_for_request", return_value=""):
            answer = backend.send(chat["id"], "whats your analysis?")
        self.assertIn("EmbeddingGemma", answer)
        self.assertEqual(llm.agent_chat.call_count, 2)
        original_messages = llm.agent_chat.call_args_list[0].args[0]
        self.assertTrue(any("AI TECHNOLOGY WATCH FOLLOW-UP" in r["content"]
                            for r in original_messages if r["role"] == "system"))
        self.assertFalse(llm.agent_chat.call_args_list[0].kwargs[
            "tool_registry"
        ].web_allowed)
        db = Database(self.data / "personal_ai.db")
        self.assertIn("EmbeddingGemma", db.get_recent_messages(chat["id"])[-1]["content"])
        db.close()


class RestartTests(unittest.TestCase):
    def test_supervisor_confirms_health_after_one_launch(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            (base / "XemAiServer.pyw").write_text("pass")
            dummy = Mock()
            dummy.poll.return_value = None
            spawn = Mock(return_value=dummy)
            with patch.object(restart_supervisor, "_listening", return_value=False), \
                 patch.object(restart_supervisor, "_health",
                    side_effect=[False, True]):
                result = restart_supervisor.relaunch(
                    "/usr/bin/python3", str(base / "XemAiServer.pyw"), root,
                    str(base / "data"), "0.9.28", 8765,
                    wait=lambda seconds: None, spawn=spawn,
                )
            self.assertTrue(result)
            spawn.assert_called_once()
            saved = json.loads((base / "data/server_restart_status.json").read_text())
            self.assertEqual(saved["state"], "healthy")
            self.assertEqual(saved["target_version"], "0.9.28")

    def test_supervisor_does_not_start_duplicate_server(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            (base / "XemAiServer.pyw").write_text("pass")
            with patch.object(restart_supervisor, "_listening", return_value=True), \
                 patch.object(restart_supervisor, "_health", return_value=False), \
                 patch.object(restart_supervisor.subprocess, "Popen") as spawn:
                result = restart_supervisor.relaunch(
                    "python", str(base / "XemAiServer.pyw"), root, str(base),
                    "0.9.28", 8765, wait=lambda seconds: None
                )
            self.assertFalse(result)
            spawn.assert_not_called()
            status = json.loads((base / "server_restart_status.json").read_text())
            self.assertEqual(status["state"], "old_server_still_running")

    def test_existing_manual_and_background_paths_schedule_new_supervisor(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            (base / "app").mkdir()
            (base / "app/restart_supervisor.py").write_text("pass")
            (base / "XemAiServer.pyw").write_text("pass")
            server = SimpleNamespace(
                server_address=("0.0.0.0", 8765),
                stop_event=Mock(), shutdown=Mock(),
            )
            with patch.object(mobile_server, "BASE_DIR", base), \
                 patch.object(mobile_server, "DATA_DIR", base / "data"), \
                 patch.object(mobile_server, "_pythonw_executable",
                              return_value=Path("/usr/bin/python3")), \
                 patch.object(mobile_server.subprocess, "Popen") as popen, \
                 patch.object(mobile_server.threading, "Thread") as thread:
                mobile_server._schedule_mobile_server_restart(server, "0.9.28")
            args = popen.call_args.args[0]
            self.assertIn("-m", args)
            self.assertIn("app.restart_supervisor", args)
            self.assertIn("0.9.28", args)
            self.assertEqual(args[-1], "8765")
            thread.assert_called_once()
            self.assertFalse(server.shutdown.called)


if __name__ == "__main__":
    unittest.main()
