from __future__ import annotations

import compileall
import json
import tempfile
from pathlib import Path

from app.database import Database
from app.prompts import CONSTITUTION, build_system_prompt
from app.updater import is_newer_version
from app.tools import ToolRegistry, should_force_web_search


def run() -> None:
    project_root = Path(__file__).resolve().parent
    assert compileall.compile_dir(project_root, quiet=1, force=True)
    assert "When directly asked for your opinion" in CONSTITUTION
    assert "You may form and express reasoned opinions" in CONSTITUTION
    assert is_newer_version("0.2.3", "0.2.2")
    assert not is_newer_version("0.2.2", "0.2.2")
    assert not is_newer_version("0.2.1", "0.2.2")
    with tempfile.TemporaryDirectory() as temp:
        db = Database(Path(temp) / "test.db")

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
