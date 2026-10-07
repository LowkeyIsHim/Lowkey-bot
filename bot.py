"""Telegram layer. All generation runs in a worker thread so the bot never blocks on Gemini."""
import asyncio
import functools
import html
import logging
import os
import signal
import sys
from datetime import datetime, time as dtime
from typing import Optional, Tuple
from zoneinfo import ZoneInfo

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from . import config, engine, quotes, store

log = logging.getLogger("bot")

HELP = (
    "Commands\n"
    "/post  pick a pillar, get one post\n"
    "/post alone  or d / n / s / a, optional format: single, split, interview\n"
    "/daily  full package now (default 3 posts)\n"
    "/settime 06:30  change the daily drop time\n"
    "/ai on|off  switch Gemini on or off (off = local bank)\n"
    "/status  what the bot is doing\n"
    "/update  restart and pull the latest code from GitHub\n"
    "/myid  your Telegram ID"
)


# ------------------------------------------------------------------ helpers
def parse_pillar(token: Optional[str]) -> Optional[str]:
    """'alone', 'a', 'def', 'noexp' ... -> pillar key. None means random."""
    if not token or token.lower() in ("any", "random", "r"):
        return None
    t = token.lower().replace("-", "_")
    for key in config.PILLARS:
        if key.startswith(t) or t.startswith(key):
            return key
    return None


def parse_format(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    t = token.lower()
    for f in config.FORMAT_WEIGHTS:
        if f.startswith(t):
            return f
    return None


def parse_hhmm(text: str) -> Optional[Tuple[int, int]]:
    try:
        hh, mm = text.strip().split(":")
        hh, mm = int(hh), int(mm)
    except ValueError:
        return None
    return (hh, mm) if 0 <= hh < 24 and 0 <= mm < 60 else None


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


def _pillar_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎲 Random", callback_data="gen:any")],
        [InlineKeyboardButton("Defense", callback_data="gen:defense"),
         InlineKeyboardButton("No Explanations", callback_data="gen:no_explanations")],
        [InlineKeyboardButton("Silence", callback_data="gen:silence"),
         InlineKeyboardButton("Alone", callback_data="gen:alone")],
    ])


def _redo_keyboard(pillar: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("🔄 Another", callback_data=f"gen:{pillar}"),
        InlineKeyboardButton("🎲 Random", callback_data="gen:any"),
    ]])


async def _send_post(message, pillar: Optional[str], fmt: Optional[str] = None) -> None:
    wait = await message.reply_text("⏳ cooking...")
    try:
        post = await asyncio.to_thread(engine.build_post, pillar, fmt)
    except Exception:  # noqa: BLE001
        log.exception("build_post failed")
        await wait.edit_text("Something broke while generating. Check the logs.")
        return
    await wait.edit_text(engine.render_post(post, html=True), parse_mode=ParseMode.HTML,
                         reply_markup=_redo_keyboard(post["pillar"]))


async def _send_package(bot, chat_id: int, count: Optional[int] = None) -> None:
    pkg = await asyncio.to_thread(engine.generate_daily, count)
    msgs = engine.render_package(pkg, html=True)
    await bot.send_message(chat_id, html.escape(msgs[0], quote=False), parse_mode=ParseMode.HTML)
    for post, text in zip(pkg["posts"], msgs[1:]):
        await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML,
                               reply_markup=_redo_keyboard(post["pillar"]))


# ------------------------------------------------------------------ commands
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not config.OWNER_ID:
        await update.message.reply_text(
            f"Setup: your Telegram ID is {user.id}. Set TELEGRAM_OWNER_ID={user.id} and restart the bot.")
    elif user.id == config.OWNER_ID:
        await update.message.reply_text("Moving in silence ⚙️\n\n" + HELP)


async def cmd_myid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Your Telegram ID: {update.effective_user.id}")


@owner_only
async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(HELP)


@owner_only
async def cmd_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    args = context.args or []
    if not args:
        await update.message.reply_text("Which pillar?", reply_markup=_pillar_keyboard())
        return
    pillar, fmt = parse_pillar(args[0]), parse_format(args[1] if len(args) > 1 else None)
    await _send_post(update.message, pillar, fmt)


@owner_only
async def cmd_daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    count = None
    if context.args and context.args[0].isdigit():
        count = max(1, min(int(context.args[0]), 8))
    await update.message.reply_text("⏳ building the package...")
    await _send_package(context.bot, update.effective_chat.id, count)


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
async def cmd_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    arg = (context.args[0].lower() if context.args else "")
    if arg in ("on", "off"):
        store.set_ai(arg == "on")
    key = "yes" if config.GEMINI_API_KEY else "NO (add GEMINI_API_KEY)"
    await update.message.reply_text(f"Gemini: {'on' if store.ai_enabled() else 'off'} | key set: {key}")


@owner_only
async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    day = store.today()
    await update.message.reply_text(
        f"Gemini: {'on' if store.ai_enabled() and config.GEMINI_API_KEY else 'off (local bank)'}\n"
        f"Daily drop: {store.get_run_time()} ({config.BOT_TZ})\n"
        f"Today's package: {store.posts_today(day)} posts\n"
        f"Quotes used (last {config.NO_REPEAT_DAYS} days): {quotes.used_count()}")


@owner_only
async def cmd_update(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Exit cleanly; the app.py launcher re-pulls the repo and starts the bot again."""
    await update.message.reply_text("Restarting to pull the latest code. Back in a minute.")
    os.kill(os.getpid(), signal.SIGTERM)


@owner_only
async def on_generate_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await _send_post(query.message, parse_pillar(query.data.split(":", 1)[1]))


# ------------------------------------------------------------------ scheduling
async def daily_job(context: ContextTypes.DEFAULT_TYPE):
    await _send_package(context.bot, context.job.chat_id)


async def catch_up_job(context: ContextTypes.DEFAULT_TYPE):
    """After a restart past today's drop time with no package yet, send it now."""
    parsed = parse_hhmm(store.get_run_time())
    now = datetime.now(ZoneInfo(config.BOT_TZ))
    if parsed and not store.has_package(store.today()) and (now.hour, now.minute) >= parsed:
        log.info("Today's package missing after restart; sending now")
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
            BotCommand("post", "One post (pick a pillar)"), BotCommand("daily", "Full package now"),
            BotCommand("settime", "Change daily drop time"), BotCommand("ai", "Gemini on/off"),
            BotCommand("status", "Bot status"), BotCommand("update", "Pull latest code"),
            BotCommand("help", "Commands"),
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
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("myid", cmd_myid))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("post", cmd_post))
    app.add_handler(CommandHandler("daily", cmd_daily))
    app.add_handler(CommandHandler("settime", cmd_settime))
    app.add_handler(CommandHandler("ai", cmd_ai))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("update", cmd_update))
    app.add_handler(CallbackQueryHandler(on_generate_button, pattern=r"^gen:"))
    app.add_error_handler(on_error)

    if config.OWNER_ID:
        schedule_daily(app)
        app.job_queue.run_once(catch_up_job, when=10, chat_id=config.OWNER_ID)
    else:
        log.warning("TELEGRAM_OWNER_ID not set. Message the bot /start to get your ID, then set it.")

    log.info("Bot starting | gemini key: %s | tz: %s", bool(config.GEMINI_API_KEY), config.BOT_TZ)
    app.run_polling(drop_pending_updates=True)
