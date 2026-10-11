"""Opt-in official-source AI technology watch; research, never self-modification.

This is a deterministic read-only feed watcher. It records vendor claims as
leads to benchmark, not as proven improvements. It neither downloads models
nor grants agent/tool permissions, and performs no network calls unless
explicitly enabled or a user manually requests a scan.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import tempfile
import threading
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


SOURCES = (
    ("OpenAI", "https://openai.com/news/rss.xml", ("openai.com", "www.openai.com")),
    ("Google DeepMind", "https://deepmind.google/blog/rss.xml", ("deepmind.google",)),
    ("Hugging Face", "https://huggingface.co/blog/feed.xml", ("huggingface.co",)),
    ("Ollama", "https://github.com/ollama/ollama/releases.atom", ("github.com",)),
    ("llama.cpp", "https://github.com/ggml-org/llama.cpp/releases.atom", ("github.com",)),
)
MAX_FEED_BYTES = 400_000
MAX_EVENTS = 60
MAX_SEEN = 140
_WATCH_LOCK = threading.Lock()
_AREAS = (
    ("screenshots and vision", re.compile(r"\b(?:vision|multimodal|visual|image|images|ocr|screenshot)\b", re.I),
     "Compare screenshot-identification accuracy on fixed XemTV screenshots, then check local model support."),
    ("software engineering", re.compile(r"\b(?:coding|code|programming|software.engineering|bug.fix|developer|agentic)\b", re.I),
     "Benchmark real Kotlin multi-file investigations and correction rate against the current worker."),
    ("tool reliability", re.compile(r"\b(?:tool|function.call|agent|orchestrat|mcp|api|computer.use)\b", re.I),
     "Test multi-step tool completion, evidence citation and permission compliance in a read-only sandbox."),
    ("local inference", re.compile(r"\b(?:inference|quantiz|gpu|context.window|memory.use|gguf|cuda|latency|ollama|performance)\b", re.I),
     "Measure compatibility, VRAM use, response time and accuracy on the RTX 5080 before changing a model."),
    ("reasoning and knowledge", re.compile(r"\b(?:model|reasoning|benchmark|research|llm|language.model|release)\b", re.I),
     "Compare factual accuracy and unsupported claims on identical tasks; vendor results are not independent proof."),
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _state_file(data_dir: Path) -> Path:
    return Path(data_dir) / "ai_technology_watch.json"


def _load(data_dir: Path) -> dict:
    try:
        raw = _state_file(data_dir).read_bytes()
        if len(raw) > 500_000:
            return {}
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def _store(data_dir: Path, state: dict) -> None:
    target = _state_file(data_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp_name = ""
    try:
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=target.parent,
            prefix=".ai-watch-", suffix=".tmp", delete=False,
        ) as output:
            temp_name = output.name
            json.dump(state, output, indent=2, ensure_ascii=False)
            output.write("\n")
        os.replace(temp_name, target)
    finally:
        if temp_name:
            try:
                Path(temp_name).unlink(missing_ok=True)
            except OSError:
                pass


def _allowed_https(url: str, hosts: tuple[str, ...]) -> bool:
    try:
        parsed = urllib.parse.urlsplit(url)
    except ValueError:
        return False
    return (
        parsed.scheme == "https" and parsed.hostname in hosts
        and parsed.username is None and parsed.password is None
        and parsed.port in (None, 443)
    )


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts):
        super().__init__()
        self.hosts = hosts

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        if not _allowed_https(newurl, self.hosts):
            raise ValueError("Unapproved feed redirect.")
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def fetch_feed(source_url: str, hosts: tuple[str, ...]) -> bytes:
    if not _allowed_https(source_url, hosts):
        raise ValueError("Feed URL is not on the approved HTTPS host.")
    opener = urllib.request.build_opener(_SafeRedirect(hosts))
    request = urllib.request.Request(
        source_url, headers={
            "User-Agent": "XemAiTechnologyWatch/1.0",
            "Accept": "application/atom+xml, application/rss+xml, text/xml",
        },
    )
    with opener.open(request, timeout=9) as response:
        if not _allowed_https(response.geturl(), hosts):
            raise ValueError("Feed was served from an unapproved host.")
        raw = response.read(MAX_FEED_BYTES + 1)
    if len(raw) > MAX_FEED_BYTES:
        raise ValueError("Feed exceeds the read limit.")
    return raw


def _clean(value: str, limit: int) -> str:
    # Treat all third-party feed fields as text, not instructions.
    value = html.unescape(re.sub(r"<[^>]*>", " ", value or ""))
    return " ".join(value.split())[:limit]


def _child_text(item: ET.Element, tag: str) -> str:
    for child in item:
        if child.tag.rsplit("}", 1)[-1] == tag:
            return child.text or ""
    return ""


def parse_feed(raw: bytes, label: str, hosts: tuple[str, ...]) -> list[dict]:
    if len(raw) > MAX_FEED_BYTES or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ValueError("Unsupported or unsafe feed.")
    root = ET.fromstring(raw)
    entries = [
        node for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] in {"item", "entry"}
    ][:14]
    found = []
    for item in entries:
        title = _clean(_child_text(item, "title"), 180)
        link = _child_text(item, "link").strip()
        if not link:
            for child in item:
                if child.tag.rsplit("}", 1)[-1] == "link":
                    link = (child.attrib.get("href") or "").strip()
                    if link and child.attrib.get("rel", "alternate") == "alternate":
                        break
        if not link:
            link = _child_text(item, "guid").strip()
        if not _allowed_https(link, hosts) or not title:
            continue
        summary = _clean(
            _child_text(item, "summary") or _child_text(item, "description")
            or _child_text(item, "content"), 700,
        )
        area = next(
            (area for area, expression, _ in _AREAS if expression.search(title+" "+summary)),
            "",
        )
        if not area:
            continue
        advice = next(advice for name, _, advice in _AREAS if name == area)
        found.append({
            "id": link, "source": label, "title": title, "url": link,
            "published": _clean(_child_text(item, "published") or _child_text(item, "updated")
                or _child_text(item, "pubDate"), 80),
            "summary": summary,
            "area": area,
            "proposal": advice,
            "assessment": "Vendor announcement; an untested lead, not a verified improvement.",
        })
    return found[:8]


def interval_hours(config: dict) -> int:
    try:
        value = config.get("ai_watch_interval_hours", 168)
        if isinstance(value, bool):
            return 168
        hours = int(value)
    except (ValueError, TypeError, OverflowError):
        return 168
    return hours if 24 <= hours <= 720 else 168


def scan_due(data_dir: Path, config: dict, *, now: datetime | None = None) -> bool:
    if config.get("ai_watch_enabled") is not True:
        return False
    state = _load(data_dir)
    stamp = state.get("last_attempt")
    if not isinstance(stamp, str):
        return True
    try:
        then = datetime.fromisoformat(stamp)
        if then.tzinfo is None:
            return True
        elapsed = ((now or _now()) - then).total_seconds()
        return elapsed >= interval_hours(config) * 3600 or elapsed < -600
    except ValueError:
        return True


def _message(events: list[dict], first: bool) -> str:
    head = (
        "AI Technology Watch — initial baseline\n"
        if first else "AI Technology Watch — newly detected updates\n"
    )
    text = [head, (
        "These are announcements from official sources, not independently "
        "verified improvements or installed changes. Suggested experiments "
        "require your approval; XemAi has modified nothing."
    )]
    for row in events[:6]:
        text.append(
            f"\n**{row['source']}: {row['title']}**\n"
            f"{row['url']}\n"
            f"Potential relevance: {row['area']}.\n"
            f"Possible next test: {row['proposal']}"
        )
    if len(events) > 6:
        text.append(f"\n{len(events)-6} additional candidates are saved in the watch report.")
    return "\n".join(text)


def scan_once(
    data_dir: Path, config: dict, *, fetch: Callable = fetch_feed,
    now: datetime | None = None, logger=None,
) -> dict:
    """One bounded, user-authorised polling iteration; stores leads for review."""
    if config.get("ai_watch_enabled") is not True:
        return {"ok": False, "status": "disabled", "new": 0}
    if not _WATCH_LOCK.acquire(blocking=False):
        return {"ok": False, "status": "already_running", "new": 0}
    try:
        instant = (now or _now()).isoformat()
        state = _load(data_dir)
        baseline = not isinstance(state.get("last_attempt"), str)
        seen = state.get("seen", {})
        if not isinstance(seen, dict):
            seen = {}
        errors = []
        fresh = []
        good = 0
        for label, url, hosts in SOURCES:
            try:
                rows = parse_feed(fetch(url, hosts), label, hosts)
                good += 1
                earlier = set(x for x in seen.get(label, []) if isinstance(x, str))
                new = [row for row in rows if row["id"] not in earlier]
                # Initial setup samples at most one candidate per official
                # source, avoiding a flood of historic release notes.
                if baseline:
                    new = new[:1]
                else:
                    new = new[:3]
                fresh.extend(new)
                ids = [r["id"] for r in rows]
                seen[label] = list(dict.fromkeys(ids + list(earlier)))[:MAX_SEEN]
            except (OSError, ValueError, ET.ParseError, urllib.error.URLError) as error:
                errors.append(label)
                if logger:
                    logger.warning("AI Technology Watch feed failed | source=%s type=%s",
                                   label, type(error).__name__)
        history = state.get("reports", [])
        if not isinstance(history, list):
            history = []
        for item in fresh:
            history.insert(0, {**item, "detected_at": instant, "baseline": baseline,
                               "delivered": False})
        state = {
            "last_attempt": instant,
            "last_success": instant if good else state.get("last_success"),
            "seen": seen,
            "reports": history[:MAX_EVENTS],
            "source_failures": errors,
            "source_successes": good,
        }
        _store(data_dir, state)
        return {
            "ok": good > 0, "status": "baseline" if baseline else "checked",
            "new": len(fresh), "failed_sources": errors,
            "source_successes": good,
        }
    finally:
        _WATCH_LOCK.release()


def deliver_reports(data_dir: Path, logger=None) -> int:
    """Append a public-source report to a dedicated XemAi chat, without inference."""
    from .database import Database

    if not _WATCH_LOCK.acquire(blocking=False):
        return 0
    try:
        state = _load(data_dir)
        reports = state.get("reports", [])
        if not isinstance(reports, list):
            return 0
        pending = [item for item in reports if isinstance(item, dict) and not item.get("delivered")]
        if not pending:
            return 0
        db = Database(Path(data_dir) / "personal_ai.db")
        try:
            user = db.get_user()
            if user is None:
                return 0
            chats = db.list_chats(user["id"])
            existing = next(
                (chat for chat in chats if chat["title"] == "AI Technology Watch"),
                None,
            )
            chat = existing or db.create_chat(user["id"], "AI Technology Watch")
            db.add_assistant_message(
                chat["id"], _message(pending, bool(pending[0].get("baseline"))),
                compute_source="application",
            )
        finally:
            db.close()
        for item in pending:
            item["delivered"] = True
        _store(data_dir, state)
        if logger:
            logger.info("AI Technology Watch report delivered | candidates=%d", len(pending))
        return len(pending)
    finally:
        _WATCH_LOCK.release()


def current_report(data_dir: Path, config: dict) -> dict:
    state = _load(data_dir)
    recent = state.get("reports", [])
    return {
        "enabled": config.get("ai_watch_enabled") is True,
        "interval_hours": interval_hours(config),
        "last_checked": state.get("last_attempt"),
        "last_success": state.get("last_success"),
        "source_failures": state.get("source_failures", []),
        "reports": recent[:12] if isinstance(recent, list) else [],
        "source_count": len(SOURCES),
        "note": "Feed claims are leads to benchmark, never automatic model learning or applied updates.",
    }


def chat_command(question: str, data_dir: Path, logger=None) -> str | None:
    """Allow explicit user commands; no LLM can invoke them as a tool."""
    q = " ".join(str(question or "").lower().split()).strip(" .!?")
    if q not in {
        "enable ai technology watch",
        "disable ai technology watch",
        "check ai technology watch now",
        "show ai technology watch report",
    }:
        return None
    from .config import load_config, save_config

    config = load_config()
    if q == "enable ai technology watch":
        config["ai_watch_enabled"] = True
        config.setdefault("ai_watch_interval_hours", 168)
        save_config(config)
        return (
            "AI Technology Watch is enabled. XemAi will check five official "
            "AI news and release feeds about once every seven days while the "
            "laptop server is running. It will create an 'AI Technology Watch' "
            "conversation when there are relevant findings. "
            "These are suggestions, not automatically applied updates. "
            "Say 'disable AI technology watch' to stop future polling."
        )
    if q == "disable ai technology watch":
        config["ai_watch_enabled"] = False
        save_config(config)
        return (
            "AI Technology Watch is disabled. No new scheduled feed checks "
            "will be started; a check already in progress may finish. "
            "Existing reports are preserved."
        )
    if q == "check ai technology watch now":
        if config.get("ai_watch_enabled") is not True:
            return "AI Technology Watch is disabled. Say 'enable AI technology watch' first."
        result = scan_once(data_dir, config, logger=logger)
        delivered = deliver_reports(data_dir, logger=logger)
        return (
            f"Technology Watch: {result.get('status')}. "
            f"Feeds checked successfully: {result.get('source_successes', 0)}"
            f"/{len(SOURCES)}. New candidate findings: {result.get('new', 0)}. "
            f"Delivered to the AI Technology Watch chat: {delivered}. "
            "No changes have been made to XemAi's models or code."
        )
    report = current_report(data_dir, config)
    items = report["reports"][:5]
    if not items:
        return (
            "AI Technology Watch has no saved findings yet. "
            "Enable it and say 'check AI technology watch now' to establish "
            "an initial baseline."
        )
    return _message(items, bool(items[0].get("baseline")))
