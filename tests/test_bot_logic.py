"""Bot logic tests. Uses the real python-telegram-bot if installed, otherwise light stubs
(stubs check our logic, not PTB's API, so the first live run on Spaceify is the real test)."""
import asyncio
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

try:
    import telegram  # noqa: F401
except ImportError:
    class _Filter:
        def __and__(self, other): return self
        def __invert__(self): return self

    tg = types.ModuleType("telegram")
    for name in ("BotCommand", "InlineKeyboardButton", "InlineKeyboardMarkup", "Update"):
        setattr(tg, name, type(name, (), {"__init__": lambda self, *a, **k: setattr(self, "args", (a, k))}))
    const = types.ModuleType("telegram.constants")
    const.ParseMode = types.SimpleNamespace(HTML="HTML")
    ext = types.ModuleType("telegram.ext")
    for name in ("Application", "CallbackQueryHandler", "CommandHandler", "MessageHandler"):
        setattr(ext, name, type(name, (), {}))
    ext.ContextTypes = types.SimpleNamespace(DEFAULT_TYPE=object)
    ext.filters = types.SimpleNamespace(TEXT=_Filter(), COMMAND=_Filter())
    sys.modules.update({"telegram": tg, "telegram.constants": const, "telegram.ext": ext})

from lowkey import bot, config, store  # noqa: E402


class FakeMsg:
    chat_id = 7

    def __init__(self):
        self.sent = []

    async def reply_text(self, text, **kw):
        m = FakeMsg()
        m.text, m.kw = text, kw
        self.sent.append(m)
        return m

    async def edit_text(self, text, **kw):
        self.text, self.kw = text, kw


class FakeQuery:
    def __init__(self, data, msg):
        self.data, self.message, self.answers = data, msg, []

    async def answer(self, text=None, show_alert=False):
        self.answers.append((text, show_alert))


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kw):
        self.sent.append((chat_id, text, kw))


class FakeJobQueue:
    def __init__(self):
        self.jobs, self.removed = [], 0

    def get_jobs_by_name(self, name):
        outer = self
        return [types.SimpleNamespace(schedule_removal=lambda: setattr(outer, "removed", outer.removed + 1))
                for _ in self.jobs]

    def run_daily(self, cb, time, name=None, chat_id=None, **kw):
        self.jobs.append((cb, time, name, chat_id))


def upd(uid=42, query=None, message=None):
    return types.SimpleNamespace(effective_user=types.SimpleNamespace(id=uid), callback_query=query,
                                 message=message, effective_chat=types.SimpleNamespace(id=7))


