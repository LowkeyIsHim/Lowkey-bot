"""Telegram layer: start menu, buttons, daily plan. Generation runs in worker threads so the bot
never blocks while Gemini thinks."""
import asyncio
import functools
import html
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, time as dtime, timedelta
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (Application, CallbackQueryHandler, CommandHandler, ContextTypes,
                          MessageHandler, filters)

try:  # PTB 21+
    from telegram import LinkPreviewOptions
    NOPREVIEW = {"link_preview_options": LinkPreviewOptions(is_disabled=True)}
except ImportError:  # older PTB
    NOPREVIEW = {"disable_web_page_preview": True}

from . import brain, capcut, config, engine, insights, persona, quotes, reminders, store, timing, trends
from . import own as own_mod

log = logging.getLogger("bot")
HTML = ParseMode.HTML


# ------------------------------------------------------------------ helpers
def parse_hhmm(text: str) -> Optional[Tuple[int, int]]:
    try:
        hh, mm = text.strip().split(":")
        hh, mm = int(hh), int(mm)
    except ValueError:
        return None
    return (hh, mm) if 0 <= hh < 24 and 0 <= mm < 60 else None


def split_idea(text: str) -> Tuple[str, str]:
    """(brief, youtube_link) from a plain message. The link may be anywhere in the text."""
    match = brain.YT_RE.search(text or "")
    link = match.group(0) if match else ""
    brief = (text or "").replace(link, "").strip() if link else (text or "").strip()
    return brief[:400], link


def _ai_on() -> bool:
    return brain.ai_available()


def _ago(iso: str) -> str:
    try:
        mins = int((datetime.now() - datetime.fromisoformat(iso)).total_seconds() // 60)
    except (TypeError, ValueError):
        return "a while ago"
    return "just now" if mins < 1 else f"{mins}m ago" if mins < 60 else f"{mins // 60}h ago"


def _ai_light() -> str:
    """One-line Gemini status for the menu: green works, yellow failing (with the reason), red off."""
    if not config.GEMINI_API_KEY:
        return "🔴 Gemini off: no API key on the server (pre-written lines)"
    if not store.ai_enabled():
        return "🔴 Gemini off: switched off in Settings (pre-written lines)"
    last = store.get_ai_status()
    if last and not last["ok"]:
        return f"🟡 Gemini failing: {last['msg']} (pre-written lines)"
    if last and last["ok"] and last.get("msg"):
        return "🟢 Gemini on (main model struggling, using the backup)"
    return "🟢 Gemini on"


def _ai_state() -> str:
    """Longer Gemini status for Settings, including when it last worked or failed."""
    light = _ai_light()
    last = store.get_ai_status()
    if light.startswith("🟢"):
        note = f"\n{last['msg']}" if last and last["ok"] and last.get("msg") else ""
        return "ON" + (f", last call worked {_ago(last['ts'])}" if last and last["ok"] else ", not tested yet") + note
    return light.split(" ", 1)[1] + (f" (last tried {_ago(last['ts'])})" if last and not last["ok"] else "")


def owner_only(fn):
    """Only the owner may use the bot (it spends your Gemini quota). Everyone else is ignored."""
    @functools.wraps(fn)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user = update.effective_user
        if config.OWNER_ID and user and user.id == config.OWNER_ID:
            return await fn(update, context)
        if update.callback_query:
            await update.callback_query.answer("Private bot.")
        return None
    return wrapper


# ------------------------------------------------------------------ screens
def menu_text() -> str:
    state = _ai_light()
    return (
        "<b>⚙️ MOVING IN SILENCE</b>\n"
        "<i>@im_just_lowkey · Lowkey He's Him</i>\n"
        "━━━━━━━━━━━━━━━\n"
        "✨ <b>New post</b>  Gemini decides everything\n"
        "📅 <b>Today's plan</b>  timed posts for the day\n"
        "🧠 <b>Persona</b>  teach it more about you\n"
        "📈 <b>Trends</b>  sounds and hashtags going around\n"
        "➕ <b>My own post</b>  your quote, sound, clip\n"
        "📆 <b>Week plan</b>  7 posts for your Saturday edit\n"
        "📊 <b>Results</b>  what's working on your page\n"
        "⚙️ <b>Settings</b>  status, times, update\n"
        "━━━━━━━━━━━━━━━\n"
        f"{html.escape(state)}  ·  daily drop {html.escape(store.get_run_time())}\n\n"
        "<i>Or type an idea, paste a YouTube link, or send a photo or video and I'll build the post around it.</i>"
    )


def menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✨ New post", callback_data="new"),
         InlineKeyboardButton("📅 Today's plan", callback_data="plan")],
        [InlineKeyboardButton("🧠 Persona", callback_data="menu:persona"),
         InlineKeyboardButton("📈 Trends", callback_data="menu:trends")],
        [InlineKeyboardButton("➕ My own post", callback_data="own"),
         InlineKeyboardButton("📆 Week plan", callback_data="week")],
        [InlineKeyboardButton("📊 Results", callback_data="menu:results"),
         InlineKeyboardButton("⚙️ Settings", callback_data="menu:settings")],
    ])


