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

    def model_available(self) -> bool:
        try:
            data = self._request("/api/tags", timeout=10)
            names = {
                item.get("name", "")
                for item in data.get("models", [])
            }
            return self.model in names or f"{self.model}:latest" in names
        except Exception:
            return False

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        json_mode: bool = False,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if json_mode:
            payload["format"] = "json"

        self.logger.debug(
            "LLM request | provider=ollama model=%s messages=%d json=%s",
            self.model, len(messages), json_mode
        )

        response = self._request("/api/chat", payload=payload)
        message = response.get("message") or {}
        content = message.get("content", "")

        self.logger.debug(
            "LLM response | provider=ollama model=%s chars=%d done=%s",
            response.get("model", self.model),
            len(content),
            response.get("done"),
        )

        if not content:
            raise OllamaError("The local model returned an empty response.")
        return content