class TestBot(unittest.TestCase):
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
        self.assertEqual(bot.parse_hhmm("6:30"), (6, 30))
        self.assertIsNone(bot.parse_hhmm("25:00"))
        self.assertIsNone(bot.parse_hhmm("abc"))
        brief, link = bot.split_idea("something about fake friends https://youtu.be/abcdefghijk?t=5 please")
        self.assertEqual(link, "https://youtu.be/abcdefghijk?t=5")
        self.assertIn("fake friends", brief)
        self.assertNotIn("youtu", brief)
        self.assertEqual(bot.split_idea("https://www.youtube.com/watch?v=abcdefghijk&t=1s")[1],
                         "https://www.youtube.com/watch?v=abcdefghijk&t=1s")
        self.assertEqual(bot.split_idea("just an idea"), ("just an idea", ""))
        self.assertEqual(bot.split_idea("https://example.com/x"), ("https://example.com/x", ""))

    def test_owner_only(self):
        called = []

        @bot.owner_only
        async def handler(update, context):
            called.append(1)

        asyncio.run(handler(upd(7), None))
        self.assertEqual(called, [])
        asyncio.run(handler(upd(42), None))
        self.assertEqual(called, [1])
        q = FakeQuery("new", FakeMsg())
        asyncio.run(handler(upd(7, query=q), None))
        self.assertEqual(q.answers, [("Private bot.", False)])

    def test_menu_screens(self):
        self.assertIn("MOVING IN SILENCE", bot.menu_text())
        self.assertIn("Gemini off", bot.menu_text())
        rows = bot.menu_kb().args[0][0]
        data = [b.args[1]["callback_data"] for row in rows for b in row]
        self.assertEqual(set(data), {"new", "plan", "menu:persona", "menu:trends", "menu:results", "menu:settings"})
        labels = lambda kb: [b.args[0][0] for row in kb.args[0][0] for b in row]  # noqa: E731
        self.assertIn("🤖 Turn Gemini off", labels(bot.settings_kb()))
        store.set_ai(False)
        self.assertIn("🤖 Turn Gemini on", labels(bot.settings_kb()))
        self.assertIn("full story", bot.persona_text())
        self.assertIn("No trend notes", bot.trends_text())
        self.assertIn("/besttimes", bot.times_text())

    def test_send_post_edits_placeholder(self):
        msg = FakeMsg()
        asyncio.run(bot._send_post(msg, "something about fake friends"))
        placeholder = msg.sent[0]
        self.assertIn("POST 1", placeholder.text)
        self.assertEqual(placeholder.kw["parse_mode"], "HTML")
        self.assertIn("reply_markup", placeholder.kw)

    def test_send_post_survives_failure(self):
        msg = FakeMsg()
        with mock.patch.object(bot.engine, "build_post", side_effect=RuntimeError("boom")):
            asyncio.run(bot._send_post(msg))
        self.assertIn("broke", msg.sent[0].text)

    def test_buttons(self):
        ctx = types.SimpleNamespace(bot=FakeBot(), application=None, user_data={})
        msg = FakeMsg()

        def press(data):
            q = FakeQuery(data, msg)
            asyncio.run(bot.on_button(upd(query=q), ctx))
            return q

        press("new")
        self.assertIn("POST 1", msg.sent[-1].text)
        pid = store.remember_post(bot.engine.build_post())
        press(f"cc:{pid}")
        self.assertIn("CAPCUT", msg.sent[-1].text)
        stale = press("cc:zzzzzz")
        self.assertEqual(stale.answers[0][1], True)  # alert
        press("menu:home")
        self.assertIn("MOVING IN SILENCE", msg.text)
        press("menu:settings")
        self.assertIn("Settings", msg.text)
        self.assertTrue(store.ai_enabled())
        press("set:ai")
        self.assertFalse(store.ai_enabled())
        press("set:times")
        self.assertIn("besttimes", msg.text)
        press("per:show")
        self.assertIn("haven't added", msg.sent[-1].text)
        press("tr:refresh")
        self.assertIn("Gemini is off", msg.text)
        with mock.patch.object(bot.os, "kill") as kill:
            press("set:update")
            self.assertIn("Restart the bot", msg.text)
            kill.assert_not_called()  # confirmation first
            press("set:update_go")
            kill.assert_called_once()

    def test_plan_button_and_package(self):
        ctx = types.SimpleNamespace(bot=FakeBot(), user_data={})
        msg = FakeMsg()
        asyncio.run(bot.on_button(upd(query=FakeQuery("plan", msg)), ctx))
        sent = ctx.bot.sent
        self.assertEqual(len(sent), 4)  # header + 3 posts
        self.assertIn("Today's plan", sent[0][1])
        self.assertTrue(all(len(t) < 4000 for _, t, _ in sent))

    def test_text_message_becomes_idea(self):
        msg = FakeMsg()
        msg.text = "something about outgrowing friends"
        asyncio.run(bot.on_text(upd(message=msg), types.SimpleNamespace(user_data={})))
        self.assertIn("POST 1", msg.sent[0].text)

    def test_log_results_flow(self):
        ctx = types.SimpleNamespace(bot=FakeBot(), user_data={})
        msg = FakeMsg()
        pid = store.remember_post(bot.engine.build_post())
        asyncio.run(bot.on_button(upd(query=FakeQuery(f"lr:{pid}", msg)), ctx))
        self.assertEqual(ctx.user_data["awaiting_results"], pid)
        self.assertIn("Example: 12400", msg.sent[-1].text)

        def say(text):
            m = FakeMsg()
            m.text = text
            asyncio.run(bot.on_text(upd(message=m), ctx))
            return m

        bad = say("830 12400 95")  # likes bigger than views: wrong order
        self.assertIn("couldn't read", bad.sent[0].text)
        self.assertEqual(ctx.user_data["awaiting_results"], pid)  # still waiting
        ok = say("12400 830 95 210 62")
        self.assertIn("Logged", ok.sent[0].text)
        self.assertNotIn("awaiting_results", ctx.user_data)
        self.assertEqual(store.read_results()[pid]["metrics"]["shares"], 95)
        # an idea typed while waiting is treated as an idea
        pid2 = store.remember_post(bot.engine.build_post())
        asyncio.run(bot.on_button(upd(query=FakeQuery(f"lr:{pid2}", msg)), ctx))
        idea = say("make one about people who only text when they need something")
        self.assertIn("POST 1", idea.sent[0].text)
        self.assertNotIn("awaiting_results", ctx.user_data)
        # stale post
        q = FakeQuery("lr:zzzzzz", msg)
        asyncio.run(bot.on_button(upd(query=q), ctx))
        self.assertEqual(q.answers[0][1], True)
        # results screen
        asyncio.run(bot.on_button(upd(query=FakeQuery("menu:results", msg)), ctx))
        self.assertIn("1 post logged", msg.text)

    def test_commands(self):
        msg = FakeMsg()
        app = types.SimpleNamespace(job_queue=FakeJobQueue())
        ctx = types.SimpleNamespace(args=["07:15"], application=app, bot=FakeBot(), user_data={})
        asyncio.run(bot.cmd_settime(upd(message=msg), ctx))
        _, t, name, chat = app.job_queue.jobs[-1]
        self.assertEqual((t.hour, t.minute, name, chat), (7, 15, "daily", 42))
        self.assertEqual(str(t.tzinfo), config.BOT_TZ)
        ctx.args = ["08:00", "13:00", "19:30", "23:15"]
        asyncio.run(bot.cmd_besttimes(upd(message=msg), ctx))
        self.assertIn("Saved", msg.sent[-1].text)
        ctx.args = ["I", "go", "quiet", "when", "hurt"]
        asyncio.run(bot.cmd_persona(upd(message=msg), ctx))
        self.assertEqual(msg.sent[-1].text, "Added.")
        ctx.args = ["SOUNDS:", "snowfall"]
        asyncio.run(bot.cmd_trends(upd(message=msg), ctx))
        self.assertIn("saved", msg.sent[-1].text)
        with mock.patch.object(bot.os, "kill") as kill:
            asyncio.run(bot.cmd_update(upd(message=msg), ctx))
            kill.assert_called_once()


if __name__ == "__main__":
    unittest.main()
