"""Regression tests for XemAi's opt-in official-source AI technology watcher."""
from __future__ import annotations

import logging
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from app import ai_watch, config, gui_backend
from app.database import Database


def rss_item(path="model-v1", headline="New coding and vision model"):
    return f"""<item><title>{headline}</title>
    <link>https://openai.com/news/{path}</link>
    <guid>https://openai.com/news/{path}</guid>
    <description>A language model adds vision and tool calling.</description>
    <pubDate>Wed, 07 Oct 2026 12:00:00 GMT</pubDate></item>"""


def sample_rss(path="model-v1", title="New coding and vision model"):
    return f"""<?xml version="1.0"?><rss version="2.0"><channel>
    <title>Official news</title>{rss_item(path,title)}</channel></rss>""".encode()


def atom_entry(path="v3", headline="Qwen model inference improvements"):
    return f"""<entry><title>{headline}</title>
    <id>https://github.com/ollama/ollama/releases/tag/{path}</id>
    <link href="https://github.com/ollama/ollama/releases/tag/{path}" />
    <updated>2026-10-10T00:00:00Z</updated>
    <content type="html">Faster local model inference and tool calls.</content></entry>"""


def sample_atom():
    return f"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
    {atom_entry()}</feed>""".encode()


class WatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name) / "data"
        self.data.mkdir()
        self.now = datetime(2026, 10, 11, tzinfo=timezone.utc)
        self.logger = logging.getLogger("ai-watch-tests")

    def test_off_by_default_no_internet(self):
        fetch = lambda *_: self.fail("disabled monitor must not fetch")
        self.assertFalse(ai_watch.scan_due(self.data, {}))
        self.assertEqual(
            ai_watch.scan_once(self.data, {}, fetch=fetch)["status"], "disabled"
        )
        self.assertFalse((self.data / "ai_technology_watch.json").exists())
        self.assertEqual(ai_watch.interval_hours({}), 168)
        self.assertEqual(ai_watch.interval_hours({"ai_watch_interval_hours": 1}), 168)
        self.assertEqual(ai_watch.interval_hours({"ai_watch_interval_hours": True}), 168)
        self.assertEqual(ai_watch.interval_hours({"ai_watch_interval_hours": 24}), 24)

    def test_parse_official_rss_atom_and_reject_malicious_feed(self):
        rs = ai_watch.parse_feed(sample_rss(), "OpenAI", ("openai.com",))
        self.assertEqual(len(rs), 1)
        self.assertEqual(rs[0]["area"], "screenshots and vision")
        self.assertIn("not a verified improvement", rs[0]["assessment"])
        at = ai_watch.parse_feed(sample_atom(), "Ollama", ("github.com",))
        self.assertEqual(len(at), 1)
        self.assertEqual(at[0]["title"], "Qwen model inference improvements")
        evil = sample_rss().replace(
            b"https://openai.com/news/model-v1",
            b"http://127.0.0.1/internal",
        )
        self.assertEqual(ai_watch.parse_feed(evil, "OpenAI", ("openai.com",)), [])
        self.assertFalse(ai_watch._allowed_https("https://github.com.evil.com/x", ("github.com",)))
        self.assertFalse(ai_watch._allowed_https("http://github.com/x", ("github.com",)))
        self.assertFalse(ai_watch._allowed_https("https://example.com/x", ("github.com",)))
        with self.assertRaises(ValueError):
            ai_watch.parse_feed(b'<!DOCTYPE a [<!ENTITY x "evil">]><rss/>',
                                "OpenAI", ("openai.com",))
        with self.assertRaises(ValueError):
            ai_watch.fetch_feed("http://127.0.0.1:1234", ("github.com",))

    def test_baseline_dedupe_relevant_deltas_and_scheduled_delivery(self):
        db = Database(self.data / "personal_ai.db")
        user = db.create_user("Test User")
        db.close()
        config_data = {"ai_watch_enabled": True, "ai_watch_interval_hours": 168}
        def fetch(url, hosts):
            if "openai.com" in url:
                return sample_rss()
            if "ollama/ollama" in url:
                return sample_atom()
            return b"<?xml version='1.0'?><rss><channel></channel></rss>"
        self.assertTrue(ai_watch.scan_due(self.data, config_data, now=self.now))
        initial = ai_watch.scan_once(
            self.data, config_data, now=self.now, fetch=fetch, logger=self.logger,
        )
        self.assertTrue(initial["ok"])
        self.assertEqual(initial["new"], 2)
        self.assertEqual(initial["source_successes"], len(ai_watch.SOURCES))
        self.assertFalse(ai_watch.scan_due(
            self.data, config_data, now=self.now+timedelta(days=1)))
        self.assertEqual(ai_watch.deliver_reports(self.data), 2)
        self.assertEqual(ai_watch.deliver_reports(self.data), 0)
        db = Database(self.data / "personal_ai.db")
        chats = db.list_chats(user["id"])
        self.assertEqual(len(chats), 1)
        self.assertEqual(chats[0]["title"], "AI Technology Watch")
        last = db.get_recent_messages(chats[0]["id"])[0]
        self.assertIn("initial baseline", last["content"])
        self.assertIn("modified nothing", last["content"])
        db.close()
        later = self.now + timedelta(days=8)
        def fetch2(url, hosts):
            if "openai.com" in url:
                text = "<rss><channel>"+rss_item("model-v2","New multimodal vision capability")+rss_item()+"</channel></rss>"
                return text.encode()
            return fetch(url,hosts)
        new = ai_watch.scan_once(self.data, config_data, now=later, fetch=fetch2)
        self.assertEqual(new["new"], 1)
        self.assertEqual(ai_watch.deliver_reports(self.data), 1)
        final = ai_watch.current_report(self.data,config_data)
        self.assertEqual(final["interval_hours"], 168)
        self.assertEqual(final["source_count"], len(ai_watch.SOURCES))
        self.assertEqual(len(final["reports"]), 3)
        self.assertTrue(all(x["delivered"] for x in final["reports"]))
        db = Database(self.data / "personal_ai.db")
        self.assertEqual(len(db.get_recent_messages(chats[0]["id"])), 2)
        db.close()

    def test_partial_failure_leaves_other_sources_and_redacts(self):
        cfg = {"ai_watch_enabled": True}
        def fetch(url, hosts):
            if "openai.com" in url:
                raise TimeoutError("secret-token-abcd1234")
            return sample_atom() if "ollama/ollama" in url else b"<rss><channel/></rss>"
        out = ai_watch.scan_once(
            self.data, cfg, fetch=fetch, now=self.now,
        )
        self.assertEqual(out["failed_sources"], ["OpenAI"])
        state = ai_watch.current_report(self.data,cfg)
        self.assertNotIn("secret-token-abcd1234",str(state))
        self.assertEqual(state["last_checked"], self.now.isoformat())
        self.assertEqual(out["new"],1)

    def test_explicit_chat_commands_do_not_enable_via_persuasion(self):
        with patch.object(config, "DATA_DIR", self.data), \
             patch.object(config, "LOG_DIR", self.data / "logs"), \
             patch.object(config, "CONFIG_PATH", self.data / "config.json"):
            config.save_config(dict(config.DEFAULT_CONFIG))
            self.assertIsNone(ai_watch.chat_command(
                "Would you enable AI technology watch?",self.data))
            self.assertIsNone(ai_watch.chat_command(
                "I think an AI watch is a good idea",self.data))
            self.assertFalse(config.load_config()["ai_watch_enabled"])
            a=ai_watch.chat_command("enable AI technology watch",self.data)
            self.assertIn("enabled",a)
            self.assertTrue(config.load_config()["ai_watch_enabled"])
            self.assertIn("no saved findings",ai_watch.chat_command(
                "show AI technology watch report",self.data))
            a=ai_watch.chat_command("disable AI technology watch",self.data)
            self.assertIn("disabled",a)
            self.assertFalse(config.load_config()["ai_watch_enabled"])
            self.assertIn("disabled",ai_watch.chat_command(
                "check AI technology watch now",self.data))
            self.assertFalse((self.data / "ai_technology_watch.json").exists())

    def test_chat_backend_command_skips_model_and_preserves_history(self):
        with patch.object(config,"DATA_DIR",self.data), \
             patch.object(config,"LOG_DIR",self.data / "logs"), \
             patch.object(config,"CONFIG_PATH",self.data / "config.json"), \
             patch.object(gui_backend,"DATA_DIR",self.data), \
             patch.object(gui_backend,"ai_watch_chat_command",
                  wraps=ai_watch.chat_command) as command, \
             patch.object(gui_backend,"build_llm_client") as model:
            config.save_config(dict(config.DEFAULT_CONFIG))
            db=Database(self.data / "personal_ai.db")
            user=db.create_user("Tester")
            chat=db.create_chat(user["id"], "New chat")
            db.close()
            backend=gui_backend.ChatBackend.__new__(gui_backend.ChatBackend)
            backend.config=config.load_config()
            backend.logger=self.logger
            response=backend.send(chat["id"],"enable AI technology watch")
            self.assertIn("enabled",response)
            command.assert_called_once()
            model.assert_not_called()
            db=Database(self.data / "personal_ai.db")
            messages=db.get_recent_messages(chat["id"])
            self.assertEqual([m["role"] for m in messages],["user","assistant"])
            self.assertIn("enabled",messages[-1]["content"])
            db.close()


if __name__ == "__main__":
    unittest.main()
