"""Builds posts and daily packages, and renders them as text/HTML. No Telegram code in here."""
import html as _html
import random
from datetime import date
from typing import Dict, List, Optional

from . import captions, config, quotes, store, visuals


# ------------------------------------------------------------------ picking
def pick_pillars(count: int, last: Optional[str], rng: random.Random) -> List[str]:
    """Rotate pillars: never the same twice in a row, spread evenly."""
    seq: List[str] = []
    prev = last
    for _ in range(count):
        options = [p for p in config.PILLARS if p != prev]
        fewest = min(seq.count(p) for p in options)
        prev = rng.choice([p for p in options if seq.count(p) == fewest])
        seq.append(prev)
    return seq


def pick_format(rng: random.Random, allow_interview: bool = True) -> str:
    weights = dict(config.FORMAT_WEIGHTS)
    if not allow_interview:
        weights.pop("interview", None)
    return rng.choices(list(weights), weights=list(weights.values()))[0]


# ------------------------------------------------------------------ building
def build_post(pillar: Optional[str] = None, fmt: Optional[str] = None,
               rng: Optional[random.Random] = None, number: int = 1) -> Dict[str, object]:
    """One complete post: text, caption, hashtags, clip and sound direction."""
    rng = rng or random.Random()
    pillar = pillar or rng.choice(list(config.PILLARS))
    fmt = fmt or pick_format(rng)
    q = quotes.get_quote(pillar, fmt, rng)
    vis = visuals.build_visual(q, rng)
    cap = captions.format_caption(q, vis["character_tags"], rng)
    return {
        "post_number": number,
        "pillar": pillar,
        "format": q.fmt,
        "quote_source": q.source,
        "on_screen_text": captions.overlay_slides(q),
        "clip_topic": q.clip_topic,
        **cap,
        "visual": vis,
    }


def build_package(day: date, count: int, only_pillar: Optional[str] = None) -> Dict[str, object]:
    rng = random.Random()
    pillars = ([only_pillar] * count if only_pillar
               else pick_pillars(count, store.last_pillar_before(day), rng))
    posts, interview_done = [], False
    for i, pillar in enumerate(pillars, 1):
        fmt = pick_format(rng, allow_interview=not interview_done)  # max one interview post per day
        interview_done = interview_done or fmt == "interview"
        posts.append(build_post(pillar, fmt, rng, number=i))
    return {"page": config.PAGE_HANDLE, "date": day.isoformat(), "posts": posts}


def generate_daily(count: Optional[int] = None, only_pillar: Optional[str] = None) -> Dict[str, object]:
    """Build today's package and save it (json + txt) to the data dir."""
    pkg = build_package(store.today(), count or config.POSTS_PER_DAY, only_pillar)
    store.save_package(pkg, "\n\n".join(render_package(pkg)))
    return pkg


# ------------------------------------------------------------------ rendering
def render_post(p: Dict[str, object], html: bool = False) -> str:
    """Phone-friendly text. With html=True, copyable parts are <pre> blocks (tap to copy in Telegram)."""
    esc = (lambda s: _html.escape(s, quote=False)) if html else (lambda s: s)

    def blk(s: str) -> str:
        return f"<pre>{esc(s)}</pre>" if html else s

    def bold(s: str) -> str:
        return f"<b>{esc(s)}</b>" if html else s

    v, slides = p["visual"], p["on_screen_text"]
    out = [bold(f"POST {p['post_number']} | {config.PILLAR_LABELS[p['pillar']]} | {p['format']} | {v['duration_seconds']}s")]
    if p["format"] == "interview":
        out += ["HOOK TEXT:", blk(slides[0]), esc(f"Clip topic: {p['clip_topic']}")]
    elif len(slides) == 2:
        out += ["ON SCREEN, beat 1:", blk(slides[0]), "ON SCREEN, beat 2:", blk(slides[1])]
    else:
        out += ["ON SCREEN:", blk(slides[0])]
    out += ["", "CAPTION:", blk(p["post_caption"]), "",
            esc(f"CLIP: {v['clip']}"),
            esc(f"SEARCH: {' / '.join(v['search_keywords'])}"),
            esc(f"FORMAT: {v['delivery']}"),
            esc(f"LOOK: {v['color_grade']}, {v['overlay_fx']}"),
            esc(f"SOUND: {v['audio']}"),
            esc(f"NOTE: {v['edit_notes'][0]}")]
    return "\n".join(out)


def render_package(pkg: Dict[str, object], html: bool = False) -> List[str]:
    """[header, post1, post2, ...] as separate messages."""
    return [f"{pkg['page']} | {pkg['date']}"] + [render_post(p, html) for p in pkg["posts"]]
