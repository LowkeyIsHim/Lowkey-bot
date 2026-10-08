"""Telegram layer: start menu, buttons, daily plan. Generation runs in worker threads so the bot
never blocks while Gemini thinks."""
import asyncio
import functools
import html
import logging
import os
import signal
import sys
from datetime import datetime, time as dtime
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

from . import brain, capcut, config, engine, persona, quotes, store, timing, trends

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


def _ai_state() -> str:
    if not config.GEMINI_API_KEY:
        return "OFF: GEMINI_API_KEY is missing on the server (using pre-written lines)"
    if not store.ai_enabled():
        return "OFF: switched off in Settings (using pre-written lines)"
    return "ON"


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
    state = "🟢 Gemini on" if _ai_on() else "🔴 Gemini off (pre-written lines)"
    return (
        "<b>⚙️ MOVING IN SILENCE</b>\n"
        "<i>@im_just_lowkey · Lowkey He's Him</i>\n"
        "━━━━━━━━━━━━━━━\n"
        "✨ <b>New post</b>  Gemini decides everything\n"
        "📅 <b>Today's plan</b>  timed posts for the day\n"
        "🧠 <b>Persona</b>  teach it more about you\n"
        "📈 <b>Trends</b>  sounds and hashtags going around\n"
        "⚙️ <b>Settings</b>  status, times, update\n"
        "━━━━━━━━━━━━━━━\n"
        f"{state}  ·  daily drop {html.escape(store.get_run_time())}\n\n"
        "<i>Or type an idea, or paste a YouTube link, and I'll build the post around it.</i>"
    )


def menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✨ New post", callback_data="new"),
         InlineKeyboardButton("📅 Today's plan", callback_data="plan")],
        [InlineKeyboardButton("🧠 Persona", callback_data="menu:persona"),
         InlineKeyboardButton("📈 Trends", callback_data="menu:trends")],
        [InlineKeyboardButton("⚙️ Settings", callback_data="menu:settings")],
    ])


def settings_kb() -> InlineKeyboardMarkup:
    ai = "🤖 Turn Gemini off" if store.ai_enabled() else "🤖 Turn Gemini on"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📊 Status", callback_data="set:status"),
         InlineKeyboardButton(ai, callback_data="set:ai")],
        [InlineKeyboardButton("🕕 Daily drop time", callback_data="set:time"),
         InlineKeyboardButton("⏰ Best post times", callback_data="set:times")],
        [InlineKeyboardButton("🔄 Update code", callback_data="set:update"),
         InlineKeyboardButton("🏠 Menu", callback_data="menu:home")],
    ])


def post_kb(post_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 CapCut steps", callback_data=f"cc:{post_id}")],
        [InlineKeyboardButton("🔄 Another", callback_data="new"),
         InlineKeyboardButton("🏠 Menu", callback_data="menu:show")],
    ])


def _home_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Menu", callback_data="menu:home")]])


