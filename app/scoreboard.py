"""XemAi model scoreboard: run the same graded tasks against local models.

Commands (owner-typed only):
  scoreboard                 Latest results and current progress.
  scoreboard models          Installed models plus suggested candidates for this PC.
  scoreboard pull <model>    Download a model into Ollama (can be large).
  scoreboard run [m1, m2]    Score installed models (default: all installed chat models).
                             The everyday model is also scored with XemAi's full
                             system prompt, to measure what the prompt itself costs.

Runs on the machine with the GPU (the paired PC worker) and talks only to the
local Ollama API. Model-written code is checked for disallowed imports/calls and
run against hidden tests in a short-lived subprocess with a timeout.
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .scoreboard_tasks import CATEGORIES, all_tasks, rule_score

ROOT_DIR = "scoreboard"
PLAIN_PROMPT = "You are XemAi, a helpful assistant. Answer accurately and concisely."
_LOCK = threading.Lock()
_STATE: dict[str, Any] = {"thread": None}
MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,80}(?::[A-Za-z0-9._-]{1,60})?")

# Researched Nov 2026 for a 16 GB GPU + 64 GB RAM; sizes are Ollama download sizes.
CANDIDATES = [
    ("gpt-oss:20b", "14 GB", "General reasoning and tools; fits fully on the GPU (fast)."),
    ("qwen3-coder:30b", "19 GB", "Coding specialist (MoE, ~3B active); spills slightly to RAM but stays quick."),
    ("qwen3.6:35b", "24 GB", "Newest Qwen, strong agentic coding (MoE); heavier RAM offload, slower."),
    ("gemma4:26b", "18 GB", "Google's general model with image input (MoE); partial offload."),
    ("qwen3.6:27b", "17 GB", "Dense Qwen 3.6; strong but likely slow here because it doesn't fit the GPU."),
]

COMMAND = re.compile(r"(?i)^\s*scoreboard(?:\s+(models|run|pull)(?:\s+(.+?))?)?\s*$")
ALLOWED_IMPORTS = {
    "math", "re", "itertools", "collections", "functools", "heapq", "bisect", "string", "datetime",
    "typing", "dataclasses", "statistics", "fractions", "decimal", "operator", "json", "calendar",
    "enum", "copy", "abc", "__future__",
}
BLOCKED_NAMES = {"open", "exec", "eval", "compile", "__import__", "input", "breakpoint", "globals",
                 "locals", "vars", "getattr", "setattr", "delattr", "memoryview", "exit", "quit"}


def is_command(text: str) -> bool:
    return bool(COMMAND.match(str(text or "")))


def root(data_dir: Path) -> Path:
    path = Path(data_dir) / ROOT_DIR
    (path / "runs").mkdir(parents=True, exist_ok=True)
    return path


def _write(path: Path, value: Any) -> None:
    tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


# ------------------------------------------------------------- code sandbox

def target_name(task: dict) -> str:
    match = re.search(r"(?:function|class) (\w+)", task.get("prompt", ""))
    if match:
        return match.group(1)
    match = re.search(r"def (\w+)\(", task.get("prompt", ""))
    return match.group(1) if match else ""


def extract_code(reply: str, name: str) -> str:
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", str(reply or ""), re.S | re.I)
    for block in reversed(blocks):
        if re.search(rf"\b(?:def|class)\s+{re.escape(name)}\b", block):
            return block
    if blocks:
        return blocks[-1]
    return str(reply or "")


def unsafe_reason(code: str) -> str:
    """Why model-written code may not run, or '' if it only uses safe constructs."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return f"syntax error: {exc.msg}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] not in ALLOWED_IMPORTS:
                    return f"import {alias.name} not allowed"
        elif isinstance(node, ast.ImportFrom):
            if (node.module or "").split(".")[0] not in ALLOWED_IMPORTS:
                return f"import from {node.module} not allowed"
        elif isinstance(node, ast.Name) and node.id in BLOCKED_NAMES:
            return f"use of {node.id} not allowed"
        elif isinstance(node, ast.Attribute) and node.attr.startswith("__") and node.attr != "__init__":
            return f"attribute {node.attr} not allowed"
    return ""


