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
        was_empty = not self.db.chat_has_messages(chat_id)
        self.db.add_message(chat_id, "user", text)

        chat = self.db.get_chat(chat_id)
        if was_empty and chat["title"] in {"New chat", "Untitled"}:
            self.db.rename_chat(chat_id, title_from_message(text))

        user = self.db.get_user()
        memories = self.db.relevant_memories(
            user["id"], text, limit=int(self.config.get("memory_limit", 25))
        )
        feedback = self.db.recent_chat_feedback(user["id"], limit=8)
        system_prompt = build_system_prompt(
            user,
            memories,
            feedback_rows=feedback,
            tool_status=self.tools.status_lines(),
            assistant_name=self.config.get("assistant_name", "XemAi"),
            capability_status=build_capability_status(self.config, self.tools),
        )
        history = self.db.get_recent_messages(
            chat_id, limit=int(self.config.get("history_messages", 30))
        )
        messages = [{"role": "system", "content": system_prompt}]
        for row in history:
            if row["role"] in {"user", "assistant"}:
                messages.append({"role": row["role"], "content": row["content"]})

        if self.tools.web_search_enabled and should_force_web_search(text):
            if status_callback:
                status_callback("Searching the web...")
            result = self.tools.execute(
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

        answer = self.llm.agent_chat(
            messages,
            tool_registry=self.tools,
            max_tool_rounds=int(self.config.get("max_tool_rounds", 6)),
        )
        self.db.add_message(chat_id, "assistant", answer)

        if self.config.get("auto_memory", True):
            extract_and_store_memories(
                llm=self.llm,
                db=self.db,
                user_id=user["id"],
                chat_id=chat_id,
                user_message=text,
                logger=self.logger,
            )
        return answer

    def close(self):
        self.db.close()
