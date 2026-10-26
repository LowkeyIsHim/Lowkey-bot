"""Your own post: read what you typed (quote, hashtags, sound, clip, caption, time) and keep it exactly.

Gemini only fills in what you left out. Also compares your own posts with Gemini's, from logged results.
"""
import re
from typing import Dict, List, Optional, Tuple

from . import store, timing, visuals

YT_RE = re.compile(r"https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?[^\s]*v=|shorts/)|youtu\.be/)[\w\-]{6,}[^\s]*")

_KEYS = {"quote": "quote", "line": "quote", "text": "quote", "words": "quote", "hook": "quote",
         "sound": "sound", "song": "sound", "audio": "sound", "music": "sound",
         "clip": "clip", "scene": "clip", "video": "clip", "footage": "clip",
         "tags": "tags", "hashtags": "tags", "hashtag": "tags",
         "caption": "caption", "cap": "caption", "time": "time"}
_LABEL = re.compile(r"^\s*([A-Za-z]+)\s*[:=]\s*(.+?)\s*$")
_TAG = re.compile(r"#[A-Za-z0-9_]{2,30}")
_SPLIT = re.compile(r"\s*\|\|\s*|\s+/\s+")


def parse_time(text: str) -> str:
    """'8:30pm', '8pm', '20:30' -> '20:30'. A bare number like '8' is ambiguous, so it returns ''."""
    m = re.search(r"(\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?", text.strip(), re.I)
    if not m or (not m.group(2) and not m.group(3)):
        return ""
    hh, mm, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "").lower()
    if ap == "pm" and hh < 12:
        hh += 12
    if ap == "am" and hh == 12:
        hh = 0
    return f"{hh:02d}:{mm:02d}" if hh < 24 and mm < 60 else ""


def parse_own(text: str) -> Dict[str, object]:
    """Pull the owner's choices out of a message. Labels (quote:, sound:, clip:, tags:, caption:, time:) are
    optional: unlabelled text is the quote, and #hashtags are found anywhere."""
    text = text or ""
    link = ""
    m = YT_RE.search(text)
    if m:
        link = m.group(0)
        text = text.replace(link, " ")
    fields: Dict[str, str] = {}
    rest: List[str] = []
    for line in text.splitlines():
        lm = _LABEL.match(line)
        key = _KEYS.get(lm.group(1).lower()) if lm else None
        if key == "time" and not parse_time(lm.group(2)):
            key = None  # "Time heals nothing" is a quote, not a time
        if key:
            fields[key] = lm.group(2).strip()
        else:
            rest.append(line)
    for k in ("sound", "clip", "caption", "time", "quote"):
        if k in fields:
            fields[k] = " ".join(_TAG.sub(" ", fields[k]).split())  # a #hashtag at the end of a line isn't part of it
    quote = fields.get("quote") or " ".join(l.strip() for l in rest if l.strip())
    quote = " ".join(_TAG.sub(" ", quote).split()).strip('"\u201c\u201d ')
    tags_source = fields.get("tags", "") + " " + text
    tags: List[str] = []
    for t in _TAG.findall(tags_source):
        t = t.lower()
        if t not in tags:
            tags.append(t)
    parts = [p.strip() for p in _SPLIT.split(quote, maxsplit=1) if p.strip()] if quote else []
    if len(parts) > 2:
        parts = parts[:2]
    return {
        "parts": parts, "hashtags": tags[:10], "sound": " ".join(fields.get("sound", "").split())[:80],
        "clip": " ".join(fields.get("clip", "").split())[:140],
        "caption": " ".join(fields.get("caption", "").split())[:100],
        "time": parse_time(fields.get("time", "")), "link": link,
    }


def locked_summary(own: dict) -> List[str]:
    """The choices Gemini must keep, as readable lines for its prompt."""
    out = []
    if own.get("parts"):
        out.append("On-screen lines: " + " || ".join(own["parts"]) +
                   (" (two beats: the format is split)" if len(own["parts"]) == 2 else " (one block: the format is single)"))
    if own.get("hashtags"):
        out.append("Hashtags: " + " ".join(own["hashtags"]))
    if own.get("sound"):
        out.append("Sound: " + own["sound"])
    if own.get("clip"):
        out.append("Clip or scene: " + own["clip"])
    if own.get("link"):
        out.append("YouTube clip: " + own["link"])
    if own.get("caption"):
        out.append("Caption line: " + own["caption"])
    if own.get("time"):
        out.append("Post time: " + own["time"])
    return out


def apply_locks(post: Dict[str, object], own: dict) -> Dict[str, object]:
    """Force the owner's choices onto the finished post, whatever Gemini returned."""
    v = post["visual"]
    if own.get("hashtags"):
        post["hashtags"] = list(own["hashtags"])
    if own.get("caption"):
        post["caption_line"] = own["caption"]
    post["post_caption"] = f"{post['caption_line']}\n\n{' '.join(post['hashtags'])}"
    if own.get("sound") and post["format"] != "interview":
        v["audio"], v["sound_title"], v["sound_why"] = own["sound"], own["sound"], "your pick"
    if not post.get("attached"):
        if own.get("clip"):
            v["clip"], v["clip_type"], v["clip_moment"] = f"Your pick: {own['clip']}", "own_pick", ""
            v["search_keywords"] = [own["clip"]]
            v["links"] = visuals.search_links([own["clip"]], own.get("link", ""))
        if own.get("link"):
            v["source_link"] = own["link"]
            v["links"] = visuals.search_links(v.get("search_keywords") or [own.get("clip", "")], own["link"])
    if own.get("time"):
        post["post_time"] = timing.post_time_at(own["time"])
    post["quote_source"] = "mine"
    return post


# ------------------------------------------------------------------ own posts vs Gemini's posts
_AUTHOR = {"gemini": "Gemini", "mine": "Your own", "bank": "Pre-written"}


def author_stats() -> Dict[str, Tuple[float, int]]:
    """Average views per author (Gemini, your own, pre-written) over the posts you logged."""
    groups: Dict[str, List[float]] = {}
    for pid, row in store.read_results().items():
        post = store.get_post(pid)
        who = (post or {}).get("quote_source") or "gemini"
        groups.setdefault(who, []).append(row["metrics"]["views"])
    return {k: (sum(v) / len(v), len(v)) for k, v in groups.items()}


def _fmt(n: float) -> str:
    return f"{n / 1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(int(n))


def author_breakdown() -> str:
    """Extra lines for the Results screen: do your own posts beat Gemini's? Empty until both exist."""
    stats = author_stats()
    if len(stats) < 2:
        return ""
    rows = sorted(stats.items(), key=lambda kv: kv[1][0], reverse=True)
    lines = [f"{_AUTHOR.get(k, k)}: {_fmt(avg)} ({n} post{'s' if n != 1 else ''})" for k, (avg, n) in rows]
    return "\n\nBy who made it (average views):\n" + "\n".join(lines)


def author_note() -> str:
    """A line for Gemini once you have logged enough of your own posts to compare."""
    stats = author_stats()
    mine, gem = stats.get("mine"), stats.get("gemini")
    if not (mine and gem and mine[1] >= 2 and gem[1] >= 2):
        return ""
    better = "better than" if mine[0] > gem[0] else "behind"
    return (f"HIS OWN POSTS average {_fmt(mine[0])} views ({mine[1]} posts), {better} yours at {_fmt(gem[0])} "
            f"({gem[1]} posts). Study what he picks himself (sounds, clips, hooks) and learn from it.")