_HARNESS = r'''
import json, sys
def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc:
        return
    raise AssertionError("expected " + exc.__name__)
src = open(sys.argv[1], encoding="utf-8").read()
tests = json.load(open(sys.argv[2], encoding="utf-8"))
base = {"raises": raises, "__name__": "solution"}
results = []
try:
    exec(compile(src, "solution.py", "exec"), base)
except Exception as e:
    print(json.dumps({"error": type(e).__name__ + ": " + str(e)[:200]}))
    sys.exit(0)
for t in tests:
    ns = dict(base)
    try:
        exec(t, ns)
        results.append(True)
    except Exception:
        results.append(False)
print(json.dumps({"results": results}))
'''


def _console_python() -> str:
    exe = Path(sys.executable)
    if os.name == "nt" and exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        return str(exe.with_name("python.exe"))
    return str(exe)


def run_code(code: str, tests: list[str], timeout: float = 10.0) -> dict:
    reason = unsafe_reason(code)
    if reason:
        return {"score": 0.0, "detail": reason}
    with tempfile.TemporaryDirectory(prefix="xemai_score_") as tmp:
        folder = Path(tmp)
        (folder / "solution.py").write_text(code, encoding="utf-8")
        (folder / "tests.json").write_text(json.dumps(tests), encoding="utf-8")
        (folder / "harness.py").write_text(_HARNESS, encoding="utf-8")
        kwargs: dict[str, Any] = {"cwd": tmp, "capture_output": True, "text": True, "timeout": timeout,
                                  "env": {"PYTHONIOENCODING": "utf-8", "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")}}
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        try:
            proc = subprocess.run([_console_python(), "-I", "harness.py", "solution.py", "tests.json"], **kwargs)
        except subprocess.TimeoutExpired:
            return {"score": 0.0, "detail": "timed out"}
    try:
        data = json.loads((proc.stdout or "").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"score": 0.0, "detail": "no result"}
    if "error" in data:
        return {"score": 0.0, "detail": data["error"]}
    results = data.get("results") or []
    passed = sum(1 for r in results if r is True)
    return {"score": passed / max(1, len(tests)), "detail": f"{passed}/{len(tests)} tests passed"}


def grade(task: dict, reply: str) -> dict:
    if task["category"] == "coding":
        return run_code(extract_code(reply, target_name(task)), task["tests"])
    return {"score": rule_score(task, reply), "detail": ""}


# ------------------------------------------------------------- ollama calls

def _post(url: str, path: str, payload: dict, timeout: float) -> dict:
    request = urllib.request.Request(url.rstrip("/") + path, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode() or "{}")


def _get(url: str, path: str, timeout: float = 15) -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(url.rstrip("/") + path, timeout=timeout) as response:
        return json.loads(response.read().decode() or "{}")


def installed_models(url: str) -> list[dict]:
    return [m for m in _get(url, "/api/tags").get("models", []) if isinstance(m, dict)]


def chat_models(url: str) -> list[str]:
    names = []
    for item in installed_models(url):
        name = str(item.get("name") or item.get("model") or "")
        families = " ".join((item.get("details") or {}).get("families") or []).lower()
        if name and "embed" not in name.lower() and "bert" not in families:
            names.append(name)
    return names


def ask(url: str, model: str, messages: list[dict], timeout: float = 600) -> dict:
    started = time.monotonic()
    data = _post(url, "/api/chat", {"model": model, "messages": messages, "stream": False,
                                    "options": {"temperature": 0, "num_predict": 4096, "num_ctx": 8192}}, timeout)
    content = str((data.get("message") or {}).get("content") or "")
    content = re.sub(r"(?s)<think>.*?</think>", "", content).strip()
    eval_count = int(data.get("eval_count") or 0)
    eval_ns = int(data.get("eval_duration") or 0)
    return {"reply": content, "seconds": round(time.monotonic() - started, 2),
            "tokens": eval_count, "tokens_per_second": round(eval_count / (eval_ns / 1e9), 1) if eval_ns else None}


