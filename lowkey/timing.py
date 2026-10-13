"""When to post. Gemini picks an exact time per post; the four bands below are only the fallback when Gemini is off.

Defaults come from the page's TikTok Analytics (Oct 2026: steady 11am-midnight, peak 7-10pm).
Re-check Analytics > Followers > Most active times now and then and update with /besttimes.
"""
import re
from datetime import datetime
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from . import config, store

BANDS = ("morning", "afternoon", "evening", "late_night")
BAND_LABELS = {"morning": "morning", "afternoon": "afternoon", "evening": "evening", "late_night": "late night"}
DEFAULT_TIMES = {"morning": "11:00", "afternoon": "15:00", "evening": "19:00", "late_night": "21:30"}
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


AUDIENCE = ("Followers (TikTok analytics, Oct 2026): about 61% male, 39% female. Active from late morning to "
            "midnight, peaking around 19:00-22:00 in the owner's local time. Only about a third of followers are "
            "online at the peak and most don't engage, so reaching NEW viewers on the For You page matters more "
            "than followers.")


def audience_summary() -> str:
    """What Gemini knows about when the audience is online (it picks the exact post time itself)."""
    t = band_times()
    return (f"{AUDIENCE}\nOwner's time zone: {config.BOT_TZ}. His preferred posting windows: morning {t['morning']}, "
            f"afternoon {t['afternoon']}, evening {t['evening']}, late night {t['late_night']}. Choose an exact "
            "time that fits the mood and the data, and keep posts in one day at least 90 minutes apart.")


def post_time(band: Optional[str]) -> Dict[str, str]:
    band = band if band in BANDS else "evening"
    hhmm = band_times()[band]
    return {"band": band, "time": hhmm, "label": _label(hhmm)}


def normalize_hhmm(text) -> Optional[str]:
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(text or ""))
    if not m:
        return None
    hh, mm = int(m.group(1)), int(m.group(2))
    return f"{hh:02d}:{mm:02d}" if hh < 24 and mm < 60 else None


def band_of(hhmm: str) -> str:
    hh = int(hhmm.split(":")[0])
    if 5 <= hh < 12:
        return "morning"
    if 12 <= hh < 17:
        return "afternoon"
    if 17 <= hh < 21:
        return "evening"
    return "late_night"


def post_time_at(hhmm: str) -> Dict[str, str]:
    """An exact time (HH:MM) with its band and a friendly label."""
    n = normalize_hhmm(hhmm) or DEFAULT_TIMES["evening"]
    return {"band": band_of(n), "time": n, "label": _label(n)}
