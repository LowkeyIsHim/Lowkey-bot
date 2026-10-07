"""Bot logic tests. Uses the real python-telegram-bot if installed, otherwise light stubs
(stubs check our logic, not PTB's API, so the first live run on Spaceify is the real test)."""
import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest import mock
import tempfile

try:
    import telegram  # noqa: F401
except ImportError:
    tg = types.ModuleType("telegram")
    for name in ("BotCommand", "InlineKeyboardButton", "InlineKeyboardMarkup", "Update"):
        setattr(tg, name, type(name, (), {"__init__": lambda self, *a, **k: setattr(self, "args", (a, k))}))
    const = types.ModuleType("telegram.constants")
    const.ParseMode = types.SimpleNamespace(HTML="HTML")
    ext = types.ModuleType("telegram.ext")
    for name in ("Application", "CallbackQueryHandler", "CommandHandler"):
        setattr(ext, name, type(name, (), {}))
    ext.ContextTypes = types.SimpleNamespace(DEFAULT_TYPE=object)
    sys.modules.update({"telegram": tg, "telegram.constants": const, "telegram.ext": ext})

from lowkey import bot, config, store  # noqa: E402


class FakeMsg:
    def __init__(self):
        self.sent = []

    async def reply_text(self, text, **kw):
        m = FakeMsg()
        m.text, m.kw = text, kw
        self.sent.append(m)
        return m

    async def edit_text(self, text, **kw):
        self.text, self.kw = text, kw


class FakeJobQueue:
    def __init__(self):
        self.jobs, self.removed = [], 0

    def get_jobs_by_name(self, name):
        outer = self
        return [types.SimpleNamespace(schedule_removal=lambda: setattr(outer, "removed", outer.removed + 1))
                for _ in self.jobs]

    def run_daily(self, cb, time, name=None, chat_id=None, **kw):
        self.jobs.append((cb, time, name, chat_id))


class TestBotLogic(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self._p = [mock.patch.object(config, a, v) for a, v in [
            ("DATA_DIR", tmp), ("OUTPUT_DIR", tmp / "o"), ("USED_FILE", tmp / "u.json"),
            ("SETTINGS_FILE", tmp / "s.json"), ("LOG_DIR", tmp / "l"), ("GEMINI_API_KEY", ""), ("OWNER_ID", 42)]]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def test_parsers(self):
        self.assertEqual(bot.parse_pillar("a"), "alone")
        self.assertEqual(bot.parse_pillar("noexp"), None)  # not a prefix: falls back to random
        self.assertEqual(bot.parse_pillar("no_explanations"), "no_explanations")
        self.assertEqual(bot.parse_pillar("n"), "no_explanations")
        self.assertEqual(bot.parse_pillar("def"), "defense")
        self.assertIsNone(bot.parse_pillar("random"))
        self.assertEqual(bot.parse_format("int"), "interview")
        self.assertEqual(bot.parse_hhmm("6:30"), (6, 30))
        self.assertIsNone(bot.parse_hhmm("25:00"))
        self.assertIsNone(bot.parse_hhmm("abc"))

    def test_owner_only(self):
        called = []

        @bot.owner_only
        async def handler(update, context):
            called.append(1)

        def upd(uid):
            return types.SimpleNamespace(effective_user=types.SimpleNamespace(id=uid), callback_query=None)

        asyncio.run(handler(upd(7), None))
        self.assertEqual(called, [])
        asyncio.run(handler(upd(42), None))
        self.assertEqual(called, [1])

    def test_send_post_edits_placeholder(self):
        msg = FakeMsg()
        asyncio.run(bot._send_post(msg, "alone", "single"))
        placeholder = msg.sent[0]
        self.assertIn("POST 1", placeholder.text)
        self.assertEqual(placeholder.kw["parse_mode"], "HTML")
        self.assertIn("reply_markup", placeholder.kw)

    def test_send_post_survives_failure(self):
        msg = FakeMsg()
        with mock.patch.object(bot.engine, "build_post", side_effect=RuntimeError("boom")):
            asyncio.run(bot._send_post(msg, None))
        self.assertIn("broke", msg.sent[0].text)

    def test_schedule_daily_replaces_job(self):
        app = types.SimpleNamespace(job_queue=FakeJobQueue())
        bot.schedule_daily(app)
        store.set_run_time("07:15")
        bot.schedule_daily(app)
        self.assertEqual(app.job_queue.removed, 1)
        _, t, name, chat = app.job_queue.jobs[-1]
        self.assertEqual((t.hour, t.minute, name, chat), (7, 15, "daily", 42))
        self.assertEqual(str(t.tzinfo), config.BOT_TZ)

    def test_update_sends_sigterm(self):
        msg = FakeMsg()
        upd = types.SimpleNamespace(effective_user=types.SimpleNamespace(id=42), callback_query=None, message=msg)
        with mock.patch.object(bot.os, "kill") as kill:
            asyncio.run(bot.cmd_update(upd, None))
        kill.assert_called_once()
        self.assertIn("Restarting", msg.sent[0].text)

    def test_send_package(self):
        sent = []

        class Bot:
            async def send_message(self, chat_id, text, **kw):
                sent.append((chat_id, text))

        asyncio.run(bot._send_package(Bot(), 42, 3))
        self.assertEqual(len(sent), 4)  # header + 3 posts
        self.assertTrue(all(len(t) < 4000 for _, t in sent))


if __name__ == "__main__":
    unittest.main()
