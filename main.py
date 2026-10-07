from __future__ import annotations

import os
import sys
from datetime import datetime
from getpass import getpass

from app.config import DATA_DIR, LOG_DIR, load_config, save_config
from app.database import Database
from app.learning import extract_and_store_memories
from app.llm import OllamaClient, OllamaError
from app.logging_setup import setup_logging
from app.prompts import build_system_prompt
from app.secrets import save_ollama_api_key, clear_ollama_api_key
from app.tools import ToolRegistry, should_force_web_search
from app.updater import check_for_update, fetch_manifest, install_update, UpdateError
from app.version import VERSION


def greeting(name: str) -> str:
    hour = datetime.now().astimezone().hour
    if hour < 12:
        return f"Good morning, {name}. How are you this morning?"
    if hour < 17:
        return f"Good afternoon, {name}. How has your day been?"
    return f"Good evening, {name}. How has your day been?"


def print_help() -> None:
    print(
        """
Commands
--------
/help                 Show commands
/new [title]          Start a new separate chat
/chats                List chats
/switch <id>          Switch chat
/profile              Show local profile
/setstyle <text>      Set how you prefer the AI to communicate
/memory               Show long-term memories
/remember <text>      Add a memory manually
/forget <id>          Deactivate a memory
/model <name>         Change Ollama model (e.g. qwen3:8b)
/ainame [name]        Show or change the AI's display name
/feedback             Show recent 0-10 chat feedback
/rate <0-10> [note]   Give optional feedback immediately
/tools                Show available tools
/capabilities         Show XemAi's actual current capabilities
/websetup             Configure and validate Ollama web search
/webtest              Test the saved web-search connection
/webclear             Remove stored Ollama web-search key
/end                  End the current chat and rate it
/update               Check for and install an update
/version              Show installed version
/log                  Show log file location
/quit                 Exit
"""
    )


def ask_chat_rating(db, user_id: int, chat_id: int) -> None:
    if not db.chat_has_messages(chat_id):
        return

    while True:
        raw = input(
            "\nBefore we close this chat, how helpful was I overall? "
            "0-10 (Enter to skip): "
        ).strip()

        if not raw:
            return

        try:
            score = int(raw)
        except ValueError:
            print("Please enter a number from 0 to 10, or press Enter to skip.")
            continue

        if not 0 <= score <= 10:
            print("Please enter a number from 0 to 10.")
            continue

        note = ""
        if score <= 5:
            note = input("What should I have done better? (optional): ").strip()
        elif score >= 9:
            note = input("What worked especially well? (optional): ").strip()

        db.add_chat_feedback(
            user_id=user_id,
            chat_id=chat_id,
            score=score,
            note=note,
        )
        print(f"Chat reward recorded: {score}/10.")
        return


def build_capability_status(config, tool_registry) -> list[str]:
    web_state = (
        "configured; use /webtest to verify the saved Ollama key"
        if tool_registry.web_search_enabled
        else "not configured"
    )
    return [
        f"Identity: {config.get('assistant_name', 'XemAi')}",
        "Persistent local user profile: enabled",
        "Persistent chat history across restarts: enabled",
        "Cross-chat long-term memory: enabled",
        "Automatic memory extraction: enabled" if config.get("auto_memory", True)
        else "Automatic memory extraction: disabled",
        "Recent 0-10 feedback is available as a future-response optimisation signal",
        f"Live web search: {web_state}",
        "Direct HTTP/HTTPS webpage fetching: enabled",
        "Calculator: enabled",
        "Current date/time lookup: enabled",
        "Sandboxed local workspace file listing/reading/writing: enabled",
        f"Underlying local model: {config.get('model', 'unknown')}",
        "Arbitrary shell/command execution: disabled",
        "Unrestricted filesystem access: disabled",
        "Unrestricted computer/desktop control: disabled",
        "Native image/vision analysis: not yet implemented",
        "Native audio/video analysis: not yet implemented",
        "General external API/app integrations: not yet implemented beyond configured tools",
    ]


def print_capabilities(config, tool_registry) -> None:
    print("\nXemAi capabilities:")
    for line in build_capability_status(config, tool_registry):
        print(f"- {line}")
    print()