def settings_kb() -> InlineKeyboardMarkup:
    ai = "🤖 Turn Gemini off" if store.ai_enabled() else "🤖 Turn Gemini on"
    rem = "🔔 Turn reminders off" if store.reminders_enabled() else "🔔 Turn reminders on"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧪 Test Gemini", callback_data="set:test"),
         InlineKeyboardButton(ai, callback_data="set:ai")],
        [InlineKeyboardButton(rem, callback_data="set:rem"),
         InlineKeyboardButton("🕕 Daily drop time", callback_data="set:time")],
        [InlineKeyboardButton("⏰ Best post times", callback_data="set:times"),
         InlineKeyboardButton("🔄 Update code", callback_data="set:update")],
        [InlineKeyboardButton(f"📅 Posts per day: {store.get_posts_per_day()}", callback_data="set:perday"),
         InlineKeyboardButton("🏠 Menu", callback_data="menu:home")],
    ])


def post_kb(post_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 CapCut steps", callback_data=f"cc:{post_id}"),
         InlineKeyboardButton("✅ I posted it", callback_data=f"posted:{post_id}")],
        [InlineKeyboardButton("📊 Log results", callback_data=f"lr:{post_id}"),
         InlineKeyboardButton("🔄 Another", callback_data="new")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:show")],
    ])


def reminder_post_kb(post_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📄 Show the post", callback_data=f"show:{post_id}"),
         InlineKeyboardButton("✅ I posted it", callback_data=f"posted:{post_id}")],
    ])


def reminder_log_kb(post_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("📊 Log results", callback_data=f"lr:{post_id}"),
                                  InlineKeyboardButton("Skip", callback_data="skip")]])


def _home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:home")]])


def settings_text() -> str:
    return (
        "<b>⚙️ Settings</b>\n\n"
        f"Gemini: {html.escape(_ai_state())}\n"
        f"Daily drop: {html.escape(store.get_run_time())} ({html.escape(config.BOT_TZ)})\n"
        f"Reminders: {'on' if store.reminders_enabled() else 'off'}\n"
        f"Posts per day: {store.get_posts_per_day()} (tap the button to change)\n"
        f"Today's plan: {store.posts_today(store.today())} posts\n"
        f"Private persona lines: {len(persona.get_extra().splitlines())}\n"
        f"Quotes used (last {config.NO_REPEAT_DAYS} days): {quotes.used_count()}"
    )


def persona_text() -> str:
    n = len(persona.get_extra().splitlines())
    return ("<b>🧠 Persona</b>\n\nI already know your page, your bio and your full story, and Gemini reads it on every "
            f"post. Extra lines you added here: {n}.\n\n"
            "Add a line:\n<code>/persona I go quiet when I'm hurting and people read it as attitude</code>")


def persona_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("👁 Show my lines", callback_data="per:show"),
         InlineKeyboardButton("🗑 Clear my lines", callback_data="per:clear")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:home")],
    ])


def trends_text() -> str:
    notes = trends.get()
    age = trends.age_hours()
    body = html.escape(notes) if notes else "No trend notes yet."
    when = f"\n\n<i>Updated {int(age)}h ago</i>" if (notes and age is not None) else ""
    return (f"<b>📈 Trends</b>\n\n{body}{when}\n\nGemini uses these when it picks sounds and hashtags. "
            "Check a sound exists before you use it. Paste your own with:\n<code>/trends your notes</code>")


def trends_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔎 Refresh with Gemini", callback_data="tr:refresh")],
        [InlineKeyboardButton("🏠 Menu", callback_data="menu:home")],
    ])


def times_text() -> str:
    t = timing.band_times()
    return ("<b>⏰ Best post times</b> (" + html.escape(config.BOT_TZ) + ")\n\n"
            f"Morning {t['morning']} · Afternoon {t['afternoon']} · Evening {t['evening']} · Late night {t['late_night']}\n\n"
            "These are starting guesses. Check TikTok: Analytics > Followers > Most active times, then set yours:\n"
            "<code>/besttimes 08:00 13:00 19:30 22:30</code>\n(morning, afternoon, evening, late night)")


