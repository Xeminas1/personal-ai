"""Owner-controlled weight tuning: teach corrections, train on the GPU PC, switch models.

Commands (only when the owner types them exactly):

  teach: <better answer>   Save a correction for XemAi's previous reply in this chat.
  weights                  Status: examples collected, setup, runs, active model.
  weights setup            One-time: build the separate training environment on the PC.
  weights train            Train a new adapter from the collected examples. It is only
                           offered for use if it beats the base model on held-out
                           examples without losing general skill.
  weights use rN           Switch everyday chat to tuned run rN.
  weights rollback         Switch back to the original base model immediately.

Training data never leaves the owner's own machines: it goes from the always-on
host to the paired PC worker over the existing authenticated worker link, and is
stored under data/weight_training/. The base Ollama model is never modified; a
tuned model is a separate Ollama tag that is only used after "weights use".
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

ROOT_DIR = "weight_training"
TUNED_PREFIX = "xemai-qwen-tuned"
MIN_EXAMPLES = 10
MAX_EXAMPLES = 2000
MAX_TEXT = 6000
MAX_UPLOAD_BYTES = 7_000_000  # worker accepts at most 8 MB per request
CONTEXT_TURNS = 6
GOOD_RATING = 9
_LOCK = threading.Lock()
_RUN_NAME = re.compile(r"r[1-9]\d{0,4}")

TEACH = re.compile(r"(?is)^\s*teach\s*:\s*(.+?)\s*$")
WEIGHTS = re.compile(r"(?i)^\s*weights(?:\s+(status|setup|train|rollback|use\s+r[1-9]\d{0,4}))?\s*$")


def is_command(text: str) -> bool:
    return bool(TEACH.match(str(text or ""))) or bool(WEIGHTS.match(str(text or "")))


def root(data_dir: Path) -> Path:
    path = Path(data_dir) / ROOT_DIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def is_tuned_model(name: str) -> bool:
    return str(name or "").strip().lower().startswith(TUNED_PREFIX)


# ------------------------------------------------------------------ active model

def active_tuned_model(data_dir: Path) -> str | None:
    """The tuned Ollama tag the owner switched to on THIS machine, if any."""
    try:
        data = json.loads((Path(data_dir) / ROOT_DIR / "active.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    model = str(data.get("model") or "").strip()
    return model if is_tuned_model(model) else None


def _write_json(path: Path, value: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def set_active(data_dir: Path, run: str | None) -> dict:
    path = root(data_dir) / "active.json"
    if run is None:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return {"ok": True, "model": None}
    if not _RUN_NAME.fullmatch(run):
        return {"ok": False, "error": "Run names look like r1, r2..."}
    report = _read(root(data_dir) / "runs" / run / "report.json")
    if not report.get("passed") or not is_tuned_model(str(report.get("model") or "")):
        return {"ok": False, "error": f"Run {run} has no tuned model that passed its tests."}
    _write_json(path, {"model": report["model"], "run": run, "activated": time.time()})
    return {"ok": True, "model": report["model"]}


# ------------------------------------------------------------------- examples

def _clip(text: str) -> str:
    return str(text or "").strip()[:MAX_TEXT]


def _context(messages: list[dict], upto_index: int) -> list[dict]:
    """Conversation turns up to and including the user prompt at upto_index."""
    window = [m for m in messages[: upto_index + 1] if m.get("role") in {"user", "assistant"}]
    window = window[-CONTEXT_TURNS:]
    while window and window[0].get("role") != "user":
        window.pop(0)
    return [{"role": m["role"], "content": _clip(m.get("content"))} for m in window if _clip(m.get("content"))]


def record_teach(data_dir: Path, db, chat_id: int, answer: str) -> str:
    answer = _clip(answer)
    if len(answer) < 2:
        return "Write the better answer after 'teach:', e.g. 'teach: The capital of Australia is Canberra.'"
    messages = [m for m in db.get_recent_messages(chat_id, limit=40)
                if not TEACH.match(str(m.get("content") or ""))]
    # The reply being corrected is the latest assistant message that follows a user prompt.
    target = next((i for i in range(len(messages) - 1, 0, -1)
                   if messages[i].get("role") == "assistant" and messages[i - 1].get("role") == "user"), None)
    if target is None:
        return "There's no earlier XemAi reply in this chat to correct yet."
    context = _context(messages, target - 1)
    if not context or context[-1]["role"] != "user":
        return "I couldn't find the question that reply was answering."
    row = {"source": "teach", "created": time.time(), "chat_id": int(chat_id),
           "messages": context + [{"role": "assistant", "content": answer}]}
    with _LOCK:
        with (root(data_dir) / "teach.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    total = len(collect_examples(data_dir, db))
    need = max(0, MIN_EXAMPLES - total)
    tail = (f" {need} more needed before the first training run." if need
            else " Type 'weights train' whenever you want XemAi to learn from them.")
    return f"Saved. I'll learn that answer next time my weights are trained ({total} example(s) collected).{tail}"


def _teach_rows(data_dir: Path) -> list[dict]:
    rows = []
    try:
        lines = (Path(data_dir) / ROOT_DIR / "teach.jsonl").read_text(encoding="utf-8").splitlines()
    except OSError:
        return rows
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and isinstance(row.get("messages"), list):
            rows.append({"source": "teach", "messages": row["messages"]})
    return rows


def _rated_rows(db, user_id: int | None) -> list[dict]:
    """Replies the owner rated 9-10 (overall), with the conversation that led to them."""
    if user_id is None:
        return []
    try:
        found = db.conn.execute(
            """
            SELECT f.chat_id, f.assistant_message_id
            FROM feedback AS f
            JOIN messages AS m ON m.id=f.assistant_message_id AND m.role='assistant'
            JOIN message_inference AS mi ON mi.message_id=m.id
            WHERE f.user_id=? AND f.score>=? AND f.aspect='overall'
              AND mi.compute_source IN ('local_host','remote_worker')
            ORDER BY f.id DESC LIMIT ?
            """, (int(user_id), GOOD_RATING, MAX_EXAMPLES),
        ).fetchall()
    except Exception:
        return []
    rows = []
    for chat_id, message_id in found:
        history = db.conn.execute(
            "SELECT id, role, content FROM messages WHERE chat_id=? AND id<=? ORDER BY id DESC LIMIT ?",
            (int(chat_id), int(message_id), CONTEXT_TURNS + 1),
        ).fetchall()
        history = [dict(zip(("id", "role", "content"), h)) for h in reversed(history)]
        if len(history) < 2 or history[-1]["role"] != "assistant" or history[-2]["role"] != "user":
            continue
        context = _context(history, len(history) - 2)
        if context:
            rows.append({"source": "rated", "messages": context + [
                {"role": "assistant", "content": _clip(history[-1]["content"])}]})
    return rows


def _bridge_rows(data_dir: Path) -> list[dict]:
    try:
        from .github_bridge_weight import approved_examples
        return approved_examples(data_dir)
    except Exception:
        return []


def collect_examples(data_dir: Path, db, user_id: int | None = None) -> list[dict]:
    if user_id is None:
        try:
            user = db.get_user()
            user_id = int(user["id"]) if user else None
        except Exception:
            user_id = None
    seen, rows = set(), []
    # Explicit corrections first: if a prompt was both rated and corrected, the correction wins.
    for row in _teach_rows(data_dir) + _bridge_rows(data_dir) + _rated_rows(db, user_id):
        messages = row["messages"]
        if not messages or messages[-1].get("role") != "assistant":
            continue
        key = json.dumps(messages[:-1], ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return rows[:MAX_EXAMPLES]


# ------------------------------------------------------------- local executor
# Runs on the machine with the GPU (normally the PC worker).

def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def venv_python(data_dir: Path) -> Path:
    venv = Path(data_dir) / ROOT_DIR / "venv"
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _console_python() -> str:
    exe = Path(sys.executable)
    if os.name == "nt" and exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        return str(exe.with_name("python.exe"))
    return str(exe)


def _spawn(args: list[str], log: Path, cwd: Path) -> int:
    kwargs: dict[str, Any] = {"stdin": subprocess.DEVNULL, "cwd": str(cwd), "close_fds": True,
                              "env": {**os.environ, "PYTHONUNBUFFERED": "1", "HF_HUB_DISABLE_TELEMETRY": "1"}}
    if os.name == "nt":
        kwargs["creationflags"] = (getattr(subprocess, "DETACHED_PROCESS", 0x8)
                                   | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
                                   | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    else:
        kwargs["start_new_session"] = True
    stream = log.open("ab")
    kwargs["stdout"] = stream
    kwargs["stderr"] = subprocess.STDOUT
    try:
        return subprocess.Popen(args, **kwargs).pid
    finally:
        stream.close()


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {int(pid)}", "/NH"], capture_output=True,
                                 text=True, timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            return str(int(pid)) in out.stdout
        except Exception:
            return False
    try:
        # Reap our own finished child first; an unreaped zombie still "exists".
        if os.waitpid(int(pid), os.WNOHANG)[0] == int(pid):
            return False
    except ChildProcessError:
        pass  # not our child (e.g. started before an app restart)
    except OSError:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _runs(data_dir: Path) -> list[Path]:
    base = root(data_dir) / "runs"
    if not base.is_dir():
        return []
    found = [p for p in base.iterdir() if p.is_dir() and _RUN_NAME.fullmatch(p.name)]
    return sorted(found, key=lambda p: int(p.name[1:]))


def busy(data_dir: Path) -> str:
    """Non-empty while setup or training is using this machine's GPU/CPU."""
    setup = _read(root(data_dir) / "setup_status.json")
    if setup.get("stage") == "installing" and _pid_alive(int(setup.get("pid") or 0)):
        return "setup"
    for run in _runs(data_dir)[-1:]:
        status = _read(run / "status.json") or _read(run / "launch.json")
        if status.get("stage") not in {"ready", "failed"} and _pid_alive(int(_read(run / "launch.json").get("pid") or 0)):
            return "training"
    return ""


