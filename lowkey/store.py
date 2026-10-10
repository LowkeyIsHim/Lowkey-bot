"""Small JSON-backed state: runtime settings, saved daily packages, recent posts."""
import json
import logging
import threading
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional
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
def read_settings() -> dict:
    try:
        return json.loads(config.SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def update_settings(**kw) -> None:
    with _lock:
        data = read_settings()
        data.update(kw)
        config.ensure_dirs()
        config.SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_run_time() -> str:
    return read_settings().get("run_time") or config.RUN_TIME


def set_run_time(hhmm: str) -> None:
    update_settings(run_time=hhmm)


def ai_enabled() -> bool:
    return bool(read_settings().get("ai", True))


def set_ai(flag: bool) -> None:
    update_settings(ai=flag)


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


# ------------------------------------------------------------------ recent posts (buttons + variety)
def _recent_path() -> Path:
    return config.DATA_DIR / "recent_posts.json"


def _read_recent() -> dict:
    try:
        return json.loads(_recent_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def remember_post(post: dict) -> str:
    """Keep the last 60 posts so buttons still work after a restart. Returns a short id."""
    import uuid
    pid = uuid.uuid4().hex[:6]
    with _lock:
        rows = _read_recent()
        rows[pid] = post
        rows = dict(list(rows.items())[-60:])
        config.ensure_dirs()
        _recent_path().write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return pid


def get_post(pid: str) -> Optional[dict]:
    return _read_recent().get(pid)


def recent_posts(n: int = 3) -> List[dict]:
    return list(_read_recent().values())[-n:]


# ------------------------------------------------------------------ results (so the bot learns what works)
def _results_path() -> Path:
    return config.DATA_DIR / "results.json"


def read_results() -> dict:
    try:
        return json.loads(_results_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_result(post_id: str, row: dict) -> None:
    with _lock:
        rows = read_results()
        rows[post_id] = row
        config.ensure_dirs()
        _results_path().write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