# ------------------------------------------------------------------ sending posts
async def _send_post(message, brief: str = "", link: str = "") -> None:
    note = "⏳ Gemini is deciding everything..." if _ai_on() else "⏳ cooking (pre-written mode)..."
    wait = await message.reply_text(note)
    try:
        recent = await asyncio.to_thread(store.recent_posts, 12)
        post = await asyncio.to_thread(engine.build_post, recent, brief, link)
        post_id = store.remember_post(post)
    except Exception:  # noqa: BLE001
        log.exception("build_post failed")
        await wait.edit_text("Something broke while generating. Check the logs.")
        return
    await wait.edit_text(engine.render_post(post, html=True), parse_mode=HTML,
                         reply_markup=post_kb(post_id), **NOPREVIEW)


def _hook(post: dict) -> str:
    return " ".join(post["on_screen_text"][0].split())[:80]


def _schedule(job_queue, row: dict) -> None:
    if job_queue is not None:
        job_queue.run_once(reminder_job, when=datetime.fromisoformat(row["when"]), name=row["id"],
                           chat_id=config.OWNER_ID, data=row)


async def _send_package(bot, chat_id: int, count: Optional[int] = None, job_queue=None) -> None:
    await asyncio.to_thread(trends.refresh_if_stale)
    pkg = await asyncio.to_thread(engine.generate_daily, count)
    ids = [store.remember_post(p) for p in pkg["posts"]]
    scheduled = 0
    if store.reminders_enabled():
        for post, pid in zip(pkg["posts"], ids):
            when = reminders.when_today(post)
            if when:
                _schedule(job_queue, reminders.add("post", pid, when))
                scheduled += 1
    header = engine.render_header(pkg, html=True)
    if scheduled:
        header += "\n🔔 I'll remind you at each time."
    first, _, rest = header.partition("\n")
    await bot.send_message(chat_id, f"<b>{first}</b>\n{rest}", parse_mode=HTML)
    for post, pid in zip(pkg["posts"], ids):
        await bot.send_message(chat_id, engine.render_post(post, html=True), parse_mode=HTML,
                               reply_markup=post_kb(pid), **NOPREVIEW)


# ------------------------------------------------------------------ commands
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not config.OWNER_ID:
        await update.message.reply_text(
            f"Setup: your Telegram ID is {user.id}. Set TELEGRAM_OWNER_ID={user.id} and restart the bot.")
    elif user.id == config.OWNER_ID:
        await update.message.reply_text(menu_text(), parse_mode=HTML, reply_markup=menu_kb())


async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Your Telegram ID: {update.effective_user.id}")


@owner_only
async def cmd_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.user_data is not None:
        context.user_data.pop("awaiting_results", None)
    await update.message.reply_text(menu_text(), parse_mode=HTML, reply_markup=menu_kb())


@owner_only
async def cmd_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    brief, link = split_idea(" ".join(context.args or []))
    await _send_post(update.message, brief, link)


RESULTS_HELP = ("Send a screenshot of the video's TikTok analytics (best), or type the numbers: views, likes, "
                "shares, saves, watch % in that order.\n"
                "Example: 12400 830 95 210 62\n"
                "Or label them: 12.4k views 95 shares 210 saves")
RESULTS_TTL = 30 * 60


def _set_waiting(context, post_id: str) -> None:
    context.user_data["awaiting_results"] = {"id": post_id, "ts": time.time(), "raw": {}}


def _waiting(context) -> Optional[dict]:
    """The post you tapped Log results on, if it was within the last 30 minutes."""
    if context.user_data is None:
        return None
    w = context.user_data.get("awaiting_results")
    if w and time.time() - w["ts"] < RESULTS_TTL:
        return w
    context.user_data.pop("awaiting_results", None)
    return None


async def _save_metrics(message, post_id: str, metrics: dict, how: str) -> bool:
    post = store.get_post(post_id)
    if not post:
        await message.reply_text("That post is too old to log. Generate a new one.")
        return False
    store.save_result(post_id, insights.row_from_post(post, post_id, metrics))
    rank, total = insights.rank_of(post_id)
    rate = (metrics["shares"] + metrics["saves"]) / metrics["views"] * 100
    more = "" if total >= 3 else "\nLog 3+ posts and Gemini starts learning from them."
    await message.reply_text(f"✅ {how}: {insights.describe(metrics)}.\n{rate:.1f}% shares+saves. "
                             f"Rank #{rank} of {total}.{more}")
    return True


