"""Explicit background conversation tests using the existing configured model.

No model installs, tools, private chat/profile extraction, training, automatic
approvals or uploads. This isolates prompt/approved-lesson effects; it is not
the entire GUI/reviewer pipeline or an automatic intelligence score.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import logging
import os
import random
import re
import secrets
import threading
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .conversation_test_cases import CASES
from .version import VERSION

_LOCK = threading.RLock()
_JOBS: dict[str, dict] = {}
_ACTIVE = {"queued", "running", "stopping"}
_ID = re.compile(r"[0-9a-f]{32}")
_COMMANDS = {
    "conversation test": "auto", "conversation test start": "auto",
    "conversation test laptop": "laptop", "conversation test pc": "pc",
    "conversation test status": "status", "conversation test results": "results",
    "conversation test stop": "stop",
}
_CONDITIONS = ("without_turn_coach", "with_turn_coach", "with_coach_and_approved_lessons", "minimal_control")
_MINIMAL = (
    "You are a helpful, candid assistant. Respond naturally to the latest user "
    "message using the visible conversation. Preserve constraints, do not "
    "invent facts, and ask a focused question only if essential information is missing."
)
_SOURCE_FILES = (
    "app/prompts.py", "app/conversation_skills.py", "app/conversation_learning.py",
    "app/github_bridge_review.py", "app/llm.py", "app/hybrid.py",
    "app/conversation_evaluation.py", "app/conversation_test_cases.py", "app/version.py",
)
_MAX_EXPORT = 3_000_000
_BETWEEN_REQUESTS_SECONDS = 0.25


def _command(text):
    return _COMMANDS.get(" ".join(str(text or "").lower().split()).strip(" .!?"))


def is_command(text):
    return isinstance(text, str) and _command(text) is not None


def _root(data_dir):
    root = Path(data_dir).resolve() / "conversation_tests"
    if root.is_symlink():
        raise ValueError("Conversation test directory cannot be a symlink.")
    return root


def _safe_job_path(data_dir, run_id):
    if not isinstance(run_id, str) or not _ID.fullmatch(run_id):
        raise ValueError("Invalid conversation test identifier.")
    root = _root(data_dir).resolve()
    path = root / ("run_" + run_id)
    if path.is_symlink() or path.resolve().parent != root:
        raise ValueError("Conversation test path is outside its directory.")
    return path


def _read_json(path, limit=16_384):
    if not path.exists():
        raise FileNotFoundError("Conversation test state is unavailable.")
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise ValueError("Conversation test state is unavailable.")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Invalid conversation test state.")
    return value


def _atomic_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


class _Reservation:
    """Native advisory lock held through the run; released if its process exits."""
    def __init__(self, path):
        self.path, self.stream = Path(path), None

    def acquire(self, create=True):
        try:
            if not create and not self.path.exists():
                return True
            if self.path.is_symlink():
                return False
            self.stream = self.path.open("a+b" if create else "r+b")
            if create and self.path.stat().st_size == 0:
                self.stream.write(b"0")
                self.stream.flush()
            self.stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            if self.stream:
                self.stream.close()
                self.stream = None
            return False

    def release(self):
        if self.stream:
            try:
                self.stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.stream.fileno(), fcntl.LOCK_UN)
            finally:
                self.stream.close()
                self.stream = None


def _latest(data_dir):
    root = _root(data_dir)
    if not (root / "latest.json").is_file():
        return None
    pointer = _read_json(root / "latest.json")
    return _read_json(_safe_job_path(data_dir, pointer.get("run_id")) / "state.json")


def is_running(data_dir):
    key = str(Path(data_dir).resolve())
    with _LOCK:
        job = _JOBS.get(key)
        if job and job["meta"]["state"] in _ACTIVE:
            return True
    root = _root(data_dir)
    if not root.exists():
        return False
    lock = _Reservation(root / "active.lock")
    free = lock.acquire(create=False)
    lock.release()
    return not free


def status(data_dir):
    with _LOCK:
        value = _latest(data_dir)
    if value and value.get("state") in _ACTIVE and not is_running(data_dir):
        value = dict(value, state="interrupted")
    return value


def _model_id(value):
    value = str(value or "").strip()
    return value if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,160}", value) else "unknown"


def _same_model(expected, actual):
    return expected != "unknown" and actual != "unknown" and (
        expected.removesuffix(":latest").lower() == actual.removesuffix(":latest").lower()
    )


def _digest(client, expected):
    try:
        for item in client.installed_models():
            if _same_model(expected, _model_id(item.get("name") or item.get("model"))):
                digest = str(item.get("digest") or "")
                if re.fullmatch(r"[a-fA-F0-9]{64}|sha256:[a-fA-F0-9]{64}", digest):
                    return digest
                break
    except Exception:
        pass
    return "unreported"


def _source_hashes():
    root = Path(__file__).resolve().parent.parent
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in _SOURCE_FILES}


def _select_client(config, data_dir, requested_route):
    from .hybrid import build_llm_client
    config = dict(config)
    if requested_route == "laptop":
        config["hybrid_enabled"] = False
    if requested_route == "pc" and not config.get("hybrid_enabled"):
        raise ValueError("Paired PC routing is not enabled.")
    logger = logging.getLogger("xemai_conversation_evaluation_inference")
    logger.handlers[:] = [logging.NullHandler()]
    logger.propagate = False
    model = build_llm_client(config, logger, data_dir)
    if callable(getattr(model, "refresh_route", None)):
        route = model.refresh_route()
        client, compute = model.active_client, str(route.get("compute") or "unknown")
    else:
        if config.get("auto_detect_ollama_model", True):
            model.discover_runtime_model(preferred=str(config.get("model") or ""))
        client, compute = model, "local_host"
    expected = _model_id(client.model)
    if expected == "unknown" or compute not in {"local_host", "remote_worker"}:
        raise ValueError("The selected model route was not identified.")
    if requested_route == "pc" and compute != "remote_worker":
        raise ValueError("The paired PC is unavailable.")
    return client, expected, compute


def _notes(data_dir, question):
    from .conversation_learning import lesson_context
    from .github_bridge_review import recall_context
    return [note for note in (recall_context(data_dir, question), lesson_context(data_dir, question)) if note]


def _messages(system, case, condition, notes):
    from .conversation_skills import guidance_for_turn
    messages = [{"role": "system", "content": _MINIMAL if condition == "minimal_control" else system}]
    if condition == "with_coach_and_approved_lessons":
        messages.extend({"role": "system", "content": note} for note in notes)
    messages.extend(copy.deepcopy(case["history"]))
    messages.append({"role": "user", "content": case["user"]})
    if condition in {"with_turn_coach", "with_coach_and_approved_lessons"}:
        cue = guidance_for_turn(messages)
        if cue:
            messages.append({"role": "system", "content": cue})
    return messages


def _generate(client, messages, expected):
    started = time.monotonic()
    try:
        raw = client.chat_raw(messages)
        if not isinstance(raw, dict) or raw.get("error") or raw.get("done") is False:
            raise ValueError("Incomplete inference result")
        actual = _model_id(raw.get("model"))
        if not _same_model(expected, actual):
            return {"status": "unscorable_model_identity", "answer": "", "actual_model": actual}
        message = raw.get("message")
        if not isinstance(message, dict):
            raise ValueError("Missing assistant message")
        if message.get("tool_calls"):
            return {"status": "unscorable_tool_call", "answer": "", "actual_model": actual}
        answer = message.get("content")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("Missing user-facing answer")
        if len(answer) > 12_000:
            return {"status": "unscorable_oversized_answer", "answer": "", "actual_model": actual}
        return {
            "status": "generated" if _same_model(expected, actual) else "unscorable_model_identity",
            "answer": answer, "actual_model": actual,
            "elapsed_seconds": round(time.monotonic() - started, 3),
        }
    except Exception as error:
        return {"status": "generation_error", "answer": "", "actual_model": "unknown",
                "error_type": type(error).__name__}


def _csv(value):
    value = str(value or "")
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value


def _save_report(path, manifest, rows):
    _atomic_json(path / "results.json", {"manifest": manifest, "results": rows})
    review = [row for row in rows if row["status"] == "generated"]
    random.SystemRandom().shuffle(review)
    columns = [
        "response_id", "case_id", "question", "answer",
        "criterion_1", "criterion_2", "criterion_3",
        "score_1_0_or_1", "score_2_0_or_1", "score_3_0_or_1", "reviewer_notes",
    ]
    with (path / "blind_review.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for row in review:
            writer.writerow({
                "response_id": row["response_id"], "case_id": row["case_id"],
                "question": _csv(row["question"]), "answer": _csv(row["answer"]),
                **{f"criterion_{i+1}": _csv(v) for i, v in enumerate(row["criteria"])},
            })
    _atomic_json(path / "condition_key.json", {
        row["response_id"]: {"condition": row["condition"], "case_id": row["case_id"],
                             "actual_model": row.get("actual_model"), "compute": row["compute"]}
        for row in rows
    })
    (path / "READ_RESULTS.txt").write_text(
        "Grade blind_review.csv before revealing condition_key.json or results.json.\n"
        "Score each criterion 0 or 1; no quality scores are assigned automatically.\n"
        "These are exposed synthetic pilot cases, not concealed held-out evidence.\n"
        "The test uses installed prompts/approved notes, bypassing GUI, tools, retries and reviewers.\n"
        "Compare matched answers on the same model/route/source version; report failures.\n"
        "Skipped lesson rows mean notes were absent or changed, not measured learning.\n"
        "Use new situations and repeated tests after restarting for retention assessment.\n"
        "No weights or owner data were changed; no results were uploaded automatically.\n",
        encoding="utf-8",
    )
    with zipfile.ZipFile(path / "results_for_review.zip", "x", zipfile.ZIP_DEFLATED) as archive:
        for name in ("results.json", "blind_review.csv", "condition_key.json", "READ_RESULTS.txt"):
            archive.write(path / name, arcname=name)


def _update(job, **values):
    with _LOCK:
        job["meta"].update(values)
        _atomic_json(job["path"] / "state.json", job["meta"])
    if job["logger"]:
        job["logger"].info(
            "Conversation test | run_id=%s state=%s rows=%s model=%s compute=%s",
            job["meta"]["run_id"], job["meta"]["state"], job["meta"]["completed_rows"],
            job["meta"].get("model", "unknown"), job["meta"].get("compute", "unknown"),
        )


def result_text(meta):
    state = str(meta.get("state") or "unknown")
    generated, completed, total = (int(meta.get(k) or 0) for k in ("generated_answers", "completed_rows", "total_rows"))
    text = (
        f"Conversation test {state}. Progress: {completed}/{total} comparisons; "
        f"{generated} model answers, {int(meta.get('skipped_rows') or 0)} skipped, "
        f"{int(meta.get('unscorable_rows') or 0)} unscorable. "
    )
    if meta.get("model"):
        route = "PC worker" if meta.get("compute") == "remote_worker" else "local host"
        text += f"Model: {meta['model']} on {route}. "
    if state == "stopping":
        text += "Stopping after the current model request. "
    if state in {"failed", "interrupted"}:
        text += "The run is incomplete; check model availability before starting again. "
    if meta.get("source_changed") or meta.get("model_digest_changed"):
        text += "The app source or model changed during the run; do not attribute differences to learning. "
    if state not in _ACTIVE:
        text += "Answers still need review; this is not proof of learning or weight training."
    if meta.get("export_ready") and _ID.fullmatch(str(meta.get("run_id") or "")):
        text += "\n[[XEMAI_CONVERSATION_RESULTS:" + meta["run_id"] + "]]"
    return text


def _run(job):
    rows, manifest = [], {"training_applied": False, "scored": False, "retained_learning_established": False}
    state, error_type = "completed", None
    before, digest_before, client = None, "unreported", None
    try:
        job["begin"].wait()
        if job["stop"].is_set():
            state = "cancelled"
            return
        before = _source_hashes()
        client, expected, compute = _select_client(job["config"], job["data_dir"], job["route"])
        digest_before = _digest(client, expected)
        _update(job, state="stopping" if job["stop"].is_set() else "running", model=expected, compute=compute)
        from .prompts import build_system_prompt, build_laptop_system_prompt
        user = {"name": "Synthetic Test Owner", "personality_notes": "",
                "communication_preferences": "Be direct, natural, helpful and independent."}
        tool_status = ["This explicit synthetic evaluation has no tools or web access."]
        if compute == "local_host" and job["config"].get("laptop_answer_guidance", True):
            system = build_laptop_system_prompt(user, [], tool_status=tool_status,
                                                assistant_name="XemAi", web_allowed=False)
            prompt_kind = "installed_laptop_prompt"
        else:
            system = build_system_prompt(user, [], tool_status=tool_status, assistant_name="XemAi")
            prompt_kind = "installed_full_prompt"
        seed = secrets.randbits(64)
        rng = random.Random(seed)
        manifest.update(app_version=VERSION, requested_model=expected, compute=compute,
                        prompt_kind=prompt_kind, model_digest_before=digest_before,
                        order_seed=seed, source_hashes_before=before)
        for case in CASES:
            if job["stop"].is_set():
                state = "cancelled"
                break
            notes = _notes(job["data_dir"], case["user"])
            conditions = list(_CONDITIONS)
            rng.shuffle(conditions)
            for condition in conditions:
                if job["stop"].is_set():
                    state = "cancelled"
                    break
                row = {
                    "response_id": uuid.uuid4().hex[:12], "case_id": case["id"],
                    "condition": condition, "skill": case["skill"],
                    "question": case["user"], "history": case["history"], "criteria": case["criteria"],
                    "compute": compute, "lesson_present": bool(notes) if condition == _CONDITIONS[2] else False,
                    "lesson_context_sha256": (
                        hashlib.sha256("\n".join(notes).encode()).hexdigest()
                        if condition == _CONDITIONS[2] and notes else None
                    ),
                }
                if condition == _CONDITIONS[2] and not notes:
                    row.update(status="skipped_no_approved_lessons", answer="", actual_model="unknown")
                elif condition == _CONDITIONS[2] and _notes(job["data_dir"], case["user"]) != notes:
                    row.update(status="skipped_lesson_state_changed", answer="", actual_model="unknown")
                else:
                    row.update(_generate(client, _messages(system, case, condition, notes), expected))
                rows.append(row)
                _update(job, completed_rows=len(rows),
                        generated_answers=sum(r["status"] == "generated" for r in rows),
                        skipped_rows=sum(r["status"].startswith("skipped_") for r in rows),
                        unscorable_rows=sum(r["status"] != "generated" and not r["status"].startswith("skipped_") for r in rows))
                if row["status"] in {"generation_error", "unscorable_model_identity"}:
                    state = "failed"
                    error_type = row.get("error_type") or row["status"]
                    break
                if job["stop"].wait(_BETWEEN_REQUESTS_SECONDS):
                    state = "cancelled"
                    break
            if state != "completed":
                break
    except Exception as error:
        state, error_type = "failed", type(error).__name__
    finally:
        try:
            after = _source_hashes() if before is not None else None
            digest_after = _digest(client, manifest.get("requested_model", "unknown")) if client else "unreported"
            source_changed = before is not None and before != after
            digest_changed = digest_before != "unreported" and digest_after != "unreported" and digest_before != digest_after
            manifest.update(
                created_at_utc=datetime.now(timezone.utc).isoformat(), state=state, error_type=error_type,
                source_hashes_after=after, source_changed_during_run=source_changed,
                model_digest_after=digest_after, model_digest_changed_during_run=digest_changed,
                sampling="Existing selected client's model defaults; no harness overrides.",
                limitation="Prompt/approved-lesson pilot; full GUI/tools/retries/reviewers bypassed.",
            )
            _save_report(job["path"], manifest, rows)
            _update(job, state=state, error_type=error_type, export_ready=True,
                    source_changed=source_changed, model_digest_changed=digest_changed)
        except Exception as error:
            _update(job, state="failed", error_type=type(error).__name__, export_ready=False)
        finally:
            try:
                if job["on_complete"]:
                    job["on_complete"](result_text(dict(job["meta"])))
            except Exception:
                if job["logger"]:
                    job["logger"].warning("Conversation test completion notification failed")
            finally:
                with _LOCK:
                    key = str(job["data_dir"].resolve())
                    if _JOBS.get(key) is job:
                        _JOBS.pop(key)
                    job["reservation"].release()


def _notify_chat(data_dir, chat_id, logger):
    def notify(text):
        from .database import Database
        path = Path(data_dir) / "personal_ai.db"
        if not path.is_file():
            return
        database = Database(path)
        try:
            if database.get_chat(chat_id) is not None:
                database.add_assistant_message(chat_id, text, compute_source="application")
        finally:
            database.close()
    return notify


def begin(data_dir, chat_id=None):
    """Release a deferred test only after its start message has been saved."""
    with _LOCK:
        job = _JOBS.get(str(Path(data_dir).resolve()))
        if job and (chat_id is None or job["chat_id"] == chat_id):
            job["begin"].set()


def command(data_dir, text, config, *, chat_id=None, logger=None, defer=False):
    action = _command(text)
    if action is None:
        return None
    try:
        key = str(Path(data_dir).resolve())
        if action in {"status", "results"}:
            meta = status(data_dir)
            return result_text(meta) if meta else "No conversation test has run. Type 'conversation test' to start one."
        if action == "stop":
            with _LOCK:
                job = _JOBS.get(key)
                if not job or job["meta"]["state"] not in _ACTIVE:
                    return ("This test is running in another XemAi process; stop it there."
                            if is_running(data_dir) else "No conversation test is running.")
                job["stop"].set()
                job["begin"].set()
                _update(job, state="stopping")
            return "Conversation test is stopping after the current model request."
        with _LOCK:
            if is_running(data_dir):
                return "A conversation test is already running. Type 'conversation test status' or 'conversation test stop'."
            root = _root(data_dir)
            root.mkdir(parents=True, exist_ok=True)
            reservation = _Reservation(root / "active.lock")
            if not reservation.acquire():
                return "A conversation test is already running in another XemAi process."
            run_id = uuid.uuid4().hex
            path = _safe_job_path(data_dir, run_id)
            try:
                path.mkdir(exist_ok=False)
                meta = {
                    "run_id": run_id, "state": "queued", "app_version": VERSION,
                    "total_rows": len(CASES) * len(_CONDITIONS), "completed_rows": 0,
                    "generated_answers": 0, "skipped_rows": 0, "unscorable_rows": 0, "export_ready": False,
                    "training_applied": False,
                }
                job = {
                    "meta": meta, "path": path, "data_dir": Path(data_dir), "config": dict(config),
                    "route": action, "stop": threading.Event(), "reservation": reservation,
                    "begin": threading.Event(),
                    "logger": logger, "on_complete": _notify_chat(data_dir, chat_id, logger) if chat_id is not None else None,
                    "chat_id": chat_id,
                }
                _atomic_json(path / "state.json", meta)
                _atomic_json(root / "latest.json", {"run_id": run_id})
                _JOBS[key] = job
                thread = threading.Thread(target=_run, args=(job,), daemon=True)
                job["thread"] = thread
                if not defer:
                    job["begin"].set()
                thread.start()
            except Exception:
                _JOBS.pop(key, None)
                reservation.release()
                raise
        return (
            "Conversation test started in the background using six fictional conversations. "
            "It compares prompts, conversation guidance and approved lessons; it does not train weights. "
            "Type 'conversation test status' for progress or 'conversation test stop' to stop after the current request."
        )
    except (OSError, ValueError, TypeError):
        return "Conversation test could not start or read its state safely. No model or configuration was changed."


def export_results(data_dir, run_id=None):
    if run_id is None:
        meta = status(data_dir)
        if not meta:
            raise FileNotFoundError("No conversation test results are available.")
        run_id = meta.get("run_id")
    path = _safe_job_path(data_dir, run_id)
    meta = _read_json(path / "state.json")
    if meta.get("state") in _ACTIVE or meta.get("export_ready") is not True:
        raise FileNotFoundError("Conversation test results are not ready.")
    archive = path / "results_for_review.zip"
    if archive.is_symlink() or archive.resolve().parent != path.resolve():
        raise ValueError("Conversation test export is outside its directory.")
    if not archive.is_file() or archive.stat().st_size > _MAX_EXPORT:
        raise FileNotFoundError("Conversation test export is unavailable.")
    return archive.read_bytes(), "XemAi_conversation_test_" + run_id + ".zip"
