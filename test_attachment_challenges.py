"""Regression tests for real source-code attachments and no external diversion."""
from __future__ import annotations

import logging
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import gui_backend
from app.attachment_tasks import (
    is_attached_code_assignment, answer_incomplete,
    source_assignment_context, source_names, incomplete_fallback,
    source_evidence_status, has_readable_source, refers_to_previously_attached_code,
    is_inline_source_assignment, inline_source_answer_needs_retry,
)
from app.database import Database


ASSIGNMENT = """XEMAI — SKYRIM SE CODING BENCHMARK — STAGE 1
Read-only diagnostic test.
YOUR TASK
1. Trace version registration and script gates using line-numbered files.
2. Explain plausible right-click/mouse aiming regressions.
3. State three read-only checks.
4. Give a safe recovery order.
5. Explain what cannot be proven from source alone.
CODE EVIDENCE — DO NOT LOOK ANYTHING UP ONLINE.
[File: CMakeLists.txt]
  1: project(MWControls VERSION 0.6.15 LANGUAGES CXX)
[File: src/Controls.cpp]
 16: SKSEPlugin_Version = { 1, 615, "MWControls" };
 22: constexpr std::uint32_t kScriptVersion = 615;
 457: bool CanProcessHook(RE::AttackBlockHandler* handler, RE::InputEvent* event)
 463: if (control == "Left Attack/Block") { return false; }
[File: scripts/Source/MWControls.psc]
  12: Int version = MWControls.GetVersion()
  19: If version != 615
  20:   Return False
  23: EndIf
"""
QUESTION = (
    "This is a read-only Skyrim Special Edition source-code challenge. "
    "Complete every numbered task in the attached file. Use exact file names "
    "and line numbers. Do not modify anything or claim to have run tests."
)
BAD = (
    "The provided context outlines tools related to Skyrim Special Edition "
    "SKSE plugins, but no specific question has been posed. To address factual "
    "queries I'd search SKSE templates and unrelated websites."
)
GOOD = (
    "1. In CMakeLists.txt line 1 the project declares 0.6.15. In "
    "src/Controls.cpp lines 16 and 22 the native DLL exposes 615; "
    "scripts/Source/MWControls.psc lines 12–23 gates native API use on 615. "
    "The code establishes this requirement, but not which DLL is installed. "
    "\n2. A stale DLL can leave the script gating to legacy aiming, so a right-click "
    "might again act as the ordinary attack/melee. This is a hypothesis pending "
    "logs. The native CanProcessHook at src/Controls.cpp line 457 tests the button "
    "and only blocks it under the active rifle condition. "
    "\n3. Check MWControls.log for the loaded module and readiness details; "
    "inspect SKSE/Plugins/MWControls.dll metadata for its version; compare the "
    "installed MWControls.pex with the scripts/Source/MWControls.psc build output. "
    "\n4. Preserve current files, record evidence, check which package supplies the "
    "DLL and script, make one compatible clean change only after explicit approval, "
    "then retest. \n5. Without the loaded DLL, full log and an actual Skyrim run "
    "we cannot establish which hook executed or claim the regression is fixed."
)


MISSING_ACTUAL_CODE = (
    "The provided text does not include the actual contents of the files "
    "CMakeLists.txt, Controls.cpp, or MWInterventionScopeAlias.psc. Without "
    "the code excerpts, it is impossible to identify or answer any numbered "
    "tasks tied to these files. To proceed, the user must provide the exact "
    "code content of these files (e.g. line numbers and text) to enable "
    "analysis. For example, if Controls.cpp contains a function definition "
    "its file and line number would be cited. "
    "<error> Code content for required files is missing. Please provide "
    "the exact text of CMakeLists.txt, Controls.cpp, and "
    "MWInterventionScopeAlias.psc to proceed. </error>"
)


class AttachmentTasksTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / "data"
        self.data.mkdir()
        db = Database(self.data / "personal_ai.db")
        self.user = db.create_user("Tester")
        self.chat = db.create_chat(self.user["id"], "New chat")
        db.close()
        root = self.data / "attachments" / f"chat_{self.chat['id']}"
        root.mkdir(parents=True)
        (root / "Stage1_Trace.txt").write_text(ASSIGNMENT, encoding="utf-8")
        self.attachment = {
            "name": "Stage1_Trace.txt",
            "path": f"attachments/chat_{self.chat['id']}/Stage1_Trace.txt",
            "size": len(ASSIGNMENT.encode()),
            "mime": "text/plain",
        }
        self.backend = gui_backend.ChatBackend.__new__(gui_backend.ChatBackend)
        self.backend.logger = logging.getLogger("attachment-task-regression")
        self.backend.config = {
            "model": "qwen3:8b", "auto_memory": False,
            "specialists_enabled": False,
            "laptop_answer_guidance": True,
            "evidence_research_mode": "auto",
        }

    def test_identifies_real_task_and_line_numbered_evidence(self):
        payload = "ATTACHED FILE: Stage1_Trace.txt\n--- UNTRUSTED FILE CONTENT ---\n" + ASSIGNMENT
        self.assertTrue(is_attached_code_assignment(
            QUESTION, payload, [self.attachment]
        ))
        self.assertEqual(source_names(payload), [
            "CMakeLists.txt", "Controls.cpp", "MWControls.psc"
        ])
        self.assertIn("answer ALL", source_assignment_context(QUESTION, payload))
        self.assertTrue(answer_incomplete(BAD, payload))
        self.assertTrue(answer_incomplete(MISSING_ACTUAL_CODE, payload))
        report = source_evidence_status(payload)
        self.assertGreaterEqual(report["numbered_source_lines"], 5)
        self.assertEqual(report["tasks_detected"], ["1", "2", "3", "4", "5"])
        self.assertTrue(has_readable_source(payload))
        self.assertTrue(refers_to_previously_attached_code(QUESTION))
        self.assertFalse(refers_to_previously_attached_code("What is the weather?"))
        self.assertFalse(answer_incomplete(GOOD, payload))
        self.assertIn("file", incomplete_fallback(payload).lower())
        self.assertFalse(is_attached_code_assignment(
            QUESTION, payload, [{"name": "plugin.zip"}]
        ))
        self.assertFalse(is_attached_code_assignment(
            "What is the weather today?", payload, [self.attachment]
        ))
        self.assertFalse(is_attached_code_assignment(
            QUESTION, "ATTACHED FILE: Stage1_Trace.txt\n[Binary attachment stored]",
            [self.attachment],
        ))

    def test_full_chat_uses_task_attachment_and_retries_off_topic_reply(self):
        model = Mock()
        model.model = "qwen3:8b"
        model.route_info = {"compute": "remote_worker"}
        model.agent_chat.side_effect = [BAD, GOOD]
        runtime = {"model": "qwen3:8b", "compute": "remote_worker",
                   "worker_available": True}
        with patch.object(gui_backend, "DATA_DIR", self.data), \
             patch.object(gui_backend, "build_llm_client", return_value=model), \
             patch.object(self.backend, "refresh_runtime_model", return_value=runtime), \
             patch.object(gui_backend, "source_context_for_request",
                          side_effect=AssertionError("attached code must not inspect unrelated repos")), \
             patch.object(gui_backend, "should_research_query",
                          side_effect=AssertionError("must not look up unrelated sites")):
            answer = self.backend.send(
                self.chat["id"], QUESTION, attachments=[self.attachment],
            )
        self.assertIn("src/Controls.cpp", answer)
        self.assertIn("scripts/Source/MWControls.psc", answer)
        self.assertEqual(model.agent_chat.call_count, 2)
        user_prompts = [
            row["content"] for row in model.agent_chat.call_args_list[0].args[0]
            if row["role"] == "user"
        ]
        self.assertTrue(any("YOUR TASK" in value for value in user_prompts))
        self.assertTrue(any("CanProcessHook" in value for value in user_prompts))
        self.assertTrue(any(
            "ATTACHED SOURCE ASSIGNMENT" in row["content"]
            for row in model.agent_chat.call_args_list[0].args[0]
            if row["role"] == "system"
        ))
        self.assertFalse(
            model.agent_chat.call_args_list[0].kwargs["tool_registry"].web_allowed
        )

    def test_unreadable_text_attachment_is_not_mistaken_for_read_content(self):
        (self.data / self.attachment["path"]).unlink()
        raw = gui_backend._attachment_marker(self.attachment) + "\n" + QUESTION
        with patch.object(gui_backend, "DATA_DIR", self.data):
            expanded = gui_backend._expand_attachment_message(raw)
        self.assertIn("unavailable", expanded.lower())
        self.assertFalse(is_attached_code_assignment(
            QUESTION, expanded, [self.attachment]
        ))


    def test_reproduces_exact_missing_code_claim_and_corrects_it(self):
        model = Mock()
        model.model = "qwen3:8b"
        model.route_info = {"compute": "remote_worker"}
        model.agent_chat.side_effect = [MISSING_ACTUAL_CODE, GOOD]
        runtime = {"model": "qwen3:8b", "compute": "remote_worker",
                   "worker_available": True}
        with patch.object(gui_backend, "DATA_DIR", self.data), \
             patch.object(gui_backend, "build_llm_client", return_value=model), \
             patch.object(self.backend, "refresh_runtime_model", return_value=runtime), \
             patch.object(gui_backend, "source_context_for_request",
                          side_effect=AssertionError("must not inspect unrelated repo")), \
             patch.object(gui_backend, "should_research_query",
                          side_effect=AssertionError("no live web")):
            answer = self.backend.send(
                self.chat["id"], QUESTION, attachments=[self.attachment]
            )
        self.assertIn("native DLL exposes 615", answer)
        self.assertNotIn("Code content for required files is missing", answer)
        self.assertEqual(model.agent_chat.call_count, 2)
        first = model.agent_chat.call_args_list[0]
        self.assertEqual(first.kwargs["max_tool_rounds"], 0)
        self.assertEqual(first.kwargs["tool_registry"].definitions(), [])
        self.assertEqual(sum(m["role"] == "user" for m in first.args[0]), 1)
        self.assertTrue(any(
            "line-numbered code excerpts" in m["content"]
            for m in first.args[0] if m["role"] == "system"
        ))

    def test_repeated_missing_content_claim_reports_existing_source_truthfully(self):
        model = Mock()
        model.model = "qwen3:8b"
        model.route_info = {"compute": "remote_worker"}
        model.agent_chat.side_effect = [MISSING_ACTUAL_CODE, MISSING_ACTUAL_CODE]
        runtime = {"model": "qwen3:8b", "compute": "remote_worker",
                   "worker_available": True}
        with patch.object(gui_backend, "DATA_DIR", self.data), \
             patch.object(gui_backend, "build_llm_client", return_value=model), \
             patch.object(self.backend, "refresh_runtime_model", return_value=runtime), \
             patch.object(gui_backend, "source_context_for_request", return_value=""), \
             patch.object(gui_backend, "should_research_query",
                          side_effect=AssertionError("do not browse")):
            answer = self.backend.send(
                self.chat["id"], QUESTION, attachments=[self.attachment]
            )
        self.assertIn("source file was received and read", answer)
        self.assertIn("line-numbered", answer)
        self.assertIn("source excerpts", answer)
        self.assertNotIn("Please provide the exact text", answer)
        self.assertEqual(model.agent_chat.call_count, 2)

    def test_source_can_be_reused_if_sent_separately_in_recent_chat(self):
        db = Database(self.data / "personal_ai.db")
        # Emulate the user uploading a file and THEN writing the test request.
        db.add_message(
            self.chat["id"], "user",
            gui_backend._attachment_marker(self.attachment),
        )
        db.close()
        model = Mock()
        model.model = "qwen3:8b"
        model.route_info = {"compute": "remote_worker"}
        model.agent_chat.return_value = GOOD
        runtime = {"model": "qwen3:8b", "compute": "remote_worker",
                   "worker_available": True}
        with patch.object(gui_backend, "DATA_DIR", self.data), \
             patch.object(gui_backend, "build_llm_client", return_value=model), \
             patch.object(self.backend, "refresh_runtime_model", return_value=runtime), \
             patch.object(gui_backend, "source_context_for_request", return_value=""), \
             patch.object(gui_backend, "should_research_query",
                          side_effect=AssertionError("do not browse")):
            answer = self.backend.send(self.chat["id"], QUESTION)
        self.assertIn("CMakeLists.txt", answer)
        first = model.agent_chat.call_args_list[0]
        self.assertEqual(sum(m["role"] == "user" for m in first.args[0]), 1)
        self.assertTrue(any(
            "PREVIOUSLY UPLOADED SOURCE" in m["content"]
            for m in first.args[0] if m["role"] == "user"
        ))
        self.assertFalse(first.kwargs["tool_registry"].web_allowed)


    def test_inline_papyrus_source_stays_in_current_chat_and_recovers_off_topic(self):
        # Mirrors the user's real Qwen3:8b failure in a new conversation.
        question = (
            "I'm testing your ability to accurately read source code.\\n"
            "File: MWInterventionScopeAlias.psc\\n"
            "Line 74:\\n"
            "nativeControls = MWControls.IsReady() && MWControls.GetVersion() == 615\\n"
            "Lines 142–145:\\n"
            "If nativeControls\\n"
            "    Return Input.IsKeyPressed(aimKeyA)\\n"
            "EndIf\\n"
            "Return Input.IsKeyPressed(aimKeyA) && Input.IsKeyPressed(aimKeyB)\\n"
            "Answer what nativeControls means. Quote only supplied code."
        )
        wrong = (
            "HomeLayout.kt and ProfileEditorLayout.kt manage media tiles and "
            "layout calculations. This is the source-code answer."
        )
        correct = (
            "In MWInterventionScopeAlias.psc, nativeControls is true only "
            "when MWControls.IsReady() is true AND MWControls.GetVersion() == 615. "
            "Native mode returns the key A pressed state, while fallback "
            "requires both key A and key B. The excerpt does not show "
            "modifierKey, singleAim(), or legacyAim() implementations."
        )
        self.assertTrue(is_inline_source_assignment(question))
        self.assertTrue(inline_source_answer_needs_retry(question, wrong))
        self.assertFalse(inline_source_answer_needs_retry(question, correct))

        db = Database(self.data / "personal_ai.db")
        db.add_memory(
            self.user["id"], self.chat["id"], "project",
            "The XemTV project includes HomeLayout.kt and ProfileEditorLayout.kt.",
            0.99,
        )
        db.close()
        model = Mock()
        model.model = "qwen3:8b"
        model.route_info = {"compute": "remote_worker"}
        model.agent_chat.side_effect = [wrong, correct]
        runtime = {"model": "qwen3:8b", "compute": "remote_worker",
                   "worker_available": True}
        with patch.object(gui_backend, "DATA_DIR", self.data), \\
             patch.object(gui_backend, "build_llm_client", return_value=model), \\
             patch.object(self.backend, "refresh_runtime_model", return_value=runtime), \\
             patch.object(gui_backend, "source_context_for_request",
                          side_effect=AssertionError("inline source cannot select repo")), \\
             patch.object(gui_backend, "should_research_query",
                          side_effect=AssertionError("inline source cannot browse")):
            answer = self.backend.send(self.chat["id"], question)
        self.assertIn("MWInterventionScopeAlias.psc", answer)
        self.assertNotIn("HomeLayout.kt", answer)
        self.assertEqual(model.agent_chat.call_count, 2)
        first = model.agent_chat.call_args_list[0]
        self.assertEqual(first.kwargs["max_tool_rounds"], 0)
        self.assertFalse(first.kwargs["tool_registry"].web_allowed)
        self.assertEqual(sum(m["role"] == "user" for m in first.args[0]), 1)
        system_text = "\\n".join(m["content"] for m in first.args[0]
                                if m["role"] == "system")
        self.assertIn("INLINE SOURCE-ONLY QUESTION", system_text)
        self.assertNotIn("HomeLayout.kt", system_text)

    def test_rejects_fabricated_fenced_quote_even_with_correct_filename(self):
        question = (
            "File: MWInterventionScopeAlias.psc\\n"
            "Line 74:\\n"
            "nativeControls = MWControls.IsReady() && MWControls.GetVersion() == 615\\n"
            "Quote only supplied code."
        )
        invented = (
            "MWInterventionScopeAlias.psc allegedly contains:\\n"
            "```papyrus\\n"
            "if (modifierKey) { singleAim(); }\\n"
            "```"
        )
        self.assertTrue(is_inline_source_assignment(question))
        self.assertTrue(inline_source_answer_needs_retry(question, invented))
        self.assertFalse(inline_source_answer_needs_retry(question, (
            "The supplied line sets nativeControls using IsReady and GetVersion."
        )))



if __name__ == "__main__":
    unittest.main()
