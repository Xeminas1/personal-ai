from __future__ import annotations

import ast
import json
import math
import operator
import re
import urllib.error
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .secrets import load_ollama_api_key


class ToolError(RuntimeError):
    pass


def should_force_web_search(text: str) -> bool:
    """
    Deterministic routing for requests that clearly require live search.
    This avoids relying entirely on a small local model to decide whether
    to call the web_search tool.
    """
    lower = text.lower()
    explicit_phrases = (
        "search the web",
        "search online",
        "browse the web",
        "browse online",
        "look it up",
        "look up ",
        "check the web",
        "check online",
        "find online",
    )
    if any(phrase in lower for phrase in explicit_phrases):
        return True

    freshness_terms = (
        "latest ",
        "latest news",
        "recent news",
        "current news",
        "today's news",
        "todays news",
        "up to date",
        "up-to-date",
        "what happened today",
    )
    return any(term in lower for term in freshness_terms)


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title_parts.append(text)
        self.parts.append(text)


_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_ALLOWED_UNARY = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_ALLOWED_FUNCS = {
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
}


def _safe_eval(node):
    if isinstance(node, ast.Expression):
        return _safe_eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINOPS:
        left = _safe_eval(node.left)
        right = _safe_eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 20:
            raise ToolError("Exponent is too large.")
        return _ALLOWED_BINOPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
        return _ALLOWED_UNARY[type(node.op)](_safe_eval(node.operand))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        fn = _ALLOWED_FUNCS.get(node.func.id)
        if fn is None:
            raise ToolError("Function is not allowed.")
        return fn(*[_safe_eval(arg) for arg in node.args])
    raise ToolError("Expression contains unsupported syntax.")


