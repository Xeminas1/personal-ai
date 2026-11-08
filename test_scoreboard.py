"""Scoreboard: graders are correct, the sandbox refuses unsafe code, runs work end to end."""
from __future__ import annotations

import json
import logging
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from app import scoreboard
from app.scoreboard_tasks import CATEGORIES, all_tasks, rule_score

REFERENCE = {
    "code-duration": '''
import re
def parse_duration(text):
    m = re.fullmatch(r"(?:(\\d+)h)?(?:(\\d+)m)?(?:(\\d+)s)?", text or "")
    if not text or not m:
        raise ValueError(text)
    h, mi, s = (int(g or 0) for g in m.groups())
    return h * 3600 + mi * 60 + s
''',
    "code-intervals": '''
def merge_intervals(intervals):
    out = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out
''',
    "code-roman": '''
def roman_to_int(s):
    v = {"I":1,"V":5,"X":10,"L":50,"C":100,"D":500,"M":1000}
    total = 0
    for i, ch in enumerate(s):
        if i + 1 < len(s) and v[ch] < v[s[i+1]]:
            total -= v[ch]
        else:
            total += v[ch]
    return total
''',
    "code-topwords": '''
import re
from collections import Counter
def top_k_words(text, k):
    c = Counter(re.findall(r"[a-z]+", text.lower()))
    return [w for w, _ in sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]
''',
    "code-brackets": '''
def brackets_balanced(s):
    pairs = {")": "(", "]": "[", "}": "{"}
    stack = []
    for ch in s:
        if ch in "([{":
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                return False
    return not stack
''',
    "code-rle": '''
from itertools import groupby
def rle(s):
    return "".join(f"{len(list(g))}{k}" for k, g in groupby(s))
''',
    "code-lru": '''
from collections import OrderedDict
class LRUCache:
    def __init__(self, capacity):
        self.cap, self.d = capacity, OrderedDict()
    def get(self, key):
        if key not in self.d:
            return -1
        self.d.move_to_end(key)
        return self.d[key]
    def put(self, key, value):
        self.d[key] = value
        self.d.move_to_end(key)
        while len(self.d) > self.cap:
            self.d.popitem(last=False)
''',
    "code-flatten": '''
def flatten(items):
    out = []
    for x in items:
        if isinstance(x, (list, tuple)):
            out.extend(flatten(x))
        else:
            out.append(x)
    return out
''',
    "code-weekday": '''
from datetime import date, timedelta
def next_weekday(date_str, weekday):
    names = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
    d = date.fromisoformat(date_str)
    target = names.index(weekday.lower())
    step = (target - d.weekday()) % 7 or 7
    return (d + timedelta(days=step)).isoformat()
''',
    "code-spiral": '''
def spiral(matrix):
    out, m = [], [list(r) for r in matrix]
    while m:
        out += m.pop(0)
        m = [list(r) for r in zip(*m)][::-1]
    return out
''',
    "code-bugfix": '''
def average_positive(nums):
    pos = [n for n in nums if n > 0]
    return sum(pos) / len(pos) if pos else 0.0
''',
    "code-anagrams": '''
def group_anagrams(words):
    groups = {}
    for w in words:
        groups.setdefault("".join(sorted(w)), []).append(w)
    return sorted((sorted(g) for g in groups.values()), key=lambda g: g[0])
''',
}

GOOD = {
    "conv-reference": "The ZenBook 14 is light with a good screen, great for programming.",
    "conv-correction": "1. Mushroom risotto\n2. Chickpea curry\n3. Halloumi traybake",
    "conv-distractor": "How about Smokey, Pebble or Ash?",
    "conv-yes": "25°C is 77°F.",
    "conv-topic-switch": "There are 16 tablespoons in a US cup.",
    "conv-name": "Your name is Sam.",
    "conv-disagree": "No, that's a myth: it isn't visible from the Moon.",
    "conv-cheaper": "The cheaper option was renting a van for £80.",
    "fact-canberra": "Canberra.", "fact-bones": "206.", "fact-gold": "Au.", "fact-austen": "Jane Austen.",
    "fact-km": "1,000 metres.", "honest-einstein": "He didn't; it was for the photoelectric effect.",
    "honest-euro": "The UK never adopted the euro.", "honest-prime-one": "No, 1 is not prime.",
    "honest-fake-book": "I'm not aware of a novel by that title; it may not exist.",
    "honest-future": "I can't predict exact future market values.",
    "inst-bullets": "- Better heart health\n- Improved mood\n- Stronger bones",
    "inst-short": "Earth's rocky, cratered natural satellite.",
    "inst-json": '{"city": "Paris", "country": "France"}',
    "inst-yesno": "Yes", "inst-lowercase": "the rain tapped softly on the window.", "inst-oneword": "hat",
    "math-pens": "7 × 1.20 = 8.40", "math-train": "It arrives at 17:20.", "math-percent": "40.8",
    "math-eggs": "36 - 7 = 29", "math-perimeter": "2 × (8 + 5) = 26", "logic-shortest": "Ann is the shortest.",
}

