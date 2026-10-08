"""Trend notes for sounds and hashtags. Gemini can search the web for them, or you paste your own.

Gemini's search is best effort: always check that a sound really exists on TikTok before using it.
"""
import logging
import time
from typing import Optional, Tuple

from . import config, store

log = logging.getLogger("trends")
MAX_AGE_DAYS = 7
MAX_CHARS = 1500

PROMPT = """Search the web for what is trending right now on TikTok for dark, stoic, lone-wolf, motivational edit pages
(Peaky Blinders, The Batman, Drive style edits, interview-clip pages). Reply in plain text, under 1200 characters:
SOUNDS: up to 8 trending or rising sounds (title - artist).
HASHTAGS: up to 10 trending hashtags relevant to this niche.
FORMATS: up to 3 formats or edit styles working this week.
Only include things you found evidence for. If you find little, say so."""


def _path():
    return config.DATA_DIR / "trends.txt"


def age_hours() -> Optional[float]:
    try:
        return (time.time() - _path().stat().st_mtime) / 3600
    except OSError:
        return None


def get() -> str:
    """Notes if they are fresh (under 7 days), else empty."""
    age = age_hours()
    if age is None or age > MAX_AGE_DAYS * 24:
        return ""
    try:
        return _path().read_text(encoding="utf-8").strip()[:MAX_CHARS]
    except OSError:
        return ""


def set_manual(text: str) -> None:
    config.ensure_dirs()
    _path().write_text(text.strip()[:MAX_CHARS], encoding="utf-8")


def refresh() -> Tuple[bool, str]:
    """Ask Gemini (with Google Search) for current trends. Returns (ok, message)."""
    if not (config.GEMINI_API_KEY and store.ai_enabled()):
        return False, "Gemini is off, so I can't search. Paste trends yourself with /trends <text>."
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=config.GEMINI_API_KEY)
        resp = client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=PROMPT,
            config=types.GenerateContentConfig(tools=[types.Tool(google_search=types.GoogleSearch())],
                                               temperature=0.3),
        )
        text = (resp.text or "").strip()
        if not text:
            return False, "Gemini found nothing useful. Try again later or paste trends yourself."
        set_manual(text)
        return True, "Trend notes updated."
    except Exception as exc:  # noqa: BLE001
        log.warning("Trend refresh failed: %s", str(exc)[:200])
        return False, "Couldn't refresh trends right now. Paste them yourself with /trends <text>."


def refresh_if_stale(hours: int = 24) -> None:
    """Best effort, used before the daily package. Never raises."""
    age = age_hours()
    if age is None or age > hours:
        try:
            refresh()
        except Exception:  # noqa: BLE001
            pass