# ---------------------------------------------------------------- scoring run

def summarise(rows: list[dict]) -> dict:
    by_cat = {c: [r["score"] for r in rows if r["category"] == c] for c in CATEGORIES}
    cats = {c: round(100 * sum(v) / len(v), 1) for c, v in by_cat.items() if v}
    speeds = [r["tokens_per_second"] for r in rows if r.get("tokens_per_second")]
    return {"overall": round(sum(cats.values()) / len(cats), 1) if cats else 0.0, "categories": cats,
            "tokens_per_second": round(sum(speeds) / len(speeds), 1) if speeds else None,
            "seconds": round(sum(r.get("seconds") or 0 for r in rows), 1),
            "errors": sum(1 for r in rows if r.get("error"))}


def score_model(url: str, model: str, system_prompt: str, tasks: list[dict],
                progress: Callable[[int], None] | None = None,
                should_stop: Callable[[], bool] = lambda: False) -> list[dict]:
    rows = []
    for index, task in enumerate(tasks):
        if should_stop():
            break
        system = system_prompt + ("\n\n" + task["system_extra"] if task.get("system_extra") else "")
        row = {"task": task["id"], "category": task["category"]}
        try:
            answer = ask(url, model, [{"role": "system", "content": system}] + task["messages"])
            row.update(answer)
            row.update(grade(task, answer["reply"]))
            row["reply"] = answer["reply"][:1500]
        except Exception as exc:  # noqa: BLE001 - a failed call scores 0 and is reported
            row.update({"score": 0.0, "error": f"{type(exc).__name__}: {str(exc)[:160]}"})
        rows.append(row)
        if progress:
            progress(index + 1)
    return rows


def xemai_system_prompt() -> str:
    """XemAi's real everyday system prompt with a neutral, empty profile."""
    from .prompts import build_system_prompt

    user = {"name": "Owner", "personality_notes": "", "communication_preferences": ""}
    return build_system_prompt(user, [], feedback_rows=[], tool_status=[], assistant_name="XemAi")


def _run_job(data_dir: Path, url: str, plan: list[tuple[str, str]], run_id: str) -> None:
    base = root(data_dir)
    tasks = all_tasks()
    prompts = {"plain": PLAIN_PROMPT, "xemai": xemai_system_prompt()}
    results: dict[str, Any] = {"run": run_id, "started": time.time(), "tasks": len(tasks), "entries": []}
    state = {"stage": "running", "run": run_id, "total": len(plan) * len(tasks), "done": 0, "pid": os.getpid()}
    stop = lambda: _read(base / "current.json").get("stage") == "stopping"  # noqa: E731
    try:
        for model, condition in plan:
            if stop():
                break
            state.update({"model": model, "condition": condition})
            offset = state["done"]

            def progress(n, offset=offset):
                state["done"] = offset + n
                _write(base / "current.json", state)

            rows = score_model(url, model, prompts[condition], tasks, progress, stop)
            results["entries"].append({"model": model, "condition": condition, "summary": summarise(rows), "rows": rows})
            _write(base / "runs" / f"{run_id}.json", results)
        results["finished"] = time.time()
        _write(base / "runs" / f"{run_id}.json", results)
        _write(base / "current.json", {"stage": "finished", "run": run_id})
    except Exception as exc:  # noqa: BLE001
        _write(base / "current.json", {"stage": "failed", "run": run_id, "message": str(exc)[:300]})


