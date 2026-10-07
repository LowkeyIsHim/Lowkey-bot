"""Small JSON-backed state: runtime settings and saved daily packages."""
import json
import logging
import threading
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from . import config

log = logging.getLogger("store")
_lock = threading.Lock()


def today() -> date:
    """Today's date in BOT_TZ (so file names and the schedule agree regardless of server time)."""
    try:
        return datetime.now(ZoneInfo(config.BOT_TZ)).date()
    except Exception:  # noqa: BLE001 - bad tz name or missing tzdata
        return date.today()


# ------------------------------------------------------------------ settings
def _read() -> dict:
    try:
        return json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _update(**kw) -> None:
    with _lock:
        data = _read()
        data.update(kw)
        config.ensure_dirs()
        config.SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_run_time() -> str:
    return _read().get("run_time") or config.RUN_TIME


def set_run_time(hhmm: str) -> None:
    _update(run_time=hhmm)


def ai_enabled() -> bool:
    return bool(_read().get("ai", True))


def set_ai(flag: bool) -> None:
    _update(ai=flag)


# ------------------------------------------------------------------ packages
def package_path(day: date) -> Path:
    return config.OUTPUT_DIR / f"{day.isoformat()}.json"


def has_package(day: date) -> bool:
    return package_path(day).exists()


def save_package(pkg: dict, text: str) -> None:
    config.ensure_dirs()
    path = package_path(date.fromisoformat(pkg["date"]))
    path.write_text(json.dumps(pkg, indent=2, ensure_ascii=False), encoding="utf-8")
    path.with_suffix(".txt").write_text(text, encoding="utf-8")


def last_pillar_before(day: date) -> Optional[str]:
    """Pillar of the last post from an earlier day, so a new day never starts with a repeat."""
    files = sorted(p for p in config.OUTPUT_DIR.glob("*.json") if p.stem < day.isoformat())
    if not files:
        return None
    try:
        return json.loads(files[-1].read_text(encoding="utf-8"))["posts"][-1]["pillar"]
    except (OSError, KeyError, IndexError, json.JSONDecodeError):
        return None


def posts_today(day: date) -> int:
    try:
        return len(json.loads(package_path(day).read_text(encoding="utf-8"))["posts"])
    except (OSError, KeyError, json.JSONDecodeError):
        return 0