def main() -> int:
    config = load_config()
    logger = setup_logging(LOG_DIR)
    db = Database(DATA_DIR / "personal_ai.db")
    logger.info("Application start | version=%s", VERSION)

    if config.get("check_updates_on_startup") and config.get("update_manifest_url"):
        try:
            manifest = check_for_update(config["update_manifest_url"])
            if manifest:
                print(
                    f"Update available: v{manifest['version']} "
                    f"(installed: v{VERSION})."
                )
                print("Type /update after startup to install it.\n")
        except Exception as e:
            logger.warning("Startup update check failed: %r", e)

    try:
        user = db.get_user()
        if user is None:
            print("Welcome. No login is required; your profile is stored locally.")
            while True:
                name = input("What should I call you? ").strip()
                if name:
                    break
                print("Please enter a name.")
            user = db.create_user(name)
            logger.info("Local user profile created | user_id=%s", user["id"])

        repaired = db.repair_invalid_memory_confidence(user["id"])
        if repaired:
            logger.info(
                "Memory repair | user_id=%s repaired_zero_confidence_preferences=%d",
                user["id"], repaired
            )

        chats = db.list_chats(user["id"])
        if chats:
            current_chat = chats[0]
        else:
            current_chat = db.create_chat(user["id"], "General")

        print()
        print(f"Chat: [{current_chat['id']}] {current_chat['title']}")
        print("-" * 50)
        print(greeting(user["name"]))
        print()

        llm = OllamaClient(
            base_url=config["ollama_url"],
            model=config["model"],
            logger=logger,
        )
        tool_registry = ToolRegistry(
            base_dir=DATA_DIR.parent,
            data_dir=DATA_DIR,
            logger=logger,
        )

        if not llm.health_check():
            print(
                "I can't reach Ollama yet.\n"
                "Install/start Ollama, then run this program again.\n"
                f"Expected local server: {config['ollama_url']}"
            )
            logger.error("Startup halted: Ollama unavailable")
            return 2

        if not llm.model_available():
            print(
                f"The configured model '{config['model']}' is not installed.\n"
                f"Open Command Prompt and run:\n\n"
                f"    ollama pull {config['model']}\n"
            )
            logger.error(
                "Startup halted: model unavailable | model=%s", config["model"]
            )
            return 3

        while True:
            try:
                raw = input(f"{user['name']} > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                ask_chat_rating(db, user["id"], current_chat["id"])
                print("Goodbye.")
                break

            if not raw:
                continue

            if raw.startswith("/"):
                parts = raw.split(maxsplit=1)
                command = parts[0].lower()
                arg = parts[1].strip() if len(parts) > 1 else ""

                if command == "/quit":
                    ask_chat_rating(db, user["id"], current_chat["id"])
                    print("Goodbye.")
                    break

                if command == "/help":
                    print_help()
                    continue

                if command == "/new":
                    ask_chat_rating(db, user["id"], current_chat["id"])
                    title = arg or input("Chat title: ").strip() or "Untitled"
                    current_chat = db.create_chat(user["id"], title)
                    logger.info(
                        "Chat created | chat_id=%s title=%r",
                        current_chat["id"], current_chat["title"]
                    )
                    print(
                        f"\nChat: [{current_chat['id']}] "
                        f"{current_chat['title']}"
                    )
                    print("-" * 50)
                    continue

                if command == "/chats":
                    rows = db.list_chats(user["id"])
                    print("\nChats:")
                    for row in rows:
                        marker = "*" if row["id"] == current_chat["id"] else " "
                        print(f"{marker} [{row['id']}] {row['title']}")
                    print()
                    continue

                if command == "/switch":
                    try:
                        chat_id = int(arg)
                    except ValueError:
                        print("Usage: /switch <chat id>")
                        continue
                    row = db.get_chat(chat_id)
                    if row is None or row["user_id"] != user["id"]:
                        print("Chat not found.")
                        continue
                    if row["id"] != current_chat["id"]:
                        ask_chat_rating(db, user["id"], current_chat["id"])
                    current_chat = row
                    logger.info("Chat switched | chat_id=%s", chat_id)
                    print(f"\nChat: [{row['id']}] {row['title']}")
                    print("-" * 50)
                    continue

                if command == "/profile":
                    user = db.get_user()
                    print(f"\nName: {user['name']}")
                    print(
                        "Communication style: "
                        + (
                            user["communication_preferences"]
                            or "Default: concise, clear, polite and direct"
                        )
                    )
                    print(
                        "Personality/context notes: "
                        + (user["personality_notes"] or "None yet")
                    )
                    print()
                    continue

                if command == "/setstyle":
                    if not arg:
                        print("Usage: /setstyle <your preference>")
                        continue
                    db.update_user_style(user["id"], arg)
                    user = db.get_user()
                    db.add_memory(
                        user["id"],
                        current_chat["id"],
                        "preference",
                        f"Communication preference: {arg}",
                        1.0,
                    )
                    print("Communication preference updated.")
                    continue

                if command == "/memory":
                    memories = db.list_memories(user["id"])
                    if not memories:
                        print("No long-term memories yet.")
                    else:
                        print("\nLong-term memory:")
                        for m in memories:
                            print(
                                f"[{m['id']}] {m['kind']} "
                                f"({m['confidence']:.2f}): {m['content']}"
                            )
                        print()
                    continue

                if command == "/remember":
                    if not arg:
                        print("Usage: /remember <text>")
                        continue
                    memory_id = db.add_memory(
                        user["id"], current_chat["id"],
                        "profile", arg, 1.0
                    )
                    print(f"Stored as memory [{memory_id}].")
                    continue

                if command == "/forget":
                    try:
                        memory_id = int(arg)
                    except ValueError:
                        print("Usage: /forget <memory id>")
                        continue
                    if db.deactivate_memory(user["id"], memory_id):
                        print(f"Memory [{memory_id}] deactivated.")
                    else:
                        print("Memory not found.")
                    continue

                if command == "/ainame":
                    if not arg:
                        print(f"AI name: {config.get('assistant_name', 'XemAi')}")
                        continue
                    config["assistant_name"] = arg.strip()
                    save_config(config)
                    print(f"AI name changed to {config['assistant_name']}.")
                    logger.info("Assistant name changed | name=%r", config["assistant_name"])
                    continue

                if command == "/model":
                    if not arg:
                        print(f"Current model: {config['model']}")
                        continue
                    config["model"] = arg
                    save_config(config)
                    llm = OllamaClient(
                        base_url=config["ollama_url"],
                        model=config["model"],
                        logger=logger,
                    )
                    print(
                        f"Model changed to '{arg}'. "
                        "If it is not installed, run "
                        f"'ollama pull {arg}' first."
                    )
                    logger.info("Model changed | model=%s", arg)
                    continue

                if command == "/capabilities":
                    print_capabilities(config, tool_registry)
                    continue

                if command == "/tools":
                    print("\nAvailable tools:")
                    for line in tool_registry.status_lines():
                        print(f"- {line}")
                    print(
                        "\nNote: live web_search sends the search query to "
                        "Ollama's web service. Other local workspace tools stay local."
                    )
                    print()
                    continue

                if command == "/websetup":
                    print(
                        "Live web search uses Ollama's Web Search API. "
                        "Paste an Ollama API key below. It will be tested before saving."
                    )
                    key = getpass("Ollama API key (input hidden): ").strip()
                    if not key:
                        print("No key saved.")
                        continue

                    ok, message = tool_registry.test_web_search_key(key)
                    if not ok:
                        print(f"Web search setup failed: {message}")
                        print("The key was not saved.")
                        continue

                    save_ollama_api_key(DATA_DIR, key)
                    tool_registry = ToolRegistry(
                        base_dir=DATA_DIR.parent,
                        data_dir=DATA_DIR,
                        logger=logger,
                    )
                    print("Ollama web search connected successfully.")
                    print("The key is stored locally in data/secrets.json.")
                    continue

                if command == "/webtest":
                    ok, message = tool_registry.test_saved_web_search()
                    if ok:
                        print("Web search test passed: Ollama accepted the saved key.")
                    else:
                        print(f"Web search test failed: {message}")
                    continue

                if command == "/webclear":
                    clear_ollama_api_key(DATA_DIR)
                    tool_registry = ToolRegistry(
                        base_dir=DATA_DIR.parent,
                        data_dir=DATA_DIR,
                        logger=logger,
                    )
                    print("Stored Ollama web-search key removed.")
                    continue

                if command == "/rate":
                    if not arg:
                        print("Usage: /rate <0-10> [optional note]")
                        continue
                    score_text, _, note = arg.partition(" ")
                    try:
                        score = int(score_text)
                    except ValueError:
                        print("Usage: /rate <0-10> [optional note]")
                        continue
                    if not 0 <= score <= 10:
                        print("Score must be from 0 to 10.")
                        continue
                    db.add_chat_feedback(
                        user["id"], current_chat["id"], score, note.strip()
                    )
                    print(f"Feedback recorded: {score}/10.")
                    continue

                if command == "/end":
                    ask_chat_rating(db, user["id"], current_chat["id"])
                    print(
                        "Chat ended. Start another with /new <title> "
                        "or /switch <id>."
                    )
                    continue

                if command == "/feedback":
                    rows = db.recent_chat_feedback(user["id"])
                    if not rows:
                        print("No chat feedback recorded yet.")
                    else:
                        avg = sum(r["score"] for r in rows) / len(rows)
                        print(
                            f"Recent average chat reward: {avg:.1f}/10 "
                            f"across {len(rows)} rated chats."
                        )
                        for row in rows[:10]:
                            note = f" | {row['note']}" if row["note"] else ""
                            print(
                                f"- [{row['chat_id']}] {row['chat_title']}: "
                                f"{row['score']}/10{note}"
                            )
                    continue

                if command == "/version":
                    print(f"Personal AI v{VERSION}")
                    continue

                if command == "/update":
                    manifest_url = config.get("update_manifest_url", "").strip()
                    if not manifest_url:
                        print(
                            "Automatic updating is installed, but no update "
                            "channel is configured yet.\n"
                            "Set 'update_manifest_url' in config.json to a "
                            "permanent HTTPS manifest URL."
                        )
                        continue

                    try:
                        manifest = check_for_update(manifest_url)
                        if not manifest:
                            print(f"You're already on the latest version (v{VERSION}).")
                            continue

                        target = str(manifest["version"])
                        notes = str(manifest.get("notes", "")).strip()
                        print(f"Update available: v{target}")
                        if notes:
                            print(notes)

                        answer = input("Install this update now? [y/N]: ").strip().lower()
                        if answer not in {"y", "yes"}:
                            print("Update cancelled.")
                            continue

                        print("Downloading and verifying update...")
                        installed = install_update(
                            base_dir=DATA_DIR.parent,
                            manifest=manifest,
                            logger=logger,
                        )
                        print(f"Updated to v{installed}.")
                        print("Restarting Personal AI in this window...")
                        logger.info(
                            "Automatic restart after update | target=%s",
                            installed,
                        )

                        # Replace this Python process with the freshly updated
                        # application. The command window stays open, while all
                        # Python modules are reloaded from the new version.
                        script = (DATA_DIR.parent / "main.py").resolve()
                        db.close()
                        os.execv(
                            sys.executable,
                            [sys.executable, str(script)],
                        )
                    except UpdateError as e:
                        logger.exception("Update failed")
                        print(f"Update failed: {e}")
                    except Exception as e:
                        logger.exception("Unexpected update failure")
                        print(f"Unexpected update error: {e}")
                    continue

                if command == "/log":
                    print(f"Log file: {LOG_DIR / 'personal_ai.log'}")
                    continue

                print("Unknown command. Type /help.")
                continue

            user_message = raw
            db.add_message(current_chat["id"], "user", user_message)

            memories = db.relevant_memories(
                user["id"],
                user_message,
                limit=int(config.get("memory_limit", 25)),
            )
            user = db.get_user()
            recent_feedback = db.recent_chat_feedback(user["id"], limit=8)
            system_prompt = build_system_prompt(
                user,
                memories,
                feedback_rows=recent_feedback,
                tool_status=tool_registry.status_lines(),
                assistant_name=config.get("assistant_name", "XemAi"),
                capability_status=build_capability_status(config, tool_registry),
            )

            history = db.get_recent_messages(
                current_chat["id"],
                limit=int(config.get("history_messages", 30)),
            )

            messages = [{"role": "system", "content": system_prompt}]
            for row in history:
                if row["role"] in {"user", "assistant"}:
                    messages.append(
                        {"role": row["role"], "content": row["content"]}
                    )

            try:
                logger.info(
                    "Chat request | user_id=%s chat_id=%s model=%s chars=%d",
                    user["id"], current_chat["id"],
                    config["model"], len(user_message)
                )
                if config.get("log_message_content", False):
                    logger.debug(
                        "User content | chat_id=%s | %s",
                        current_chat["id"], user_message
                    )

                if (
                    tool_registry.web_search_enabled
                    and should_force_web_search(user_message)
                ):
                    logger.info(
                        "Forced web search route | chat_id=%s query_chars=%d",
                        current_chat["id"], len(user_message)
                    )
                    search_json = tool_registry.execute(
                        "web_search",
                        {"query": user_message, "max_results": 5},
                    )
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "A live web search was automatically run because "
                                "the user explicitly requested current/web information. "
                                "Use the results below if successful. If the tool "
                                "returned an error, state that specific error and do "
                                "not claim that web access does not exist.\n\n"
                                f"LIVE_WEB_SEARCH_RESULT:\n{search_json}"
                            ),
                        }
                    )

                answer = llm.agent_chat(
                    messages,
                    tool_registry=tool_registry,
                    max_tool_rounds=int(config.get("max_tool_rounds", 6)),
                )
            except OllamaError as e:
                logger.exception(
                    "LLM failure | chat_id=%s model=%s",
                    current_chat["id"], config["model"]
                )
                print(f"\nAI error: {e}\n")
                continue
            except Exception as e:
                logger.exception("Unexpected chat failure")
                print(f"\nUnexpected error: {e}\n")
                continue

            assistant_message_id = db.add_message(
                current_chat["id"], "assistant", answer
            )

            if config.get("log_message_content", False):
                logger.debug(
                    "Assistant content | chat_id=%s | %s",
                    current_chat["id"], answer
                )

            print(f"\n{config.get('assistant_name', 'XemAi')} > {answer}\n")

            if config.get("auto_memory", True):
                extract_and_store_memories(
                    llm=llm,
                    db=db,
                    user_id=user["id"],
                    chat_id=current_chat["id"],
                    user_message=user_message,
                    logger=logger,
                )

        logger.info("Application exit")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