BAD = {
    "conv-reference": "The Aspire 5 is a budget option.",
    "conv-correction": "1. Chicken curry\n2. Veg soup\n3. Pasta",
    "conv-distractor": "For the birthday invitation for six guests, pick the other venue.",
    "conv-yes": "Okay!", "conv-topic-switch": "In Skyrim there are 16 tablespoons.", "conv-name": "I don't know.",
    "conv-disagree": "Yes, you can see it easily.", "conv-cheaper": "The cheaper one was £250.",
    "fact-canberra": "Sydney.", "fact-bones": "212.", "fact-gold": "AU or Ag.", "fact-austen": "Charlotte Brontë.",
    "fact-km": "100 metres.", "honest-einstein": "Because relativity changed physics.",
    "honest-euro": "In 2002.", "honest-prime-one": "Yes, 1 is prime.",
    "honest-fake-book": "It follows lantern keepers guarding a valley.", "honest-future": "It will close at 8,412.",
    "inst-bullets": "Here are three:\n- Health\n- Mood\n- Bones", "inst-short": "The Moon " * 20,
    "inst-json": "City: Paris, Country: France", "inst-yesno": "Yes, it is the largest.",
    "inst-lowercase": "The rain fell.", "inst-oneword": "Hat and bat.",
    "math-pens": "About 9.", "math-train": "17:10", "math-percent": "41", "math-eggs": "30",
    "math-perimeter": "40", "logic-shortest": "Tom is the shortest.",
}


class TaskSuiteTests(unittest.TestCase):
    def test_suite_shape(self):
        tasks = all_tasks()
        self.assertEqual({t["category"] for t in tasks}, set(CATEGORIES))
        self.assertEqual(len({t["id"] for t in tasks}), len(tasks))
        self.assertGreaterEqual(len(tasks), 40)

    def test_every_coding_task_passes_reference_and_fails_wrong_answer(self):
        for task in (t for t in all_tasks() if t["category"] == "coding"):
            code = REFERENCE[task["id"]]
            reply = f"Here you go:\n```python\n{code}\n```"
            result = scoreboard.grade(task, reply)
            self.assertEqual(result["score"], 1.0, (task["id"], result))
            name = scoreboard.target_name(task)
            wrong = f"```python\nclass {name}:\n    pass\n```" if "class" in task["prompt"][:30] \
                else f"```python\ndef {name}(*a, **k):\n    return None\n```"
            self.assertLess(scoreboard.grade(task, wrong)["score"], 0.5, task["id"])

    def test_every_rule_task_accepts_good_and_rejects_bad(self):
        for task in (t for t in all_tasks() if t["category"] != "coding"):
            self.assertEqual(rule_score(task, GOOD[task["id"]]), 1.0, ("good", task["id"]))
            self.assertEqual(rule_score(task, BAD[task["id"]]), 0.0, ("bad", task["id"]))


class SandboxTests(unittest.TestCase):
    def test_unsafe_code_is_refused_before_running(self):
        for code in ["import os\nos.remove('x')", "import subprocess", "from pathlib import Path",
                     "open('x', 'w').write('y')", "eval('1+1')", "().__class__.__bases__[0].__subclasses__()",
                     "__import__('os')", "getattr(object, 'x')"]:
            self.assertTrue(scoreboard.unsafe_reason(code), code)
            self.assertEqual(scoreboard.run_code(code, ["assert True"])["score"], 0.0)
        self.assertEqual(scoreboard.unsafe_reason("import math\nfrom collections import Counter\n"), "")

    def test_infinite_loop_times_out(self):
        result = scoreboard.run_code("def f():\n    while True:\n        pass\nf()", ["assert True"], timeout=2)
        self.assertEqual((result["score"], result["detail"]), (0.0, "timed out"))

    def test_partial_credit_and_crash_reporting(self):
        result = scoreboard.run_code("def f(x):\n    return x if x < 2 else 0", ["assert f(1) == 1", "assert f(5) == 5"])
        self.assertEqual(result["score"], 0.5)
        self.assertIn("ZeroDivisionError", scoreboard.run_code("1/0", ["assert True"])["detail"])

    def test_code_extraction_prefers_block_with_target(self):
        reply = "```python\nprint('demo')\n```\nFinal:\n```python\ndef rle(s):\n    return s\n```"
        self.assertIn("def rle", scoreboard.extract_code(reply, "rle"))
        self.assertEqual(scoreboard.extract_code("def rle(s): return s", "rle"), "def rle(s): return s")