@owner_only
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Plain message: stats for a post you tapped Log results on, otherwise an idea or a YouTube link."""
    if not (update.message and update.message.text):
        return
    text = update.message.text
    waiting = _waiting(context)
    if waiting:
        if insights.looks_like_numbers(text):
            metrics = insights.parse_metrics(text)
            if not metrics:
                await update.message.reply_text("I couldn't read that.\n\n" + RESULTS_HELP)
                return
            await _save_metrics(update.message, waiting["id"], metrics, "Logged")
            context.user_data.pop("awaiting_results", None)
            return
        context.user_data.pop("awaiting_results", None)  # it was an idea, not stats
    if _own_active(context):
        if await _make_own_post(update.message, text):
            _end_own(context)
        return
    brief, link = split_idea(text)
    await _send_post(update.message, brief, link)


OWN_TTL = 30 * 60
OWN_HELP = ("➕ Your own post\n\nSend it as ONE message. Anything you leave out, Gemini fills in.\n\n"
            "quote: I stopped explaining myself || the day nobody listened\n"
            "sound: snowfall - oneheart\n"
            "clip: Shelby at the window\n"
            "tags: #stoic #lowkey\n"
            "caption: No updates.\n"
            "time: 8:30pm\n\n"
            "Only the quote is needed. || splits a hook from its payoff. You can also send a video or photo and put "
            "all of this in the caption.")


def _start_own(context) -> None:
    context.user_data["own_mode"] = {"ts": time.time()}


def _own_active(context) -> bool:
    if context.user_data is None:
        return False
    mode = context.user_data.get("own_mode")
    if mode and time.time() - mode["ts"] < OWN_TTL:
        return True
    context.user_data.pop("own_mode", None)
    return False


def _end_own(context) -> None:
    if context.user_data is not None:
        context.user_data.pop("own_mode", None)


async def _make_own_post(msg, text: str) -> bool:
    """Build a post from the owner's own quote (and sound, clip, tags...). Returns True when it was built."""
    own = own_mod.parse_own(text)
    if not own["parts"]:
        await msg.reply_text("I need at least your quote. Type it, then add anything else you decided "
                             "(sound, clip, tags, time).\n\n" + OWN_HELP)
        return False
    wait = await msg.reply_text("⏳ finishing your post...")
    try:
        recent = await asyncio.to_thread(store.recent_posts, 12)
        post = await asyncio.to_thread(engine.build_own_post, own, None, recent)
        post_id = store.remember_post(post)
    except Exception:  # noqa: BLE001
        log.exception("own post failed")
        await wait.edit_text("Something broke while building your post. Check the logs.")
        return False
    await wait.edit_text(engine.render_post(post, html=True), parse_mode=HTML,
                         reply_markup=post_kb(post_id), **NOPREVIEW)
    return True


MAX_MEDIA_BYTES = 18 * 1024 * 1024  # Gemini reads files up to about this size directly; Telegram bots cap at 20 MB


def _media_item(msg):
    """(telegram file object, 'image' or 'video', mime type) for whatever the owner sent, else (None, None, None)."""
    if getattr(msg, "photo", None):
        return msg.photo[-1], "image", "image/jpeg"
    for attr in ("video", "animation"):
        item = getattr(msg, attr, None)
        if item:
            return item, "video", getattr(item, "mime_type", None) or "video/mp4"
    doc = getattr(msg, "document", None)
    if doc:
        mime = getattr(doc, "mime_type", "") or ""
        if mime.startswith("video/"):
            return doc, "video", mime
        if mime.startswith("image/"):
            return doc, "image", mime
    return None, None, None


async def _read_stats_screenshot(msg, item, mime: str, waiting: dict) -> None:
    """A screenshot of a video's analytics: Gemini reads the numbers. Several screenshots merge."""
    if not brain.ai_available():
        await msg.reply_text("Gemini is off, so I can't read screenshots. Type the numbers instead.\n\n" + RESULTS_HELP)
        return
    wait = await msg.reply_text("🔎 reading your screenshot...")
    raw = None
    try:
        tg_file = await item.get_file()
        data = bytes(await tg_file.download_as_bytearray())
        raw = await asyncio.to_thread(insights.read_screenshot, data, mime)
    except Exception:  # noqa: BLE001
        log.exception("screenshot download/read failed")
    if not raw:
        await wait.edit_text("I couldn't read that screenshot. Try a clearer one, or type the numbers.\n\n" + RESULTS_HELP)
        return
    waiting["raw"] = insights.merge_raw(waiting["raw"], raw)
    metrics = insights.normalize_metrics(waiting["raw"])
    if not metrics:
        await wait.edit_text("I couldn't find the views number yet. Send the screenshot that shows views, or type "
                             "the numbers.")
        return
    post = store.get_post(waiting["id"])
    if not post:
        await wait.edit_text("That post is too old to log. Generate a new one.")
        return
    store.save_result(waiting["id"], insights.row_from_post(post, waiting["id"], metrics))
    rank, total = insights.rank_of(waiting["id"])
    await wait.edit_text(f"✅ I read: {insights.describe(metrics)}. Rank #{rank} of {total}.\n"
                         "Wrong, or another screenshot with more numbers? Send it, or type the right numbers.")


