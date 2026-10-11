"""Reminders: post each planned post at its time, and log results 48h after you post.

Kept on disk so a restart doesn't lose them. bot.py does the actual scheduling.
"""
import json
import threading
import uuid
from datetime import datetime, timedelta
from typing import List, Optional
from zoneinfo import ZoneInfo

from . import config

LOG_DELAY_HOURS = 48
_lock = threading.Lock()


def _path():
    return config.DATA_DIR / "reminders.json"


def _read() -> List[dict]:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def _write(rows: List[dict]) -> None:
    config.ensure_dirs()
    _path().write_text(json.dumps(rows), encoding="utf-8")


def now() -> datetime:
    try:
        return datetime.now(ZoneInfo(config.BOT_TZ))
    except Exception:  # noqa: BLE001 - bad tz name or missing tzdata
        return datetime.now().astimezone()


def add(kind: str, post_id: str, when: datetime) -> dict:
    """Save a reminder ('post' or 'log'). One per kind+post: adding again replaces the old one."""
    with _lock:
        rows = [r for r in _read() if not (r["kind"] == kind and r["post_id"] == post_id)]
        row = {"id": uuid.uuid4().hex[:8], "kind": kind, "post_id": post_id, "when": when.isoformat()}
        rows.append(row)
        _write(rows)
        return row


def remove(rid: str) -> None:
    with _lock:
        _write([r for r in _read() if r["id"] != rid])


def all_pending() -> List[dict]:
    return _read()


def when_today(post: dict, current: Optional[datetime] = None) -> Optional[datetime]:
    """Today's clock time for a post, or None if that time has already passed."""
    hh, mm = (int(x) for x in post["post_time"]["time"].split(":"))
    current = current or now()
    when = current.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return when if when > current + timedelta(minutes=1) else None


def log_time(current: Optional[datetime] = None) -> datetime:
    return (current or now()) + timedelta(hours=LOG_DELAY_HOURS)
