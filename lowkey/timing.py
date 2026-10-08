"""When to post. Four time bands; set your real peak times with /besttimes.

Defaults are starting guesses. Your real answer is in TikTok Analytics > Followers > Most active times.
"""
from datetime import datetime
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from . import config, store

BANDS = ("morning", "afternoon", "evening", "late_night")
BAND_LABELS = {"morning": "morning", "afternoon": "afternoon", "evening": "evening", "late_night": "late night"}
DEFAULT_TIMES = {"morning": "08:00", "afternoon": "13:00", "evening": "19:30", "late_night": "22:30"}
# Fallback mood-to-time mapping (Gemini picks its own band when it's on).
PILLAR_BAND = {"defense": "late_night", "alone": "late_night", "silence": "morning", "no_explanations": "evening"}


def _valid(hhmm: str) -> bool:
    try:
        hh, mm = hhmm.split(":")
        return 0 <= int(hh) < 24 and 0 <= int(mm) < 60
    except ValueError:
        return False


def band_times() -> Dict[str, str]:
    saved = store.read_settings().get("band_times") or {}
    return {b: saved.get(b) if _valid(saved.get(b, "")) else DEFAULT_TIMES[b] for b in BANDS}


def set_band_times(times: List[str]) -> bool:
    """Four HH:MM values: morning, afternoon, evening, late night."""
    if len(times) != 4 or not all(_valid(t) for t in times):
        return False
    store.update_settings(band_times={b: f"{int(t.split(':')[0]):02d}:{t.split(':')[1]}" for b, t in zip(BANDS, times)})
    return True


def _label(hhmm: str) -> str:
    hh, mm = (int(x) for x in hhmm.split(":"))
    try:
        tz = datetime.now(ZoneInfo(config.BOT_TZ)).tzname() or ""
    except Exception:  # noqa: BLE001
        tz = ""
    return f"{(hh % 12) or 12}:{mm:02d} {'AM' if hh < 12 else 'PM'} {tz}".strip()


def post_time(band: Optional[str]) -> Dict[str, str]:
    band = band if band in BANDS else "evening"
    hhmm = band_times()[band]
    return {"band": band, "time": hhmm, "label": _label(hhmm)}