def local_status(data_dir: Path) -> dict:
    setup = _read(root(data_dir) / "setup_status.json")
    runs = []
    for run in _runs(data_dir)[-5:]:
        status, report = _read(run / "status.json"), _read(run / "report.json")
        stage = status.get("stage") or "starting"
        if stage not in {"ready", "failed"} and not _pid_alive(int(_read(run / "launch.json").get("pid") or 0)):
            stage, status["message"] = "failed", status.get("message") or "Training stopped unexpectedly (see log)."
        runs.append({"run": run.name, "stage": stage, "message": status.get("message", ""),
                     "passed": bool(report.get("passed")), "model": report.get("model"),
                     "evaluation": report.get("evaluation") or {}, "examples": report.get("examples")})
    ready_env = venv_python(data_dir).is_file() and setup.get("stage") == "ready"
    return {"ok": True, "setup": "ready" if ready_env else (setup.get("stage") or "not_installed"),
            "setup_message": setup.get("message", ""), "busy": busy(data_dir), "runs": runs,
            "active": active_tuned_model(data_dir)}


def local_setup(data_dir: Path) -> dict:
    with _LOCK:
        if busy(data_dir):
            return {"ok": False, "error": "Setup or training is already running."}
        status_path = root(data_dir) / "setup_status.json"
        script = _repo_root() / "training" / "setup_env.py"
        pid = _spawn([_console_python(), str(script), "--data-dir", str(Path(data_dir).resolve())],
                     root(data_dir) / "setup.log", _repo_root())
        _write_json(status_path, {"stage": "installing", "pid": pid, "message": "Installing the training tools (one-time, several GB)."})
        return {"ok": True, "message": "Installing training tools on the PC. This is one-time and can take 10-20 minutes."}


