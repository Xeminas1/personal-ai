from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any


class OllamaError(RuntimeError):
    pass


class OllamaClient:
    def __init__(self, base_url: str, model: str, logger):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.logger = logger

    def _request(
        self,
        path: str,
        payload: dict[str, Any] | None = None,
        timeout: int = 600,
    ) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = None
        headers = {"Content-Type": "application/json"}

        if payload is not None:
            data = json.dumps(payload).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method="POST" if payload is not None else "GET",
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            raise OllamaError(
                f"Ollama returned HTTP {e.code}: {body}"
            ) from e
        except urllib.error.URLError as e:
            raise OllamaError(
                "Could not connect to Ollama. Make sure Ollama is installed "
                "and running."
            ) from e
        except TimeoutError as e:
            raise OllamaError("The local model request timed out.") from e

    def health_check(self) -> bool:
        try:
            self._request("/api/tags", timeout=10)
            return True
        except Exception as e:
            self.logger.debug("Ollama health check failed: %r", e)
            return False

    def installed_models(self) -> list[dict[str, Any]]:
        data = self._request("/api/tags", timeout=10)
        return [
            item for item in data.get("models", [])
            if isinstance(item, dict)
        ]

    def running_models(self) -> list[dict[str, Any]]:
        data = self._request("/api/ps", timeout=10)
        return [
            item for item in data.get("models", [])
            if isinstance(item, dict)
        ]

    @staticmethod
    def _model_name(item: dict[str, Any]) -> str:
        return str(item.get("name") or item.get("model") or "").strip()

    @classmethod
    def _qwen_models(cls, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            item for item in items
            if "qwen" in cls._model_name(item).lower()
        ]

    def discover_runtime_model(
        self,
        *,
        preferred: str | None = None,
    ) -> dict[str, Any]:
        preferred = str(preferred or self.model or "").strip()
        installed = self.installed_models()
        try:
            running = self.running_models()
        except Exception as e:
            self.logger.debug("Ollama /api/ps discovery failed: %r", e)
            running = []

        installed_qwen = self._qwen_models(installed)
        running_qwen = self._qwen_models(running)

        running_selected = (
            max(
                running_qwen,
                key=lambda item: str(item.get("expires_at", "")),
            )
            if running_qwen
            else None
        )
        installed_selected = (
            max(
                installed_qwen,
                key=lambda item: str(item.get("modified_at", "")),
            )
            if installed_qwen
            else None
        )

        running_name = (
            self._model_name(running_selected)
            if running_selected
            else ""
        )
        installed_name = (
            self._model_name(installed_selected)
            if installed_selected
            else ""
        )

        # A model that is running only because the old config launched it
        # should not permanently trap auto-detection on that stale value.
        # If a different Qwen build was installed more recently, prefer it.
        if (
            running_selected
            and running_name
            and running_name != preferred
        ):
            selected = running_selected
            source = "ollama_running"
        elif (
            installed_selected
            and installed_name
            and installed_name != preferred
        ):
            selected = installed_selected
            source = "ollama_installed_recent"
        elif running_selected:
            selected = running_selected
            source = "ollama_running"
        elif installed_selected:
            selected = installed_selected
            source = "ollama_installed_recent"
        else:
            selected = None
            source = "configured_fallback"

        model = self._model_name(selected) if selected else preferred
        if model:
            self.model = model

        info = {
            "model": model or "unknown",
            "source": source,
            "installed_qwen": [
                self._model_name(item) for item in installed_qwen
                if self._model_name(item)
            ],
            "running_qwen": [
                self._model_name(item) for item in running_qwen
                if self._model_name(item)
            ],
        }
        self.logger.info(
            "Ollama runtime model discovery | model=%s source=%s installed_qwen=%s running_qwen=%s",
            info["model"],
            info["source"],
            ",".join(info["installed_qwen"]) or "none",
            ",".join(info["running_qwen"]) or "none",
        )
        return info

    def model_available(self, model: str | None = None) -> bool:
        target = str(model or self.model).strip()
        try:
            names = {
                self._model_name(item)
                for item in self.installed_models()
            }
            return target in names or f"{target}:latest" in names
        except Exception:
            return False

    def chat_raw(
        self,
        messages: list[dict[str, Any]],
        *,
        json_mode: bool = False,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if json_mode:
            payload["format"] = "json"
        if tools:
            payload["tools"] = tools

        self.logger.debug(
            "LLM request | provider=ollama model=%s messages=%d json=%s tools=%d",
            self.model, len(messages), json_mode, len(tools or [])
        )

        response = self._request("/api/chat", payload=payload)
        message = response.get("message") or {}
        content = message.get("content", "") or ""
        tool_calls = message.get("tool_calls") or []

        self.logger.debug(
            "LLM response | provider=ollama model=%s chars=%d tool_calls=%d done=%s",
            response.get("model", self.model),
            len(content),
            len(tool_calls),
            response.get("done"),
        )

        if not content and not tool_calls:
            raise OllamaError("The local model returned an empty response.")
        return response

    def chat(
        self,
        messages: list[dict[str, Any]],
        *,
        json_mode: bool = False,
    ) -> str:
        response = self.chat_raw(messages, json_mode=json_mode)
        message = response.get("message") or {}
        content = message.get("content", "") or ""
        if not content:
            raise OllamaError("The local model returned no text.")
        return content

    def agent_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        tool_registry,
        max_tool_rounds: int = 6,
    ) -> str:
        conversation = list(messages)
        tools = tool_registry.definitions()

        for round_index in range(max_tool_rounds + 1):
            response = self.chat_raw(conversation, tools=tools)
            assistant_message = response.get("message") or {}
            tool_calls = assistant_message.get("tool_calls") or []

            conversation.append(assistant_message)

            if not tool_calls:
                content = assistant_message.get("content", "") or ""
                if content:
                    return content
                raise OllamaError("The agent finished without a text answer.")

            if round_index >= max_tool_rounds:
                raise OllamaError("Tool-call limit reached before a final answer.")

            for call in tool_calls:
                function = call.get("function") or {}
                name = str(function.get("name", ""))
                arguments = function.get("arguments") or {}
                if isinstance(arguments, str):
                    try:
                        arguments = json.loads(arguments)
                    except json.JSONDecodeError:
                        arguments = {}

                result = tool_registry.execute(name, arguments)
                conversation.append(
                    {
                        "role": "tool",
                        "content": result,
                        "tool_name": name,
                    }
                )

        raise OllamaError("Agent loop ended unexpectedly.")