def start_run(data_dir: Path, url: str, models: list[str] | None, everyday: str) -> dict:
    with _LOCK:
        if busy(data_dir):
            return {"ok": False, "error": "A scoreboard run or model download is already in progress."}
        installed = chat_models(url)
        wanted = [m for m in (models or installed)]
        missing = [m for m in wanted if m not in installed and f"{m}:latest" not in installed]
        if missing:
            return {"ok": False, "error": "Not installed: " + ", ".join(missing) +
                    ". Download with 'scoreboard pull <model>' first."}
        if not wanted:
            return {"ok": False, "error": "No chat models are installed in Ollama on this machine."}
        plan = [(m, "plain") for m in wanted]
        if everyday in wanted:
            plan.append((everyday, "xemai"))
        run_id = time.strftime("%Y%m%d-%H%M%S")
        _write(root(data_dir) / "current.json", {"stage": "running", "run": run_id, "done": 0,
                                                 "total": len(plan) * len(all_tasks()), "pid": os.getpid()})
        thread = threading.Thread(target=_run_job, args=(Path(data_dir), url, plan, run_id), daemon=True,
                                  name="XemAiScoreboard")
        _STATE["thread"] = thread
        thread.start()
        minutes = max(1, round(len(plan) * len(all_tasks()) * 8 / 60))
        return {"ok": True, "run": run_id, "plan": plan,
                "message": f"Scoreboard started: {len(plan)} run(s) × {len(all_tasks())} tasks "
                           f"(roughly {minutes}+ minutes). Type 'scoreboard' to see progress."}


def start_pull(data_dir: Path, url: str, model: str) -> dict:
    if not MODEL_NAME.fullmatch(model or ""):
        return {"ok": False, "error": "That doesn't look like an Ollama model name (e.g. gpt-oss:20b)."}
    with _LOCK:
        if busy(data_dir):
            return {"ok": False, "error": "A scoreboard run or model download is already in progress."}
        base = root(data_dir)
        _write(base / "current.json", {"stage": "pulling", "model": model, "pid": os.getpid(), "percent": 0})

        def pull():
            try:
                request = urllib.request.Request(url.rstrip("/") + "/api/pull",
                                                 data=json.dumps({"model": model, "stream": True}).encode(),
                                                 headers={"Content-Type": "application/json"})
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(request, timeout=7200) as response:
                    last = time.monotonic()
                    for line in response:
                        event = json.loads(line.decode() or "{}")
                        if event.get("error"):
                            raise RuntimeError(event["error"])
                        if event.get("total") and time.monotonic() - last > 2:
                            last = time.monotonic()
                            percent = round(100 * int(event.get("completed") or 0) / int(event["total"]))
                            _write(base / "current.json", {"stage": "pulling", "model": model, "percent": percent,
                                                           "pid": os.getpid()})
                _write(base / "current.json", {"stage": "pulled", "model": model})
            except Exception as exc:  # noqa: BLE001
                _write(base / "current.json", {"stage": "failed", "model": model,
                                               "message": f"Download failed: {str(exc)[:200]}"})

        thread = threading.Thread(target=pull, daemon=True, name="XemAiModelPull")
        _STATE["thread"] = thread
        thread.start()
        return {"ok": True, "message": f"Downloading {model} into Ollama. Type 'scoreboard' to see progress."}


def busy(data_dir: Path) -> str:
    """'run' or 'pull' while active in THIS process (state from a dead process is ignored)."""
    thread = _STATE.get("thread")
    if thread is None or not thread.is_alive():
        return ""
    return "pull" if thread.name == "XemAiModelPull" else "run"


def status(data_dir: Path, url: str | None = None) -> dict:
    base = root(data_dir)
    runs = sorted((base / "runs").glob("*.json"))
    latest = _read(runs[-1]) if runs else {}
    current = _read(base / "current.json")
    if current.get("stage") in {"running", "pulling", "stopping"} and not busy(data_dir):
        current = {**current, "stage": "interrupted"}
    return {"ok": True, "current": current, "latest": {
        "run": latest.get("run"), "finished": latest.get("finished"),
        "entries": [{"model": e["model"], "condition": e["condition"], "summary": e["summary"]}
                    for e in latest.get("entries", [])]}}


# ---------------------------------------------------------------- chat side