def local_train(data_dir: Path, examples: list[dict], ollama_base: str, ollama_url: str) -> dict:
    with _LOCK:
        if busy(data_dir):
            return {"ok": False, "error": "Setup or training is already running."}
        if local_status(data_dir)["setup"] != "ready":
            return {"ok": False, "error": "The training tools aren't installed yet. Type 'weights setup' first."}
        clean = [e for e in examples if isinstance(e, dict) and isinstance(e.get("messages"), list)][:MAX_EXAMPLES]
        if len(clean) < MIN_EXAMPLES:
            return {"ok": False, "error": f"Need at least {MIN_EXAMPLES} examples; have {len(clean)}."}
        if not re.fullmatch(r"[A-Za-z0-9._:-]{2,80}", ollama_base or "") or is_tuned_model(ollama_base):
            return {"ok": False, "error": "Unknown base model to tune."}
        existing = _runs(data_dir)
        run = f"r{int(existing[-1].name[1:]) + 1 if existing else 1}"
        run_dir = root(data_dir) / "runs" / run
        run_dir.mkdir(parents=True)
        dataset = run_dir / "dataset.jsonl"
        dataset.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in clean), encoding="utf-8")
        _unload_ollama(ollama_url)
        pid = _spawn([str(venv_python(data_dir)), "-m", "training.xemai_tune", "run",
                      "--dataset", str(dataset), "--run-dir", str(run_dir), "--ollama-base", ollama_base,
                      "--ollama-url", ollama_url, "--name", f"{TUNED_PREFIX}:{run}"],
                     run_dir / "train.log", _repo_root())
        _write_json(run_dir / "launch.json", {"pid": pid, "started": time.time(), "base": ollama_base,
                                              "examples": len(clean)})
        return {"ok": True, "run": run, "examples": len(clean)}


