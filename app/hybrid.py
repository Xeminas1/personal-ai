from __future__ import annotations

import errno
import math
import re
import socket
import ssl
import time
import urllib.error
from pathlib import Path
from typing import Any

from .llm import OllamaClient
from .secrets import load_hybrid_worker_client_token


def _error_diagnostics(error: BaseException | None) -> dict:
    """Inspect bounded typed causes only; never parse or export error text."""
    result = {"error_category": "none", "http_status": -1, "errno": -1, "winerror": -1}
    if error is None:
        return result
    result["error_category"] = "model_error"
    pending, seen, priority = [error], set(), 99
    while pending and len(seen) < 16:
        current = pending.pop()
        if not isinstance(current, BaseException) or id(current) in seen:
            continue
        seen.add(id(current))
        for key in ("errno", "winerror"):
            if isinstance(current, OSError):
                value = getattr(current, key, None)
                if isinstance(value, int) and not isinstance(value, bool) and -(2**31) <= value < 2**31 and result[key] == -1:
                    result[key] = value
        number = getattr(current, "errno", None) if isinstance(current, OSError) else None
        windows = getattr(current, "winerror", None) if isinstance(current, OSError) else None
        number = number if isinstance(number, int) and not isinstance(number, bool) else None
        windows = windows if isinstance(windows, int) and not isinstance(windows, bool) else None
        category, rank = "model_error", 90
        if isinstance(current, urllib.error.HTTPError):
            category, rank = "http", 0
            code = current.code
            if isinstance(code, int) and not isinstance(code, bool) and 100 <= code <= 599:
                result["http_status"] = code
        elif isinstance(current, ssl.SSLCertVerificationError):
            category, rank = "tls_verification", 1
        elif isinstance(current, ssl.SSLError):
            category, rank = "tls", 2
        elif isinstance(current, socket.gaierror):
            category, rank = "dns", 3
        elif isinstance(current, TimeoutError) or number == errno.ETIMEDOUT or windows == 10060:
            category, rank = "timeout", 4
        elif isinstance(current, ConnectionRefusedError) or number == errno.ECONNREFUSED or windows == 10061:
            category, rank = "refused", 5
        elif isinstance(current, ConnectionResetError) or number == errno.ECONNRESET or windows == 10054:
            category, rank = "reset", 6
        elif isinstance(current, ConnectionAbortedError) or number == errno.ECONNABORTED or windows == 10053:
            category, rank = "aborted", 7
        elif number in {errno.ENETUNREACH, errno.EHOSTUNREACH, errno.ENETDOWN} or windows in {10050, 10051, 10065}:
            category, rank = "unreachable", 8
        elif isinstance(current, (urllib.error.URLError, ConnectionError, OSError)):
            category, rank = "connection", 80
        if rank < priority:
            result["error_category"], priority = category, rank
        cause = current.__cause__ or current.__context__
        if isinstance(cause, BaseException):
            pending.append(cause)
        if isinstance(current, urllib.error.URLError) and isinstance(current.reason, BaseException):
            pending.append(current.reason)
    return result


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

    def teacher_review(self, question: str, draft: str) -> dict[str, Any]:
        return self._request(
            "/api/teacher/review",
            payload={"question": question, "draft": draft},
            timeout=30.25,
        )

    def specialist_pass(
        self, role: str, question: str, context: str, *,
        draft: str = "", timeout: float = 25.0,
    ) -> dict[str, Any]:
        budget = _specialist_budget(timeout)
        return self._request(
            "/api/agents/run",
            payload={
                "role": role, "question": question, "context": context,
                "draft": draft, "timeout_seconds": budget, "model": self.model,
            },
            timeout=budget + 0.25,
        )