class FakeOllama:
    """Answers every task correctly for 'smart', wrongly for 'dumb'; tracks system prompts."""

    def __init__(self):
        self.models = ["smart:1b", "dumb:1b", "nomic-embed-text:latest"]
        self.systems = []
        tasks = {t["id"]: t for t in all_tasks()}
        self.by_prompt = {t["messages"][-1]["content"]: t["id"] for t in tasks.values()}
        test = self

        class Handler(BaseHTTPRequestHandler):
            def _send(self, body):
                raw = json.dumps(body).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                self._send({"models": [{"name": m} for m in test.models]})

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/api/pull":
                    raw = b"".join(json.dumps(e).encode() + b"\n" for e in (
                        {"status": "pulling", "total": 100, "completed": 50}, {"status": "success"}))
                    test.models.append(body["model"])
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                test.systems.append((body["model"], body["messages"][0]["content"]))
                task = test.by_prompt[body["messages"][-1]["content"]]
                if body["model"].startswith("smart"):
                    reply = (f"```python\n{REFERENCE[task]}\n```" if task in REFERENCE else GOOD[task])
                else:
                    reply = BAD.get(task, "```python\ndef nope(): pass\n```")
                self._send({"message": {"content": "<think>hmm</think>" + reply},
                            "eval_count": 100, "eval_duration": 2_000_000_000})

            def log_message(self, *a):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()


class RunTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)
        self.ollama = FakeOllama()
        self.addCleanup(self.ollama.close)

    def wait(self):
        for _ in range(600):
            if not scoreboard.busy(self.data):
                return
            time.sleep(0.05)
        self.fail("job did not finish")

    def test_full_run_scores_models_and_measures_xemai_prompt(self):
        result = scoreboard.start_run(self.data, self.ollama.url, None, everyday="smart:1b")
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["plan"], [("smart:1b", "plain"), ("dumb:1b", "plain"), ("smart:1b", "xemai")])
        self.wait()
        status = scoreboard.status(self.data)
        entries = {(e["model"], e["condition"]): e["summary"] for e in status["latest"]["entries"]}
        self.assertEqual(entries[("smart:1b", "plain")]["overall"], 100.0)
        self.assertEqual(entries[("dumb:1b", "plain")]["overall"], 0.0)
        self.assertEqual(entries[("smart:1b", "plain")]["tokens_per_second"], 50.0)
        self.assertEqual(status["current"]["stage"], "finished")
        # The 'xemai' condition really used XemAi's full system prompt.
        systems = {s for m, s in self.ollama.systems if m == "smart:1b"}
        self.assertTrue(any("XemAi" in s and len(s) > 2000 for s in systems))
        self.assertTrue(any(s.startswith(scoreboard.PLAIN_PROMPT) for s in systems))
        table = scoreboard.format_status(status)
        self.assertIn("| smart:1b | plain | **100.0**", table)
        self.assertIn("50.0 tok/s", table)
        self.assertNotIn("nomic-embed", table)
        saved = json.loads(next((self.data / "scoreboard" / "runs").glob("*.json")).read_text())
        self.assertEqual(len(saved["entries"][0]["rows"]), len(all_tasks()))

    def test_uninstalled_model_is_refused_and_pull_installs_it(self):
        result = scoreboard.start_run(self.data, self.ollama.url, ["gpt-oss:20b"], everyday="smart:1b")
        self.assertIn("Not installed", result["error"])
        self.assertFalse(scoreboard.start_pull(self.data, self.ollama.url, "rm -rf /")["ok"])
        self.assertTrue(scoreboard.start_pull(self.data, self.ollama.url, "gpt-oss:20b")["ok"])
        self.wait()
        self.assertEqual(scoreboard.status(self.data)["current"]["stage"], "pulled")
        self.assertIn("gpt-oss:20b", scoreboard.chat_models(self.ollama.url))

    def test_only_one_job_at_a_time(self):
        self.assertTrue(scoreboard.start_run(self.data, self.ollama.url, ["dumb:1b"], everyday="x")["ok"])
        self.assertFalse(scoreboard.start_pull(self.data, self.ollama.url, "gpt-oss:20b")["ok"])
        self.wait()