def _unload_ollama(url: str) -> None:
    """Free GPU memory held by Ollama before training (it reloads on the next chat)."""
    import urllib.request

    try:
        with urllib.request.urlopen(url.rstrip("/") + "/api/ps", timeout=5) as response:
            running = json.loads(response.read().decode() or "{}").get("models", [])
        for item in running:
            body = json.dumps({"model": item.get("name") or item.get("model"), "keep_alive": 0}).encode()
            urllib.request.urlopen(urllib.request.Request(url.rstrip("/") + "/api/generate", data=body,
                                                          headers={"Content-Type": "application/json"}), timeout=30).read()
    except Exception:
        pass


# ----------------------------------------------------------------- chat command

def _format_status(status: dict, examples: int) -> str:
    lines = [f"Weight training: {examples} example(s) collected ({MIN_EXAMPLES} needed to train)."]
    setup = status.get("setup")
    lines.append("Training tools: " + ("installed" if setup == "ready" else
                 "installing…" if setup == "installing" else
                 f"failed — {status.get('setup_message')}" if setup == "failed" else
                 "not installed (type 'weights setup')"))
    active = status.get("active")
    lines.append(f"Active model: {active} (tuned)" if active else "Active model: original base model")
    for run in status.get("runs") or []:
        ev = run.get("evaluation") or {}
        detail = (f" — held-out loss {ev.get('holdout_nll_base')} → {ev.get('holdout_nll_tuned')},"
                  f" general drift {ev.get('anchor_drift')}" if ev else "")
        lines.append(f"• {run['run']}: {run['stage']}{detail}. {run.get('message', '')}".rstrip())
    return "\n".join(lines)


