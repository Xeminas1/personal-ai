from __future__ import annotations

from pathlib import Path
from typing import Any

from .llm import OllamaClient
from .secrets import load_hybrid_worker_client_token


class HybridWorkerClient(OllamaClient):
    def __init__(self, base_url: str, token: str, model: str, logger):
        super().__init__(
            base_url=base_url,
            model=model,
            logger=logger,
            extra_headers={"Authorization": f"Bearer {token}"},
            provider_name="xemai-worker",
        )

    def worker_health(self) -> dict[str, Any]:
        return self._request("/api/health", timeout=15)


class HybridOllamaClient(OllamaClient):
    """
    Ollama-compatible client that prefers a paired XemAi worker and falls back
    to the host machine's local Ollama without moving chats/memory off the host.

    The inherited agent loop calls self.chat_raw(), so tool calls still execute
    on the central XemAi host even when model inference happens remotely.
    """

    def __init__(
        self,
        *,
        local_client: OllamaClient,
        worker_client: HybridWorkerClient,
        logger,
        local_fallback_model: str,
    ):
        super().__init__(
            base_url=local_client.base_url,
            model=local_client.model,
            logger=logger,
            provider_name="xemai-hybrid",
        )
        self.is_hybrid = True
        self.local_client = local_client
        self.worker_client = worker_client
        self.local_fallback_model = str(local_fallback_model or local_client.model)
        self.active_client: OllamaClient = local_client
        self.worker_failed_for_request = False
        self.route_info: dict[str, Any] = {
            "model": local_client.model,
            "source": "hybrid_local_fallback",
            "compute": "local_host",
            "compute_name": "Always-on host",
            "worker_available": False,
            "installed_qwen": [],
            "running_qwen": [],
        }

    def _local_info(self) -> dict[str, Any]:
        try:
            info = self.local_client.discover_runtime_model(
                preferred=self.local_fallback_model
            )
        except Exception as e:
            self.logger.warning(
                "Hybrid local model discovery failed | fallback=%s error=%r",
                self.local_fallback_model,
                e,
            )
            self.local_client.model = self.local_fallback_model
            info = {
                "model": self.local_fallback_model,
                "source": "configured_fallback",
                "installed_qwen": [],
                "running_qwen": [],
            }

        self.active_client = self.local_client
        self.model = str(info.get("model") or self.local_client.model)
        self.route_info = {
            **info,
            "source": f"hybrid_local:{info.get('source', 'unknown')}",
            "compute": "local_host",
            "compute_name": "Always-on host",
            "worker_available": False,
        }
        return dict(self.route_info)

    def refresh_route(self) -> dict[str, Any]:
        try:
            health = self.worker_client.worker_health()
            if not health.get("ok", False):
                raise RuntimeError(
                    str(health.get("error") or "Worker health check was not OK.")
                )

            model = str(
                health.get("recommended_model")
                or health.get("model")
                or self.worker_client.model
            ).strip()
            if not model:
                raise RuntimeError("Worker did not report an available model.")

            self.worker_client.model = model
            self.active_client = self.worker_client
            self.model = model
            self.route_info = {
                "model": model,
                "source": "hybrid_worker",
                "compute": "remote_worker",
                "compute_name": str(
                    health.get("machine_name") or "Powerful PC"
                ),
                "worker_available": True,
                "worker_version": str(health.get("version") or "unknown"),
                "worker_url": self.worker_client.base_url,
                "installed_qwen": list(health.get("installed_qwen") or []),
                "running_qwen": list(health.get("running_qwen") or []),
            }
            return dict(self.route_info)
        except Exception as e:
            self.logger.info(
                "Hybrid worker unavailable; using local fallback | url=%s error=%r",
                self.worker_client.base_url,
                e,
            )
            return self._local_info()

    def discover_runtime_model(
        self,
        *,
        preferred: str | None = None,
    ) -> dict[str, Any]:
        self.worker_failed_for_request = False
        return self.refresh_route()

    def health_check(self) -> bool:
        info = self.refresh_route()
        if info.get("compute") == "remote_worker":
            return True
        return self.local_client.health_check()

    def model_available(self, model: str | None = None) -> bool:
        client = self.active_client
        target = str(model or self.model)
        return client.model_available(target)

    def installed_models(self) -> list[dict[str, Any]]:
        return self.active_client.installed_models()

    def running_models(self) -> list[dict[str, Any]]:
        return self.active_client.running_models()

    def chat_raw(
        self,
        messages: list[dict[str, Any]],
        *,
        json_mode: bool = False,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        # Refresh at the first call of a turn so powering the strong PC on/off
        # is detected without restarting XemAi.
        if (
            self.active_client is self.local_client
            and not self.worker_failed_for_request
        ):
            self.refresh_route()

        if self.active_client is self.worker_client:
            try:
                response = self.worker_client.chat_raw(
                    messages,
                    json_mode=json_mode,
                    tools=tools,
                )
                self.model = self.worker_client.model
                return response
            except Exception as e:
                self.logger.warning(
                    "Hybrid worker generation failed; falling back locally | "
                    "url=%s model=%s error=%r",
                    self.worker_client.base_url,
                    self.worker_client.model,
                    e,
                )
                self.worker_failed_for_request = True
                self._local_info()

        response = self.local_client.chat_raw(
            messages,
            json_mode=json_mode,
            tools=tools,
        )
        self.model = self.local_client.model
        return response


def build_llm_client(config, logger, data_dir: Path) -> OllamaClient:
    local = OllamaClient(
        base_url=str(config.get("ollama_url", "http://localhost:11434")),
        model=str(config.get("model", "qwen3:8b")),
        logger=logger,
        provider_name="ollama-local",
    )

    if not config.get("hybrid_enabled", False):
        return local

    worker_url = str(config.get("hybrid_worker_url", "")).strip().rstrip("/")
    token = load_hybrid_worker_client_token(data_dir)
    if not worker_url or not token:
        logger.warning(
            "Hybrid compute enabled but worker URL/token is incomplete; "
            "using local Ollama."
        )
        return local

    worker = HybridWorkerClient(
        base_url=worker_url,
        token=token,
        model=str(config.get("hybrid_worker_model", "qwen3:8b")),
        logger=logger,
    )
    return HybridOllamaClient(
        local_client=local,
        worker_client=worker,
        logger=logger,
        local_fallback_model=str(config.get("model", "qwen3:8b")),
    )