def settings_text() -> str:
    return (
        "<b>⚙️ Settings</b>\n\n"
        f"Gemini: {html.escape(_ai_state())}\n"
        f"Daily drop: {html.escape(store.get_run_time())} ({html.escape(config.BOT_TZ)})\n"
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
        recent = await asyncio.to_thread(store.recent_posts, 3)
        post = await asyncio.to_thread(engine.build_post, recent, brief, link)
        post_id = store.remember_post(post)
    except Exception:  # noqa: BLE001
        log.exception("build_post failed")
        await wait.edit_text("Something broke while generating. Check the logs.")
        return
    await wait.edit_text(engine.render_post(post, html=True), parse_mode=HTML,
                         reply_markup=post_kb(post_id), **NOPREVIEW)


async def _send_package(bot, chat_id: int, count: Optional[int] = None) -> None:
    await asyncio.to_thread(trends.refresh_if_stale)
    pkg = await asyncio.to_thread(engine.generate_daily, count)
    await bot.send_message(chat_id, "<b>" + engine.render_header(pkg, html=True).replace("\n", "</b>\n", 1),
                           parse_mode=HTML)
    for post in pkg["posts"]:
        await bot.send_message(chat_id, engine.render_post(post, html=True), parse_mode=HTML,
                               reply_markup=post_kb(store.remember_post(post)), **NOPREVIEW)


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
    await update.message.reply_text(menu_text(), parse_mode=HTML, reply_markup=menu_kb())


@owner_only
async def cmd_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    brief, link = split_idea(" ".join(context.args or []))
    await _send_post(update.message, brief, link)


@owner_only
async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Any plain message is an idea, or a YouTube link to build a post around."""
    if update.message and update.message.text:
        brief, link = split_idea(update.message.text)
        await _send_post(update.message, brief, link)


@owner_only
async def cmd_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = None
    if context.args and context.args[0].isdigit():
        count = max(1, min(int(context.args[0]), 6))
    await update.message.reply_text("⏳ building today's plan...")
    await _send_package(context.bot, update.effective_chat.id, count)


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


async def _restart(message) -> None:
    """Exit cleanly; the app.py launcher re-pulls the repo and starts the bot again."""
    await message.reply_text("Restarting to pull the latest code. Back in a minute.")
    os.kill(os.getpid(), signal.SIGTERM)


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

    await query.answer()
    if data == "new":
        await _send_post(msg)
    elif data == "plan":
        await msg.reply_text("⏳ building today's plan...")
        await _send_package(context.bot, msg.chat_id)
    elif data == "menu:show":
        await msg.reply_text(menu_text(), parse_mode=HTML, reply_markup=menu_kb())
    elif data == "menu:home":
        await msg.edit_text(menu_text(), parse_mode=HTML, reply_markup=menu_kb())
    elif data == "menu:settings":
        await msg.edit_text(settings_text(), parse_mode=HTML, reply_markup=settings_kb())
    elif data == "menu:persona":
        await msg.edit_text(persona_text(), parse_mode=HTML, reply_markup=persona_kb())
    elif data == "menu:trends":
        await msg.edit_text(trends_text(), parse_mode=HTML, reply_markup=trends_kb())
    elif data == "set:status":
        await msg.edit_text(settings_text(), parse_mode=HTML, reply_markup=settings_kb())
    elif data == "set:ai":
        store.set_ai(not store.ai_enabled())
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
    await _send_package(context.bot, context.job.chat_id)


async def catch_up_job(context: ContextTypes.DEFAULT_TYPE):
    """After a restart past today's drop time with no plan yet, send it now."""
    parsed = parse_hhmm(store.get_run_time())
    now = datetime.now(ZoneInfo(config.BOT_TZ))
    if parsed and not store.has_package(store.today()) and (now.hour, now.minute) >= parsed:
        log.info("Today's plan missing after restart; sending now")
        await _send_package(context.bot, context.job.chat_id)


def schedule_daily(application: Application) -> None:
    jq = application.job_queue
    for job in jq.get_jobs_by_name("daily"):
        job.schedule_removal()
    hh, mm = parse_hhmm(store.get_run_time()) or parse_hhmm(config.RUN_TIME) or (6, 0)
    jq.run_daily(daily_job, time=dtime(hh, mm, tzinfo=ZoneInfo(config.BOT_TZ)),
                 name="daily", chat_id=config.OWNER_ID)
    log.info("Daily drop scheduled for %02d:%02d %s", hh, mm, config.BOT_TZ)


async def on_error(update, context: ContextTypes.DEFAULT_TYPE):
    log.error("Unhandled error", exc_info=context.error)


async def post_init(application: Application) -> None:
    try:
        await application.bot.set_my_commands([
            BotCommand("menu", "Open the menu"), BotCommand("post", "New post (add an idea if you want)"),
            BotCommand("daily", "Today's plan"), BotCommand("persona", "Teach the bot about you"),
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
                     ("daily", cmd_daily), ("persona", cmd_persona), ("trends", cmd_trends),
                     ("besttimes", cmd_besttimes), ("settime", cmd_settime), ("update", cmd_update)]:
        app.add_handler(CommandHandler(name, fn))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_error)

    if config.OWNER_ID:
        schedule_daily(app)
        app.job_queue.run_once(catch_up_job, when=10, chat_id=config.OWNER_ID)
    else:
        log.warning("TELEGRAM_OWNER_ID not set. Message the bot /start to get your ID, then set it.")

    log.info("Bot starting | gemini key: %s | tz: %s", bool(config.GEMINI_API_KEY), config.BOT_TZ)
    app.run_polling(drop_pending_updates=True)