async def _post_from_media(msg, item, kind: str, mime: str, own_mode: bool = False) -> bool:
    """Build today's post around a photo or video the owner sent (the caption is his idea, or in own mode his
    own quote, sound, clip and tags). Returns True when a post was built."""
    if not own_mode and not brain.ai_available():
        await msg.reply_text("I need Gemini to look at your " + ("clip" if kind == "video" else "photo") +
                             f".\nWhy it's off: {brain.why_not()}.\nSettings > 🧪 Test Gemini shows the details.")
        return False
    size = getattr(item, "file_size", None)
    if size and size > MAX_MEDIA_BYTES:
        await msg.reply_text("That file is too big for me to read (the limit is about 18 MB). Trim it to the part you "
                             "want, around 10-15 seconds, or export at 720p from CapCut, then send it again.")
        return False
    caption = (getattr(msg, "caption", None) or "").strip()
    brief, link = split_idea(caption)
    wait = await msg.reply_text("🎞 watching your clip..." if kind == "video" else "🖼 looking at your photo...")
    try:
        tg_file = await item.get_file()
        data = bytes(await tg_file.download_as_bytearray())
        recent = await asyncio.to_thread(store.recent_posts, 12)
        if own_mode:
            post = await asyncio.to_thread(engine.build_own_post, own_mod.parse_own(caption), (data, mime, kind), recent)
        else:
            post = await asyncio.to_thread(engine.build_media_post, data, mime, kind, recent, brief, link)
    except Exception:  # noqa: BLE001
        log.exception("media post failed")
        await wait.edit_text("I couldn't download that file. Telegram only lets me read files under 20 MB, so try a "
                             "shorter or smaller one.")
        return False
    if post is None:
        await wait.edit_text(f"Gemini couldn't build a post from that: {brain.why_not()}.")
        return False
    post_id = store.remember_post(post)
    await wait.edit_text(engine.render_post(post, html=True), parse_mode=HTML,
                         reply_markup=post_kb(post_id), **NOPREVIEW)
    return True


@owner_only
async def on_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """A photo or video. If you tapped Log results, an image is read as analytics. Otherwise it becomes a post."""
    msg = update.message
    item, kind, mime = _media_item(msg)
    if item is None:
        return
    waiting = _waiting(context)
    if waiting and kind == "image":
        await _read_stats_screenshot(msg, item, mime, waiting)
    elif _own_active(context):
        if await _post_from_media(msg, item, kind, mime, own_mode=True):
            _end_own(context)
    else:
        await _post_from_media(msg, item, kind, mime)


on_photo = on_media  # old name


async def _background(context, coro) -> None:
    """Run a long job without freezing the bot (button presses and messages keep working meanwhile)."""
    app = getattr(context, "application", None)
    if app is not None and hasattr(app, "create_task"):
        app.create_task(coro)
    else:
        await coro


async def _send_week(bot, chat_id: int, include_today: bool = False, job_queue=None) -> None:
    """Plan 7 posts, one per day, for your Saturday edit: each post, then the week at a glance and a shopping list."""
    start = store.today() + timedelta(days=0 if include_today else 1)
    end = start + timedelta(days=6)
    await bot.send_message(chat_id, f"📆 Building your week ({start:%a %d %b} to {end:%a %d %b}). One post at a "
                                    "time, about a minute each. Keep studying, I'll send everything here.")
    await asyncio.to_thread(trends.refresh_if_stale)
    recent = list(await asyncio.to_thread(store.recent_posts, 12))
    posts: List[dict] = []
    for i in range(7):
        day = start + timedelta(days=i)
        try:
            post = await asyncio.to_thread(engine.build_post, recent, "", "", i + 1, None, day)
        except Exception:  # noqa: BLE001
            log.exception("week plan failed on day %d", i + 1)
            await bot.send_message(chat_id, f"Stopped at day {i + 1}: something broke. Check the logs.")
            break
        post["date"] = day.isoformat()
        pid = store.remember_post(post)
        recent.append(post)
        posts.append(post)
        if store.reminders_enabled():
            when = engine.when_for(post)
            if when:
                _schedule(job_queue, reminders.add("post", pid, when))
        await bot.send_message(chat_id, engine.render_post(post, html=True), parse_mode=HTML,
                               reply_markup=post_kb(pid), **NOPREVIEW)
    if posts:
        await asyncio.to_thread(engine.save_week, posts, start)
        tail = "\n\n🔔 I'll remind you on each day at its time." if store.reminders_enabled() else ""
        await bot.send_message(chat_id, engine.render_week_header(posts, html=True) + tail, parse_mode=HTML)
        await bot.send_message(chat_id, engine.render_shopping_list(posts, html=True), parse_mode=HTML, **NOPREVIEW)