class CommandTests(unittest.TestCase):
    def test_commands_route_and_explain(self):
        for text in ["scoreboard", "scoreboard models", "scoreboard run", "scoreboard run a:1, b:2",
                     "scoreboard pull gpt-oss:20b", "Scoreboard"]:
            self.assertTrue(scoreboard.is_command(text), text)
        for text in ["what's the scoreboard for the match", "scoreboards", "show me the scoreboard please"]:
            self.assertFalse(scoreboard.is_command(text), text)

        class Ex:
            ran = None

            def models(self):
                return ["qwen3.5:9b-q8_0"]

            def status(self):
                return {"current": {}, "latest": {}}

            def run(self, models, everyday):
                Ex.ran = (models, everyday)
                return {"ok": True, "message": "Scoreboard started"}

            def pull(self, model):
                return {"ok": True, "message": f"Downloading {model}"}

        self.assertIn("gpt-oss:20b — 14 GB", scoreboard.command("scoreboard models", executor=Ex(), everyday="x"))
        self.assertIn("No scoreboard results", scoreboard.command("scoreboard", executor=Ex(), everyday="x"))
        scoreboard.command("scoreboard run qwen3:8b, gpt-oss:20b", executor=Ex(), everyday="qwen3:8b")
        self.assertEqual(Ex.ran, (["qwen3:8b", "gpt-oss:20b"], "qwen3:8b"))
        self.assertIn("Say which model", scoreboard.command("scoreboard pull", executor=Ex(), everyday="x"))


class WorkerEndpointTests(unittest.TestCase):
    def setUp(self):
        from app import worker_server

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ollama = FakeOllama()
        self.addCleanup(self.ollama.close)
        patcher = patch.object(worker_server, "DATA_DIR", Path(self.tmp.name))
        patcher.start()
        self.addCleanup(patcher.stop)
        from app.llm import OllamaClient

        client = OllamaClient(base_url=self.ollama.url, model="smart:1b", logger=logging.getLogger("t"),
                              provider_name="t")
        self.server = worker_server.XemAiWorkerServer(("127.0.0.1", 0), worker_server.XemAiWorkerHandler)
        self.server.worker_token = "tok"
        self.server.ollama_client = client
        self.server.generation_lock = threading.Lock()
        self.server.xemai_logger = logging.getLogger("w")
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(lambda: (self.server.shutdown(), self.server.server_close()))
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def call(self, path, payload=None, auth=True):
        headers = {"Content-Type": "application/json", **({"Authorization": "Bearer tok"} if auth else {})}
        request = urllib.request.Request(self.base + path, headers=headers, method="GET" if payload is None else "POST",
                                         data=None if payload is None else json.dumps(payload).encode())
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            response = opener.open(request, timeout=10)
        except urllib.error.HTTPError as e:
            response = e
        with response:
            return response.status, json.load(response)

    def test_auth_and_flow(self):
        for path, payload in [("/api/scoreboard/status", None), ("/api/scoreboard/models", None),
                              ("/api/scoreboard/run", {}), ("/api/scoreboard/pull", {"model": "x:1"})]:
            self.assertEqual(self.call(path, payload, auth=False)[0], 401, path)
        self.assertIn("smart:1b", self.call("/api/scoreboard/models")[1]["models"])
        code, body = self.call("/api/scoreboard/run", {"models": ["dumb:1b"]})
        self.assertTrue(body["ok"], body)
        for _ in range(400):
            if self.call("/api/scoreboard/status")[1]["current"].get("stage") == "finished":
                break
            time.sleep(0.05)
        entries = self.call("/api/scoreboard/status")[1]["latest"]["entries"]
        self.assertEqual(entries[0]["model"], "dumb:1b")
        self.assertEqual(self.call("/api/scoreboard/run", {"models": "dumb"})[0], 400)


if __name__ == "__main__":
    unittest.main()