def _specialist_budget(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 2:
        raise ValueError("Specialist budget is unavailable.")
    return min(30.0, float(value))


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
        except Exception:
            self.logger.warning("Hybrid local model discovery failed")
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
        started = time.monotonic()
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
            self.worker_failed_for_request = False
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
            self._log_attempt("worker_health", started)
            return dict(self.route_info)
        except Exception as e:
            self._log_attempt("worker_health", started, e)
            # Keep this turn on its selected fallback, including tool rounds,
            # answer retries and memory extraction. The next turn can recover.
            self.worker_failed_for_request = True
            self.logger.info("Hybrid worker unavailable; using local fallback")
            return self._local_info()

    def _log_attempt(self, stage: str, started: float, error: BaseException | None = None) -> None:
        try:
            details = _error_diagnostics(error)
            turn_id = getattr(self, "turn_id", None)
            turn_id = turn_id if isinstance(turn_id, str) and re.fullmatch(r"[0-9a-f]{16}", turn_id) else "none"
            self.logger.info(
                "Hybrid attempt | turn_id=%s stage=%s elapsed_ms=%d success=%s error_category=%s http_status=%d errno=%d winerror=%d",
                turn_id, stage, max(0, int((time.monotonic() - started) * 1000)), error is None,
                details["error_category"], details["http_status"], details["errno"], details["winerror"],
            )
        except Exception:
            # Diagnostics must not change a valid response or fallback behavior.
            pass

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


    def review_answer(self, question: str, draft: str) -> dict[str, Any] | None:
        """Ask the stronger worker-only teacher for one independent second pass."""
        if self.active_client is not self.worker_client or self.worker_failed_for_request:
            return None
        started = time.monotonic()
        try:
            result = self.worker_client.teacher_review(question, draft)
            if not result.get("ok") or not str(result.get("answer") or "").strip():
                return None
            self._log_attempt("teacher_review", started)
            return result
        except Exception as e:
            self._log_attempt("teacher_review", started, e)
            self.logger.info("Local teacher unavailable; keeping original draft")
            return None

    def specialist_pass(
        self, role: str, question: str, context: str, *,
        draft: str = "", timeout: float = 25.0,
    ) -> dict[str, Any] | None:
        """Run one bounded PC pass without changing the selected answer route."""
        if (
            self.active_client is not self.worker_client
            or self.worker_failed_for_request
            or self.route_info.get("compute") != "remote_worker"
        ):
            return None
        started = time.monotonic()
        try:
            budget = _specialist_budget(timeout)
            result = self.worker_client.specialist_pass(
                role, question, context, draft=draft, timeout=budget,
            )
            if time.monotonic() - started > budget + 0.25:
                raise TimeoutError("Specialist response exceeded its budget.")
            if not isinstance(result, dict) or result.get("ok") is not True or result.get("role") != role:
                raise ValueError("Invalid specialist response.")
            output, model = result.get("output"), result.get("model")
            if (
                not isinstance(output, str) or not output.strip() or len(output) > 6000
                or not isinstance(model, str) or not model.strip()
                or len(model) > 256 or not model.isprintable()
            ):
                raise ValueError("Invalid specialist response.")
            if any(
                (ord(character) < 32 and character not in "\t\n\r") or 127 <= ord(character) <= 159
                for character in output
            ):
                raise ValueError("Invalid specialist response.")
            output.encode("utf-8")
            self._log_attempt("specialist", started)
            return result
        except Exception as error:
            self._log_attempt("specialist", started, error)
            return None

    def local_review(
        self, question: str, draft: str, context: str, *, timeout: float = 10.0,
    ) -> dict[str, Any] | None:
        """Delegate to the selected fallback without probing or changing routes."""
        if self.active_client is not self.local_client or self.route_info.get("compute") != "local_host":
            return None
        local_client = self.local_client
        started = time.monotonic()
        try:
            result = local_client.local_review(question, draft, context, timeout=timeout)
            self._log_attempt("local_review", started, None if result is not None else RuntimeError())
            return result
        except Exception as error:
            self._log_attempt("local_review", started, error)
            return None

    def _local_answer_messages(self, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Adapt only the bound answer prompt; leave extraction/history intact."""
        origin = getattr(self, "answer_system_prompt_origin", None)
        compact = getattr(self, "local_system_prompt", None)
        context = getattr(self, "local_answer_context", None)
        compact = compact if isinstance(compact, str) and compact.strip() else None
        context = context if isinstance(context, str) and context.strip() else None
        if (
            not isinstance(origin, str) or not origin.strip()
            or not messages or not isinstance(messages[0], dict)
            or messages[0].get("role") != "system"
            or (
                messages[0].get("content") != origin
                and (compact is None or messages[0].get("content") != compact)
            )
        ):
            return messages
        adapted = messages
        if compact is not None and messages[0].get("content") != compact:
            adapted = [{**messages[0], "content": compact}, *messages[1:]]
        if context is not None and not any(
            isinstance(message, dict) and message.get("role") == "system" and message.get("content") == context
            for message in adapted
        ):
            adapted = [*adapted, {"role": "system", "content": context}]
        return adapted

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
            started = time.monotonic()
            try:
                response = self.worker_client.chat_raw(
                    messages,
                    json_mode=json_mode,
                    tools=tools,
                )
                self.model = self.worker_client.model
                self._log_attempt("worker_chat", started)
                return response
            except Exception as e:
                self._log_attempt("worker_chat", started, e)
                self.logger.warning("Hybrid worker generation failed; falling back locally")
                self.worker_failed_for_request = True
                self._local_info()

        response = self.local_client.chat_raw(
            self._local_answer_messages(messages),
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