def command(data_dir: Path, db, chat_id: int, text: str, *, executor, ollama_base: str) -> str:
    """Handle an exact owner-typed command. `executor` runs setup/train on the GPU machine."""
    match = TEACH.match(text or "")
    if match:
        return record_teach(data_dir, db, chat_id, match.group(1))
    sub = (WEIGHTS.match(text or "").group(1) or "status").lower()
    try:
        if sub == "status":
            return _format_status(executor.status(), len(collect_examples(data_dir, db)))
        if sub == "setup":
            result = executor.setup()
        elif sub == "train":
            examples = collect_examples(data_dir, db)
            if len(examples) < MIN_EXAMPLES:
                return (f"I have {len(examples)} example(s); I need at least {MIN_EXAMPLES} before training. "
                        "Correct a reply with 'teach: <better answer>' or rate great replies 9-10.")
            result = executor.train(examples, ollama_base)
            if result.get("ok"):
                return (f"Training run {result['run']} started on {executor.label} with {result['examples']} examples. "
                        "Chat keeps working on the always-on host meanwhile. Type 'weights' to check progress; "
                        "it will only be offered if it beats the current model on held-out examples.")
        elif sub == "rollback":
            result = executor.use(None)
            if result.get("ok"):
                return "Rolled back: everyday chat is using the original base model again."
        else:
            run = sub.split()[1]
            result = executor.use(run)
            if result.get("ok"):
                return f"Switched to {result['model']}. Type 'weights rollback' any time to go back."
        return result.get("message") or result.get("error") or "Done."
    except WorkerOutdated as exc:
        return str(exc)
    except Exception as exc:  # noqa: BLE001 - surface a short reason, never a traceback
        return f"Weight training is unavailable right now: {str(exc)[:200]}"


class LocalExecutor:
    label = "this computer"

    def __init__(self, data_dir: Path, ollama_url: str):
        self.data_dir, self.ollama_url = Path(data_dir), ollama_url

    def status(self) -> dict:
        return local_status(self.data_dir)

    def setup(self) -> dict:
        return local_setup(self.data_dir)

    def train(self, examples: list[dict], base: str) -> dict:
        return local_train(self.data_dir, examples, base, self.ollama_url)

    def use(self, run: str | None) -> dict:
        return set_active(self.data_dir, run)


class WorkerOutdated(RuntimeError):
    """The paired PC is still running a worker without weight training."""


class WorkerExecutor:
    """Same operations on the paired PC worker over its authenticated link."""

    label = "your PC"

    def __init__(self, worker_client):
        self.client = worker_client

    def _call(self, path: str, payload: dict | None = None, timeout: int = 30) -> dict:
        try:
            return self.client._request(path, payload=payload, timeout=timeout)
        except Exception as exc:
            if "Unknown worker endpoint" not in str(exc):
                raise
            try:
                version = str(self.client.worker_health().get("version") or "an older version")
            except Exception:
                version = "an older version"
            version = f"v{version}" if version[:1].isdigit() else version
            raise WorkerOutdated(
                f"Your PC's XemAi worker is still running {version}, which doesn't have weight training yet. "
                "From v0.9.62 the PC worker restarts itself after every update. This one time, restart the PC "
                "(or sign out and back in) so it loads the new version, then try again."
            ) from exc

    def status(self) -> dict:
        return self._call("/api/weights/status", timeout=15)

    def setup(self) -> dict:
        return self._call("/api/weights/setup", payload={}, timeout=30)

    def train(self, examples: list[dict], base: str) -> dict:
        # Stay under the worker's request limit; drop the lowest-priority (last) examples.
        examples = list(examples)
        while examples and len(json.dumps({"examples": examples}).encode()) > MAX_UPLOAD_BYTES:
            examples = examples[: max(0, len(examples) - max(1, len(examples) // 10))]
        return self._call("/api/weights/train", payload={"examples": examples, "base": base}, timeout=60)

    def use(self, run: str | None) -> dict:
        return self._call("/api/weights/use", payload={"run": run}, timeout=30)