def format_table(latest: dict) -> str:
    entries = latest.get("entries") or []
    if not entries:
        return "No scoreboard results yet. Type 'scoreboard run' to score the installed models."
    head = "| Model | Prompt | Overall | Coding | Conversation | Facts/honesty | Instructions | Reasoning | Speed |"
    lines = [head, "|" + "---|" * 9]
    for e in sorted(entries, key=lambda e: -e["summary"]["overall"]):
        s, c = e["summary"], e["summary"]["categories"]
        speed = f"{s['tokens_per_second']} tok/s" if s.get("tokens_per_second") else "?"
        lines.append(f"| {e['model']} | {'XemAi' if e['condition'] == 'xemai' else 'plain'} | **{s['overall']}** | "
                     + " | ".join(str(c.get(k, '-')) for k in CATEGORIES) + f" | {speed} |")
    note = ("\nScores are % of tasks passed (coding: % of hidden tests passed). 'XemAi' rows use XemAi's full "
            "system prompt; compare with the same model's 'plain' row to see what the prompt costs.")
    return f"Scoreboard run {latest.get('run')}{'' if latest.get('finished') else ' (in progress)'}:\n\n" \
           + "\n".join(lines) + note


def format_status(result: dict) -> str:
    current = result.get("current") or {}
    stage = current.get("stage")
    parts = []
    if stage == "running":
        parts.append(f"Running: {current.get('model')} ({current.get('condition')}) — "
                     f"{current.get('done', 0)}/{current.get('total', '?')} tasks done.")
    elif stage == "pulling":
        parts.append(f"Downloading {current.get('model')}: {current.get('percent', 0)}%.")
    elif stage == "pulled":
        parts.append(f"Downloaded {current.get('model')}.")
    elif stage in {"failed", "interrupted"}:
        parts.append(f"Last job {stage}: {current.get('message', 'the worker restarted mid-job')}")
    parts.append(format_table(result.get("latest") or {}))
    return "\n\n".join(parts)


def format_models(installed: list[str]) -> str:
    lines = ["Installed: " + (", ".join(installed) if installed else "none"), "",
             "Suggested candidates for a 16 GB GPU + 64 GB RAM (type 'scoreboard pull <name>'):"]
    for name, size, why in CANDIDATES:
        mark = " (installed)" if name in installed else ""
        lines.append(f"• {name} — {size}{mark}: {why}")
    return "\n".join(lines)


def command(text: str, *, executor, everyday: str) -> str:
    match = COMMAND.match(text or "")
    sub, arg = (match.group(1) or "").lower(), (match.group(2) or "").strip()
    try:
        if sub == "models":
            return format_models(executor.models())
        if sub == "pull":
            if not arg:
                return "Say which model, e.g. 'scoreboard pull gpt-oss:20b'. 'scoreboard models' lists suggestions."
            result = executor.pull(arg)
        elif sub == "run":
            models = [m.strip() for m in re.split(r"[,\s]+", arg) if m.strip()] or None
            result = executor.run(models, everyday)
        else:
            return format_status(executor.status())
        return result.get("message") or result.get("error") or "Done."
    except Exception as exc:  # noqa: BLE001
        if "Unknown worker endpoint" in str(exc):
            return ("Your PC's XemAi worker hasn't loaded the scoreboard yet. It restarts itself onto updates "
                    "(from v0.9.62); if it's older, restart its worker once.")
        return f"The scoreboard is unavailable right now: {str(exc)[:200]}"


class LocalExecutor:
    def __init__(self, data_dir: Path, url: str):
        self.data_dir, self.url = Path(data_dir), url

    def models(self) -> list[str]:
        return chat_models(self.url)

    def status(self) -> dict:
        return status(self.data_dir, self.url)

    def run(self, models, everyday) -> dict:
        return start_run(self.data_dir, self.url, models, everyday)

    def pull(self, model) -> dict:
        return start_pull(self.data_dir, self.url, model)


class WorkerExecutor:
    def __init__(self, client):
        self.client = client

    def models(self) -> list[str]:
        return list(self.client._request("/api/scoreboard/models", timeout=15).get("models") or [])

    def status(self) -> dict:
        return self.client._request("/api/scoreboard/status", timeout=15)

    def run(self, models, everyday) -> dict:
        return self.client._request("/api/scoreboard/run", payload={"models": models}, timeout=30)

    def pull(self, model) -> dict:
        return self.client._request("/api/scoreboard/pull", payload={"model": model}, timeout=30)
