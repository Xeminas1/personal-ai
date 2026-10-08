from __future__ import annotations

from pathlib import Path

from .capabilities import build_capability_status
from .config import DATA_DIR, LOG_DIR, load_config, save_config
from .database import Database
from .learning import extract_and_store_memories
from .llm import OllamaClient
from .logging_setup import setup_logging
from .prompts import build_system_prompt
from .secrets import save_ollama_api_key
from .self_knowledge import (
    build_ai_comparison_fallback,
    build_authoritative_self_context,
    build_self_knowledge_fallback,
    is_ai_comparison_query,
    is_self_knowledge_query,
    looks_like_stale_self_description,
)
from .tools import ToolRegistry, should_force_web_search
from .updater import check_for_update, install_update

BASE_DIR = Path(__file__).resolve().parent.parent


def title_from_message(text: str) -> str:
    clean = " ".join(text.strip().split())
    if not clean:
        return "New chat"
    return clean if len(clean) <= 42 else clean[:39].rstrip() + "..."


class ChatBackend:
    def __init__(self):
        self.config = load_config()
        self.logger = setup_logging(LOG_DIR)
        self.db = Database(DATA_DIR / "personal_ai.db")
        self.user = self.db.get_user()
        self.llm = OllamaClient(
            base_url=self.config["ollama_url"],
            model=self.config["model"],
            logger=self.logger,
        )
        self.tools = ToolRegistry(BASE_DIR, DATA_DIR, self.logger)

    def ensure_user(self, name: str):
        if self.user is None:
            self.user = self.db.create_user(name.strip() or "User")
        self.db.repair_invalid_memory_confidence(self.user["id"])
        return self.user

    def health_error(self) -> str | None:
        if not self.llm.health_check():
            return "XemAi cannot reach Ollama. Start Ollama, then reopen XemAi."
        if not self.llm.model_available():
            model = self.config["model"]
            return f"The model '{model}' is not installed.\n\nRun: ollama pull {model}"
        return None

    def chats(self):
        return self.db.list_chats(self.user["id"])

    def get_chat(self, chat_id: int):
        return self.db.get_chat(chat_id)

    def create_chat(self):
        return self.db.create_chat(self.user["id"], "New chat")

    def messages(self, chat_id: int):
        return self.db.get_recent_messages(chat_id, limit=500)

    def capabilities(self) -> list[str]:
        return build_capability_status(self.config, self.tools)

    def save_settings(self, *, assistant_name: str, model: str, api_key: str = ""):
        self.config["assistant_name"] = assistant_name.strip() or "XemAi"
        self.config["model"] = model.strip() or "qwen3:8b"
        if api_key.strip():
            ok, msg = self.tools.test_web_search_key(api_key.strip())
            if not ok:
                raise RuntimeError(msg)
            save_ollama_api_key(DATA_DIR, api_key.strip())
        save_config(self.config)
        self.llm = OllamaClient(
            base_url=self.config["ollama_url"],
            model=self.config["model"],
            logger=self.logger,
        )
        self.tools = ToolRegistry(BASE_DIR, DATA_DIR, self.logger)

    def web_test(self) -> tuple[bool, str]:
        return self.tools.test_saved_web_search()

    def rate_chat(self, chat_id: int, score: int, note: str = "") -> None:
        score = int(score)
        if not 0 <= score <= 10:
            raise ValueError("Score must be from 0 to 10.")
        chat = self.db.get_chat(chat_id)
        if chat is None or chat["user_id"] != self.user["id"]:
            raise ValueError("Chat not found.")
        self.db.add_chat_feedback(
            self.user["id"], chat_id, score, note.strip()
        )

    def check_update(self):
        url = self.config.get("update_manifest_url", "").strip()
        return check_for_update(url) if url else None

    def install_update(self, manifest):
        return install_update(
            base_dir=BASE_DIR,
            manifest=manifest,
            logger=self.logger,
        )

    def send(self, chat_id: int, text: str, status_callback=None) -> str:
        # Tkinter stays on the UI thread. Use a separate SQLite connection for
        # response generation so the UI remains responsive and thread-safe.
        worker_db = Database(DATA_DIR / "personal_ai.db")
        try:
            was_empty = not worker_db.chat_has_messages(chat_id)
            worker_db.add_message(chat_id, "user", text)

            chat = worker_db.get_chat(chat_id)
            if was_empty and chat["title"] in {"New chat", "Untitled"}:
                worker_db.rename_chat(chat_id, title_from_message(text))

            user = worker_db.get_user()
            memories = worker_db.relevant_memories(
                user["id"], text, limit=int(self.config.get("memory_limit", 25))
            )
            feedback = worker_db.recent_chat_feedback(user["id"], limit=8)

            tools = ToolRegistry(BASE_DIR, DATA_DIR, self.logger)
            llm = OllamaClient(
                base_url=self.config["ollama_url"],
                model=self.config["model"],
                logger=self.logger,
            )

            system_prompt = build_system_prompt(
                user,
                memories,
                feedback_rows=feedback,
                tool_status=tools.status_lines(),
                assistant_name=self.config.get("assistant_name", "XemAi"),
                capability_status=build_capability_status(self.config, tools),
            )
            history = worker_db.get_recent_messages(
                chat_id, limit=int(self.config.get("history_messages", 30))
            )
            messages = [{"role": "system", "content": system_prompt}]
            comparison_query = is_ai_comparison_query(text)
            self_query = is_self_knowledge_query(text)

            # For self-knowledge questions, old generic model self-descriptions
            # are not trusted. Rebuild the tail so runtime facts win.
            for i, row in enumerate(history):
                if row["role"] not in {"user", "assistant"}:
                    continue

                is_latest_user = (
                    i == len(history) - 1
                    and row["role"] == "user"
                    and row["content"] == text
                )
                if self_query and is_latest_user:
                    continue

                if (
                    self_query
                    and row["role"] == "assistant"
                    and looks_like_stale_self_description(row["content"])
                ):
                    continue

                messages.append(
                    {"role": row["role"], "content": row["content"]}
                )

            if self_query:
                messages.append({
                    "role": "system",
                    "content": build_authoritative_self_context(
                        self.config, tools
                    ),
                })
                messages.append({"role": "user", "content": text})

            if tools.web_search_enabled and should_force_web_search(text):
                if status_callback:
                    status_callback("Searching the web...")
                result = tools.execute(
                    "web_search", {"query": text, "max_results": 5}
                )
                messages.append({
                    "role": "system",
                    "content": (
                        "A live web search was automatically run. Use the results if "
                        "successful. If it returned an error, state that error and do "
                        "not claim web access does not exist.\n\n"
                        f"LIVE_WEB_SEARCH_RESULT:\n{result}"
                    ),
                })

            answer = llm.agent_chat(
                messages,
                tool_registry=tools,
                max_tool_rounds=int(self.config.get("max_tool_rounds", 6)),
            )

            if self_query and looks_like_stale_self_description(answer):
                self.logger.warning(
                    "Rejected stale XemAi self-description draft | chat_id=%s",
                    chat_id,
                )
                retry_messages = list(messages)
                retry_messages.append({
                    "role": "system",
                    "content": (
                        "RESPONSE VALIDATION FAILURE: The previous draft used a "
                        "stale or generic model self-description. Regenerate the "
                        "answer now. You are XemAi, not an unnamed AI. Use the "
                        "authoritative runtime self-knowledge above. Do not "
                        "invent a training cutoff. Do not claim you cannot "
                        "compare yourself with ChatGPT or another AI. Give a "
                        "direct, reasoned answer and distinguish the underlying "
                        "local model from XemAi as the complete application."
                    ),
                })
                answer = llm.agent_chat(
                    retry_messages,
                    tool_registry=tools,
                    max_tool_rounds=int(self.config.get("max_tool_rounds", 6)),
                )

                if looks_like_stale_self_description(answer):
                    self.logger.warning(
                        "Second stale XemAi self-description rejected | chat_id=%s",
                        chat_id,
                    )
                    if comparison_query:
                        answer = build_ai_comparison_fallback(text, self.config)
                    else:
                        answer = build_self_knowledge_fallback(
                            text, self.config, tools
                        )

            worker_db.add_message(chat_id, "assistant", answer)

            if self.config.get("auto_memory", True):
                extract_and_store_memories(
                    llm=llm,
                    db=worker_db,
                    user_id=user["id"],
                    chat_id=chat_id,
                    user_message=text,
                    logger=self.logger,
                )
            return answer
        finally:
            worker_db.close()

    def close(self):
        self.db.close()