@owner_only
async def cmd_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    today = bool(context.args) and context.args[0].lower() in ("today", "now")
    await _background(context, _send_week(context.bot, update.effective_chat.id, today,
                                          getattr(context, "job_queue", None)))


@owner_only
async def cmd_mine(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """/mine <your quote ...> builds it now. /mine alone explains the format and waits for your message."""
    text = " ".join(context.args or []).strip()
    if text:
        await _make_own_post(update.message, text)
    else:
        _start_own(context)
        await update.message.reply_text(OWN_HELP)


@owner_only
async def cmd_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = None
    if context.args and context.args[0].isdigit():
        count = max(1, min(int(context.args[0]), 6))
    await update.message.reply_text("⏳ building today's plan...")
    await _send_package(context.bot, update.effective_chat.id, count, getattr(context, "job_queue", None))


@owner_only
async def cmd_persona(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        _, msg = persona.add_extra(" ".join(context.args))
        await update.message.reply_text(msg)
    else:
        await update.message.reply_text(persona_text(), parse_mode=HTML, reply_markup=persona_kb())


@owner_only
async def cmd_trends(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        trends.set_manual(" ".join(context.args))
        await update.message.reply_text("Trend notes saved.")
    else:
        await update.message.reply_text(trends_text(), parse_mode=HTML, reply_markup=trends_kb())


@owner_only
async def cmd_besttimes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    saved = bool(context.args) and timing.set_band_times(context.args)
    await update.message.reply_text(("✅ Saved.\n\n" if saved else "") + times_text(), parse_mode=HTML)


@owner_only
async def cmd_settime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    parsed = parse_hhmm(context.args[0]) if context.args else None
    if not parsed:
        await update.message.reply_text(
            f"Usage: /settime 06:30  (24h, {config.BOT_TZ}). Now: {store.get_run_time()}")
        return
    store.set_run_time(f"{parsed[0]:02d}:{parsed[1]:02d}")
    schedule_daily(context.application)
    await update.message.reply_text(f"Daily drop set to {parsed[0]:02d}:{parsed[1]:02d} ({config.BOT_TZ}).")


@owner_only
async def cmd_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _restart(update.message)


def _git_version() -> str:
    """Short hash and subject of the code that is running, e.g. 'a1b2c3d Add week plan'. Empty if unknown."""
    try:
        out = subprocess.run(["git", "-C", str(config.BASE_DIR), "log", "-1", "--pretty=%h %s"],
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:  # noqa: BLE001
        return ""


async def _restart(message) -> None:
    """Exit cleanly; the app.py launcher re-pulls the repo and starts the bot again.
    A note is saved first so the new process can message you the moment it is back."""
    store.update_settings(update_pending={"chat_id": message.chat_id, "old": _git_version(), "ts": time.time()})
    await message.reply_text("🔄 Restarting to pull the latest code. I'll message you here the moment it's done "
                             "(usually about a minute).")
    os.kill(os.getpid(), signal.SIGTERM)


async def update_done_job(context: ContextTypes.DEFAULT_TYPE):
    """Runs once at startup: if you asked for an update, say that it finished (and which version is running)."""
    pending = store.read_settings().get("update_pending")
    if not pending:
        return
    store.update_settings(update_pending=None)
    if time.time() - pending.get("ts", 0) > 15 * 60:
        return  # a stale note from a crash, not a fresh /update
    new, old = _git_version(), pending.get("old", "")
    if new and old and new == old:
        headline = "✅ Update done. You were already on the latest code, so nothing changed."
    else:
        headline = "✅ Update done. The new code is running."
    lines = [headline] + ([f"Version: {new}"] if new else []) + [_ai_light()]
    await context.bot.send_message(pending["chat_id"], "\n".join(lines))


# ------------------------------------------------------------------ buttons
@owner_only
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data, msg = query.data, query.message

    if data.startswith("cc:"):
        post = store.get_post(data[3:])
        if not post:
            await query.answer("That post is too old. Generate a new one.", show_alert=True)
            return
        await query.answer()
        await msg.reply_text(capcut.steps(post))
        return

    if data.startswith("lr:"):
        if not store.get_post(data[3:]):
            await query.answer("That post is too old to log.", show_alert=True)
            return
        await query.answer()
        _set_waiting(context, data[3:])
        await msg.reply_text(RESULTS_HELP)
        return

    if data.startswith("show:") or data.startswith("posted:"):
        kind, pid = data.split(":", 1)
        post = store.get_post(pid)
        if not post:
            await query.answer("That post is too old.", show_alert=True)
            return
        await query.answer()
        if kind == "show":
            await msg.reply_text(engine.render_post(post, html=True), parse_mode=HTML,
                                 reply_markup=post_kb(pid), **NOPREVIEW)
        elif store.reminders_enabled():
            when = reminders.log_time()
            _schedule(getattr(context, "job_queue", None), reminders.add("log", pid, when))
            await msg.reply_text(f"✅ Nice. I'll remind you to log results on {when:%a} at {when:%H:%M}.")
        else:
            await msg.reply_text("✅ Nice. (Reminders are off, so tap 📊 Log results after about 48 hours.)")
        return

    await query.answer()
    if data == "own":
        _start_own(context)
        await msg.reply_text(OWN_HELP)
    elif data == "week":
        await _background(context, _send_week(context.bot, msg.chat_id, False, getattr(context, "job_queue", None)))
    elif data == "new":
        await _send_post(msg)
    elif data == "plan":
        await msg.reply_text("⏳ building today's plan...")
        await _send_package(context.bot, msg.chat_id, None, getattr(context, "job_queue", None))
    elif data == "menu:show":
        await msg.reply_text(menu_text(), parse_mode=HTML, reply_markup=menu_kb())
    elif data == "menu:home":
        await msg.edit_text(menu_text(), parse_mode=HTML, reply_markup=menu_kb())
    elif data == "menu:settings":
        await msg.edit_text(settings_text(), parse_mode=HTML, reply_markup=settings_kb())
    elif data == "menu:results":
        await msg.edit_text(insights.breakdown_text() + own_mod.author_breakdown(), reply_markup=_home_kb())
    elif data == "menu:persona":
        await msg.edit_text(persona_text(), parse_mode=HTML, reply_markup=persona_kb())
    elif data == "menu:trends":
        await msg.edit_text(trends_text(), parse_mode=HTML, reply_markup=trends_kb())
    elif data == "set:status":
        await msg.edit_text(settings_text(), parse_mode=HTML, reply_markup=settings_kb())
    elif data == "set:test":
        await msg.edit_text("🧪 testing Gemini...", reply_markup=_home_kb())
        ok, text = await asyncio.to_thread(brain.ping, True)
        await msg.edit_text(("✅ " if ok else "❌ ") + text, reply_markup=settings_kb())
    elif data == "set:ai":
        store.set_ai(not store.ai_enabled())
        await msg.edit_text(settings_text(), parse_mode=HTML, reply_markup=settings_kb())
    elif data == "skip":
        await msg.edit_text("Skipped.")
    elif data == "set:perday":
        store.set_posts_per_day(store.get_posts_per_day() % 3 + 1)  # 1 -> 2 -> 3 -> 1
        await msg.edit_text(settings_text(), parse_mode=HTML, reply_markup=settings_kb())
    elif data == "set:rem":
        store.set_reminders(not store.reminders_enabled())
        await msg.edit_text(settings_text(), parse_mode=HTML, reply_markup=settings_kb())
    elif data == "set:time":
        await msg.edit_text(f"Daily drop is {store.get_run_time()} ({config.BOT_TZ}).\nChange it:\n"
                            "<code>/settime 06:30</code>", parse_mode=HTML, reply_markup=_home_kb())
    elif data == "set:times":
        await msg.edit_text(times_text(), parse_mode=HTML, reply_markup=_home_kb())
    elif data == "set:update":
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes, restart", callback_data="set:update_go"),
                                    InlineKeyboardButton("Cancel", callback_data="menu:settings")]])
        await msg.edit_text("Restart the bot and pull the latest code from GitHub?", reply_markup=kb)
    elif data == "set:update_go":
        await _restart(msg)
    elif data == "per:show":
        extra = persona.get_extra()
        await msg.reply_text(extra or "You haven't added any extra lines yet.")
    elif data == "per:clear":
        persona.clear_extra()
        await msg.edit_text(persona_text(), parse_mode=HTML, reply_markup=persona_kb())
    elif data == "tr:refresh":
        await msg.edit_text("🔎 asking Gemini to search...", reply_markup=_home_kb())
        ok, text = await asyncio.to_thread(trends.refresh)
        await msg.edit_text(trends_text() if ok else html.escape(text), parse_mode=HTML, reply_markup=trends_kb())


# ------------------------------------------------------------------ scheduling
async def daily_job(context: ContextTypes.DEFAULT_TYPE):
    await _send_package(context.bot, context.job.chat_id, None, context.job_queue)


async def catch_up_job(context: ContextTypes.DEFAULT_TYPE):
    """After a restart past today's drop time with no plan yet, send it now."""
    parsed = parse_hhmm(store.get_run_time())
    now = datetime.now(ZoneInfo(config.BOT_TZ))
    if parsed and not store.has_package(store.today()) and (now.hour, now.minute) >= parsed:
        log.info("Today's plan missing after restart; sending now")
        await _send_package(context.bot, context.job.chat_id, None, context.job_queue)


def schedule_daily(application: Application) -> None:
    jq = application.job_queue
    for job in jq.get_jobs_by_name("daily"):
        job.schedule_removal()
    hh, mm = parse_hhmm(store.get_run_time()) or parse_hhmm(config.RUN_TIME) or (6, 0)
    jq.run_daily(daily_job, time=dtime(hh, mm, tzinfo=ZoneInfo(config.BOT_TZ)),
                 name="daily", chat_id=config.OWNER_ID)
    log.info("Daily drop scheduled for %02d:%02d %s", hh, mm, config.BOT_TZ)


async def reminder_job(context: ContextTypes.DEFAULT_TYPE):
    """Fires a saved reminder: 'post it now' at a post's time, or 'log results' 48h after you posted."""
    row = context.job.data
    reminders.remove(row["id"])
    post = store.get_post(row["post_id"])
    if not (store.reminders_enabled() and post):
        return
    hook = html.escape(_hook(post))
    if row["kind"] == "post":
        await context.bot.send_message(
            context.job.chat_id, f"⏰ <b>Time to post</b> ({html.escape(post['post_time']['label'])})\n\n“{hook}”",
            parse_mode=HTML, reply_markup=reminder_post_kb(row["post_id"]))
    else:
        await context.bot.send_message(
            context.job.chat_id, f"📊 <b>Time to log results</b> (about 48h since you posted)\n\n“{hook}”",
            parse_mode=HTML, reply_markup=reminder_log_kb(row["post_id"]))


def restore_reminders(application: Application) -> None:
    """Re-schedule saved reminders after a restart. Late log reminders still fire; stale post ones are dropped."""
    now = reminders.now()
    for row in reminders.all_pending():
        when = datetime.fromisoformat(row["when"])
        if when <= now:
            if row["kind"] == "log" and now - when < timedelta(hours=24):
                row = dict(row, when=(now + timedelta(seconds=20)).isoformat())
            else:
                reminders.remove(row["id"])
                continue
        _schedule(application.job_queue, row)


async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled error", exc_info=context.error)


async def post_init(application: Application) -> None:
    try:
        await application.bot.set_my_commands([
            BotCommand("menu", "Open the menu"), BotCommand("post", "New post (add an idea if you want)"),
            BotCommand("daily", "Today's plan"), BotCommand("week", "Plan the whole week"),
            BotCommand("mine", "Post your own quote, sound, clip"), BotCommand("persona", "Teach the bot about you"),
            BotCommand("trends", "Sounds and hashtags trending"), BotCommand("besttimes", "Set best post times"),
            BotCommand("settime", "Set the daily drop time"), BotCommand("update", "Pull latest code"),
        ])
    except Exception:  # noqa: BLE001 - cosmetic only
        log.warning("Could not set command menu")


# ------------------------------------------------------------------ entry
def run_bot() -> None:
    config.setup_logging()
    if not config.TELEGRAM_BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN is not set. Get one from @BotFather.")
        sys.exit(1)

    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    for name, fn in [("start", cmd_start), ("myid", cmd_myid), ("menu", cmd_menu), ("post", cmd_post),
                     ("daily", cmd_daily), ("week", cmd_week), ("mine", cmd_mine),
                     ("persona", cmd_persona), ("trends", cmd_trends),
                     ("besttimes", cmd_besttimes), ("settime", cmd_settime), ("update", cmd_update)]:
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.ANIMATION | filters.Document.IMAGE
                                   | filters.Document.VIDEO, on_media))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)

    app.job_queue.run_once(update_done_job, when=3)  # tells you if a /update just finished
    if config.OWNER_ID:
        schedule_daily(app)
        restore_reminders(app)
        app.job_queue.run_once(catch_up_job, when=10, chat_id=config.OWNER_ID)
    else:
        log.warning("TELEGRAM_OWNER_ID not set. Message the bot /start to get your ID, then set it.")

    log.info("Bot starting | gemini key: %s | tz: %s", bool(config.GEMINI_API_KEY), config.BOT_TZ)
    app.run_polling(drop_pending_updates=True)