class ToolRegistry:
    def __init__(self, base_dir: Path, data_dir: Path, logger):
        self.base_dir = base_dir.resolve()
        self.data_dir = data_dir.resolve()
        self.workspace = (base_dir / "workspace").resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.logger = logger

    @property
    def web_search_enabled(self) -> bool:
        return bool(load_ollama_api_key(self.data_dir))

    def status_lines(self) -> list[str]:
        return [
            "calculator: enabled",
            "current_time: enabled",
            "web_fetch: enabled (direct HTTPS/HTTP page fetch)",
            (
                "web_search: configured (run /webtest to verify connection)"
                if self.web_search_enabled
                else "web_search: disabled (run /websetup to configure)"
            ),
            "workspace_list: enabled",
            "workspace_read: enabled",
            "workspace_write: enabled",
            "feedback learning: enabled",
        ]

    def definitions(self) -> list[dict[str, Any]]:
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "calculator",
                    "description": "Safely calculate a mathematical expression.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "expression": {
                                "type": "string",
                                "description": "Math expression such as (25*4)+sqrt(81)"
                            }
                        },
                        "required": ["expression"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "current_time",
                    "description": "Get the current date and time for a timezone.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "timezone": {
                                "type": "string",
                                "description": "IANA timezone such as Europe/London. Use local for computer local time."
                            }
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "web_fetch",
                    "description": "Fetch current text from a specific HTTP or HTTPS webpage.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "Full webpage URL"}
                        },
                        "required": ["url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "workspace_list",
                    "description": "List files and folders inside the AI's local workspace directory.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Relative workspace path; default ."}
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "workspace_read",
                    "description": "Read a UTF-8 text file inside the local workspace.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Relative path inside workspace"},
                            "max_chars": {"type": "integer", "description": "Maximum characters to return"}
                        },
                        "required": ["path"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "workspace_write",
                    "description": "Create or replace a UTF-8 text file inside the local workspace. Only use when the user asks to create or change a file.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Relative path inside workspace"},
                            "content": {"type": "string", "description": "Complete file contents"}
                        },
                        "required": ["path", "content"],
                    },
                },
            },
        ]

        if self.web_search_enabled:
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": "web_search",
                        "description": "Search the live web for current information. Use for recent, changing, or externally verifiable facts.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "query": {"type": "string", "description": "Search query"},
                                "max_results": {
                                    "type": "integer",
                                    "description": "Number of results, 1-10"
                                },
                            },
                            "required": ["query"],
                        },
                    },
                }
            )
        return tools

    def _safe_workspace_path(self, relative: str) -> Path:
        relative = (relative or ".").strip()
        target = (self.workspace / relative).resolve()
        if target != self.workspace and self.workspace not in target.parents:
            raise ToolError("Path escapes the allowed workspace.")
        return target

    def execute(self, name: str, arguments: dict[str, Any] | None) -> str:
        args = arguments or {}
        self.logger.info("Tool call | name=%s", name)

        try:
            if name == "calculator":
                result = self.calculator(str(args.get("expression", "")))
            elif name == "current_time":
                result = self.current_time(str(args.get("timezone", "local")))
            elif name == "web_search":
                result = self.web_search(
                    str(args.get("query", "")),
                    int(args.get("max_results", 5) or 5),
                )
            elif name == "web_fetch":
                result = self.web_fetch(str(args.get("url", "")))
            elif name == "workspace_list":
                result = self.workspace_list(str(args.get("path", ".")))
            elif name == "workspace_read":
                result = self.workspace_read(
                    str(args.get("path", "")),
                    int(args.get("max_chars", 20000) or 20000),
                )
            elif name == "workspace_write":
                result = self.workspace_write(
                    str(args.get("path", "")),
                    str(args.get("content", "")),
                )
            else:
                raise ToolError(f"Unknown tool: {name}")
        except Exception as e:
            self.logger.warning("Tool failure | name=%s error=%r", name, e)
            return json.dumps({"ok": False, "error": str(e)})

        self.logger.info("Tool success | name=%s", name)
        return json.dumps({"ok": True, "result": result}, ensure_ascii=False)

    def calculator(self, expression: str):
        if not expression or len(expression) > 500:
            raise ToolError("Expression is empty or too long.")
        tree = ast.parse(expression, mode="eval")
        result = _safe_eval(tree)
        if isinstance(result, float) and not math.isfinite(result):
            raise ToolError("Result is not finite.")
        return result

    def current_time(self, timezone: str = "local") -> dict[str, str]:
        if not timezone or timezone.lower() == "local":
            now = datetime.now().astimezone()
        else:
            try:
                now = datetime.now(ZoneInfo(timezone))
            except Exception as e:
                raise ToolError(f"Unknown timezone: {timezone}") from e
        return {
            "iso": now.isoformat(timespec="seconds"),
            "timezone": str(now.tzinfo),
        }

    def _ollama_web_search_request(
        self,
        *,
        key: str,
        query: str,
        max_results: int = 5,
        timeout: int = 45,
    ) -> dict[str, Any]:
        query = query.strip()
        if not query:
            raise ToolError("Search query is empty.")

        max_results = max(1, min(10, int(max_results)))
        payload = json.dumps(
            {"query": query, "max_results": max_results}
        ).encode("utf-8")
        req = urllib.request.Request(
            "https://ollama.com/api/web_search",
            data=payload,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "User-Agent": "PersonalAI/0.1.7",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code == 401:
                raise ToolError(
                    "Ollama rejected the API key (HTTP 401 Unauthorized). "
                    "Create a valid Ollama API key and run /websetup again."
                ) from e
            raise ToolError(
                f"Ollama web search HTTP {e.code}: {body[:300]}"
            ) from e
        except urllib.error.URLError as e:
            raise ToolError(f"Web search connection failed: {e}") from e

        if not isinstance(parsed, dict):
            raise ToolError("Ollama returned an unexpected web-search response.")
        return parsed

    def test_web_search_key(self, key: str) -> tuple[bool, str]:
        key = key.strip()
        if not key:
            return False, "No API key was provided."

        try:
            parsed = self._ollama_web_search_request(
                key=key,
                query="Ollama",
                max_results=1,
                timeout=30,
            )
        except ToolError as e:
            return False, str(e)

        results = parsed.get("results", [])
        if not isinstance(results, list):
            return False, "Ollama returned an unexpected response."
        return True, "Ollama web search connection verified."

    def test_saved_web_search(self) -> tuple[bool, str]:
        key = load_ollama_api_key(self.data_dir)
        if not key:
            return False, "No Ollama API key is configured. Run /websetup."
        return self.test_web_search_key(key)

    def web_search(self, query: str, max_results: int = 5):
        key = load_ollama_api_key(self.data_dir)
        if not key:
            raise ToolError("Web search is not configured. Run /websetup.")

        parsed = self._ollama_web_search_request(
            key=key,
            query=query,
            max_results=max_results,
        )

        results = parsed.get("results", [])
        cleaned = []
        for item in results[:max(1, min(10, int(max_results)))]:
            cleaned.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "content": str(item.get("content", ""))[:3000],
                }
            )
        return {"query": query.strip(), "results": cleaned}

    def web_fetch(self, url: str):
        url = url.strip()
        if not re.match(r"^https?://", url, flags=re.I):
            raise ToolError("Only HTTP and HTTPS URLs are allowed.")

        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 PersonalAI/0.1.6"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                content_type = response.headers.get("Content-Type", "")
                raw = response.read(1_500_000)
        except urllib.error.HTTPError as e:
            raise ToolError(f"Webpage returned HTTP {e.code}.") from e
        except urllib.error.URLError as e:
            raise ToolError(f"Could not fetch webpage: {e}") from e

        if "text" not in content_type and "json" not in content_type:
            raise ToolError(f"Unsupported page content type: {content_type}")

        text = raw.decode("utf-8", errors="replace")
        if "html" in content_type.lower() or "<html" in text[:500].lower():
            parser = _TextExtractor()
            parser.feed(text)
            title = " ".join(parser.title_parts).strip()
            body = " ".join(parser.parts)
        else:
            title = ""
            body = text

        body = re.sub(r"\s+", " ", body).strip()
        return {
            "url": url,
            "title": title,
            "content": body[:12000],
            "truncated": len(body) > 12000,
        }

    def workspace_list(self, path: str = "."):
        target = self._safe_workspace_path(path)
        if not target.exists():
            raise ToolError("Path does not exist.")
        if not target.is_dir():
            raise ToolError("Path is not a directory.")

        items = []
        for child in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
            rel = child.relative_to(self.workspace)
            items.append(
                {
                    "path": str(rel).replace("\\", "/"),
                    "type": "directory" if child.is_dir() else "file",
                    "size": child.stat().st_size if child.is_file() else None,
                }
            )
        return items[:500]

    def workspace_read(self, path: str, max_chars: int = 20000):
        target = self._safe_workspace_path(path)
        if not target.is_file():
            raise ToolError("File does not exist.")
        if target.stat().st_size > 5_000_000:
            raise ToolError("File is too large for this text reader.")
        max_chars = max(500, min(100000, int(max_chars)))
        text = target.read_text(encoding="utf-8", errors="replace")
        return {
            "path": str(target.relative_to(self.workspace)).replace("\\", "/"),
            "content": text[:max_chars],
            "truncated": len(text) > max_chars,
        }

    def workspace_write(self, path: str, content: str):
        target = self._safe_workspace_path(path)
        if target == self.workspace:
            raise ToolError("A file path is required.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return {
            "path": str(target.relative_to(self.workspace)).replace("\\", "/"),
            "chars_written": len(content),
        }
