from __future__ import annotations

import compileall
import json
import tempfile
from pathlib import Path

from app.capabilities import build_capability_status
from app.database import Database
from app.gui_backend import ChatBackend, title_from_message
from app.mobile_runtime import mobile_local_url, mobile_server_version
from app.prompts import CONSTITUTION, build_system_prompt
from app.self_knowledge import (
    build_authoritative_self_context,
    is_self_knowledge_query,
    looks_like_stale_self_description,
)
from app.updater import is_newer_version
from app.tools import ToolRegistry, should_force_web_search
from ui import XemAiApp


def run() -> None:
    project_root = Path(__file__).resolve().parent
    assert compileall.compile_dir(project_root, quiet=1, force=True)
    assert "When directly asked for your opinion" in CONSTITUTION
    assert "You may form and express reasoned opinions" in CONSTITUTION
    assert (project_root / "XemAi.pyw").exists()
    assert (project_root / "LegacyDesktop.pyw").exists()
    assert "--app=" in (project_root / "XemAi.pyw").read_text(encoding="utf-8")
    assert (project_root / "ui.py").exists()
    assert (project_root / "console.bat").exists()
    assert (project_root / "XemAiServer.pyw").exists()
    assert (project_root / "mobile_server.bat").exists()
    assert (project_root / "mobile_tailscale_setup.bat").exists()
    assert (project_root / "mobile" / "index.html").exists()
    assert (project_root / "mobile" / "app.js").exists()
    mobile_js = (project_root / "mobile" / "app.js").read_text(encoding="utf-8")
    mobile_server = (project_root / "app" / "mobile_server.py").read_text(encoding="utf-8")
    assert "/api/update/install" in mobile_js
    assert "/api/update/install" in mobile_server
    assert "/api/update" in mobile_server
    assert 'FRONTEND_VERSION = "0.6.1"' in mobile_js
    mobile_html = (project_root / "mobile" / "index.html").read_text(encoding="utf-8")
    assert "/app.js?v=0.6.1" in mobile_html
    assert "/styles.css?v=0.6.1" in mobile_html
    mobile_css = (project_root / "mobile" / "styles.css").read_text(encoding="utf-8")
    assert "backdrop-filter: blur(14px)" in mobile_css
    assert "@media (min-width: 1000px)" in mobile_css
    assert "margin-left: 318px" in mobile_css
    assert "font-size: 18px;" in mobile_css
    assert "background-attachment: fixed" in mobile_css
    assert "@media (max-width: 999px)" in mobile_css
    assert "rgba(14, 70, 116, 0.62)" in mobile_css
    assert 'chatTitle: $("chatTitle")' not in mobile_js
    desktop_ui = (project_root / "ui.py").read_text(encoding="utf-8")
    assert 'row["updated_at"]' in desktop_ui
    assert 'row.get("updated_at")' not in desktop_ui
    assert "no-store, max-age=0" in mobile_server
    assert mobile_local_url().startswith("http://")
    assert (project_root / "restart_mobile_server.bat").exists()
    runtime_source = (project_root / "app" / "mobile_runtime.py").read_text(encoding="utf-8")
    assert "ensure_mobile_server_current" in runtime_source
    assert "XemAiServer.pyw" in runtime_source
    assert title_from_message("hello world") == "hello world"
    assert XemAiApp._format_time(None, "2026-10-08T01:41:00+01:00") is not None
    assert "desktop_startup_error.log" in (project_root / "XemAi.pyw").read_text(encoding="utf-8")
    assert is_self_knowledge_query("what do you think your ai is missing?")
    assert is_self_knowledge_query("through your iterative updates, can you recognise whats been added?")
    assert not is_self_knowledge_query("help me design a Skyrim perk")
    assert looks_like_stale_self_description("I have no live web search and my training ends in 2023.")
    assert is_newer_version("0.6.2", "0.6.1")
    assert not is_newer_version("0.6.1", "0.6.1")
    assert not is_newer_version("0.6.0", "0.6.1")
    with tempfile.TemporaryDirectory() as temp:
        db = Database(Path(temp) / "test.db")

        mode = db.conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert str(mode).lower() == "wal"
        user = db.create_user("Test User")
        assert user["name"] == "Test User"

        system_prompt = build_system_prompt(
            user,
            [],
            feedback_rows=[],
            tool_status=["calculator: enabled"],
            assistant_name="XemAi",
            capability_status=[
                "Persistent chat history across restarts: enabled",
                "Cross-chat long-term memory: enabled",
                "Live web search: configured",
            ],
        )
        assert "You are XemAi" in system_prompt
        assert "Your name is XemAi" in system_prompt
        assert "SELF-KNOWLEDGE / CURRENT APP CAPABILITIES" in system_prompt
        assert "Cross-chat long-term memory: enabled" in system_prompt
        assert "Do NOT claim you lack live data" in system_prompt
        assert "Never invent or state a training cutoff year" in system_prompt
        assert "AVAILABLE TOOLS" in system_prompt
        assert "calculator: enabled" in system_prompt
        assert "Do not use tool limitations as an excuse" in system_prompt

        chat_a = db.create_chat(user["id"], "Skyrim")
        chat_b = db.create_chat(user["id"], "Research")
        assert chat_a["id"] != chat_b["id"]
        db.rename_chat(chat_b["id"], "Renamed chat")
        assert db.get_chat(chat_b["id"])["title"] == "Renamed chat"

        db.add_message(chat_a["id"], "user", "The scope sway needs work.")
        db.add_message(chat_a["id"], "assistant", "Understood.")
        assert len(db.get_recent_messages(chat_a["id"])) == 2
        assert len(db.get_recent_messages(chat_b["id"])) == 0

        bad_pref_id = db.add_memory(
            user["id"], chat_a["id"], "preference",
            "Prefer direct answers without unnecessary agreement.", 0.0
        )
        repaired = db.repair_invalid_memory_confidence(user["id"])
        assert repaired == 1
        repaired_pref = [
            m for m in db.list_memories(user["id"])
            if m["id"] == bad_pref_id
        ][0]
        assert repaired_pref["confidence"] == 1.0

        memory_id = db.add_memory(
            user["id"], chat_a["id"], "project",
            "The Skyrim project includes scope sway.", 0.95
        )
        assert memory_id is not None
        relevant = db.relevant_memories(
            user["id"], "Skyrim scope", limit=5
        )
        assert relevant
        assert "scope sway" in relevant[0]["content"].lower()

        assistant_id = db.add_message(
            chat_a["id"], "assistant", "Updated the sway."
        )
        db.add_feedback(
            user["id"], chat_a["id"], assistant_id, 10, "Worked well"
        )
        feedback = db.recent_feedback(user["id"])
        assert feedback[0]["score"] == 10

        db.add_chat_feedback(
            user["id"], chat_a["id"], 9, "Helpful overall"
        )
        chat_feedback = db.recent_chat_feedback(user["id"])
        assert chat_feedback[0]["score"] == 9
        assert chat_feedback[0]["chat_title"] == "Skyrim"

        assert db.deactivate_memory(user["id"], memory_id)
        assert all(
            row["id"] != memory_id
            for row in db.list_memories(user["id"])
        )

        class DummyLogger:
            def info(self, *args, **kwargs):
                pass
            def warning(self, *args, **kwargs):
                pass

        registry = ToolRegistry(Path(temp), Path(temp) / "data", DummyLogger())
        self_context = build_authoritative_self_context(
            {"assistant_name": "XemAi", "model": "qwen3:8b", "auto_memory": True},
            registry,
        )
        assert "AUTHORITATIVE XEMAI RUNTIME SELF-KNOWLEDGE" in self_context
        assert "persistent chat history" in self_context.lower()
        assert "cross-chat long-term memory" in self_context.lower()
        assert "v0.3.0" in self_context
        assert "bubble-based" in self_context.lower()
        assert "Do not claim a 2023" in self_context

        calc = json.loads(registry.execute("calculator", {"expression": "2 + 3 * 4"}))
        assert calc["ok"] and calc["result"] == 14

        wrote = json.loads(
            registry.execute(
                "workspace_write",
                {"path": "test.txt", "content": "hello tools"},
            )
        )
        assert wrote["ok"]
        read = json.loads(
            registry.execute("workspace_read", {"path": "test.txt"})
        )
        assert read["ok"] and "hello tools" in read["result"]["content"]

        db.close()

    print("SELF-TEST PASSED")


if __name__ == "__main__":
    run()
