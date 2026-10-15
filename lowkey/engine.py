"""Builds posts and daily plans and renders them as text/HTML. No Telegram code in here.

Gemini decides everything when it's on (brain.py). Otherwise the local bank and libraries are used.
"""
import html as _html
import random
from datetime import date
from typing import Dict, List, Optional

from . import brain, captions, config, quotes, store, timing, visuals


# ------------------------------------------------------------------ fallback picking
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


def _fallback_post(rng: random.Random, recent: List[dict]) -> Dict[str, object]:
    taken = {r.get("pillar") for r in recent}
    last = recent[-1].get("pillar") if recent else None
    fresh = [p for p in config.PILLARS if p not in taken] or [p for p in config.PILLARS if p != last]
    pillar = rng.choice(fresh)
    fmt = pick_format(rng, allow_interview=not any(r.get("format") == "interview" for r in recent))
    q = quotes.get_quote(pillar, fmt, rng)
    vis = visuals.build_visual(q, rng)
    cap = captions.format_caption(q, vis["character_tags"], rng)
    return {
        "pillar": pillar, "format": q.fmt, "media": vis["media"], "quote_source": "bank",
        "on_screen_text": captions.overlay_slides(q), "clip_topic": q.clip_topic,
        **cap, "post_time": timing.post_time(timing.PILLAR_BAND[pillar]), "why": "", "visual": vis,
    }


# ------------------------------------------------------------------ building
def build_post(recent: Optional[List[dict]] = None, brief: str = "", link: str = "",
               number: int = 1, rng: Optional[random.Random] = None) -> Dict[str, object]:
    """One complete post. `brief` is an idea from you, `link` a YouTube clip to build around."""
    rng = rng or random.Random()
    recent = recent or []
    post = brain.generate_post(brief, link, recent)
    if post is None:
        post = _fallback_post(rng, recent)
        post["fallback_reason"] = brain.why_not()
    post["post_number"] = number
    return post


MIN_GAP_MIN = 90


def _spread_times(posts: List[dict]) -> None:
    """Keep posts at least 90 minutes apart (push later ones back), then refresh each post's time band."""
    last: Optional[int] = None
    for p in sorted(posts, key=lambda x: x["post_time"]["time"]):
        hh, mm = (int(x) for x in p["post_time"]["time"].split(":"))
        minutes = hh * 60 + mm
        if last is not None and minutes - last < MIN_GAP_MIN:
            minutes = min(last + MIN_GAP_MIN, 23 * 60 + 45)
        last = minutes
        p["post_time"] = timing.post_time_at(f"{minutes // 60:02d}:{minutes % 60:02d}")


def build_package(day: date, count: int) -> Dict[str, object]:
    last = store.last_pillar_before(day)
    recent: List[dict] = [{"pillar": last}] if last else []
    posts: List[dict] = []
    for _ in range(count):
        post = build_post(recent=recent)
        posts.append(post)
        recent.append(post)
    _spread_times(posts)
    posts.sort(key=lambda p: p["post_time"]["time"])  # in the order you should post them
    for i, p in enumerate(posts, 1):
        p["post_number"] = i
    return {"page": config.PAGE_HANDLE, "date": day.isoformat(), "posts": posts}


def generate_daily(count: Optional[int] = None) -> Dict[str, object]:
    """Build today's plan and save it (json + txt) to the data dir."""
    pkg = build_package(store.today(), count or config.POSTS_PER_DAY)
    store.save_package(pkg, "\n\n".join(render_package(pkg)))
    return pkg


# ------------------------------------------------------------------ rendering
def _media_label(p: Dict[str, object]) -> str:
    v = p["visual"]
    if p["media"] == "video":
        return f"video {v['duration_seconds']}s"
    return "photo post" if p["media"] == "photo" else "photo carousel"


def render_post(p: Dict[str, object], html: bool = False) -> str:
    """Phone-friendly text. With html=True, copyable parts are <pre> blocks (tap to copy in Telegram)."""
    esc = (lambda s: _html.escape(s, quote=False)) if html else (lambda s: s)

    def blk(s: str) -> str:
        return f"<pre>{esc(s)}</pre>" if html else s

    def bold(s: str) -> str:
        return f"<b>{esc(s)}</b>" if html else s

    def link(label: str, url: str) -> str:
        return f'<a href="{_html.escape(url, quote=True)}">{esc(label)}</a>' if html else f"{label}: {url}"

    v, slides, t = p["visual"], p["on_screen_text"], p["post_time"]
    tag = "" if p["quote_source"] == "gemini" else " | pre-written"
    out = [bold(f"POST {p['post_number']} | {config.PILLAR_LABELS[p['pillar']]} | {p['format']} | {_media_label(p)}{tag}"),
           esc(f"POST AT: {t['label']} ({timing.BAND_LABELS[t['band']]})")]
    if p.get("fallback_reason"):
        out.append(esc(f"⚠ Gemini didn't write this: {p['fallback_reason']}"))
    if p["format"] == "interview":
        out += ["", "HOOK TEXT:", blk(slides[0]), esc(f"Clip topic: {p['clip_topic']}")]
    elif len(slides) == 2:
        out += ["", "ON SCREEN, beat 1:", blk(slides[0]), "ON SCREEN, beat 2:", blk(slides[1])]
    else:
        out += ["", "ON SCREEN:", blk(slides[0])]
    out += ["", "CAPTION:", blk(p["post_caption"]), "",
            esc(f"{'CLIP' if p['media'] == 'video' else 'STILL'}: {v['clip']}")]
    if v.get("clip_moment"):
        out.append(esc(f"MOMENT: {v['clip_moment']}"))
    links = v.get("links") or {}
    if links:
        if p["media"] == "video":
            yt_label = "YouTube clip" if v.get("source_link") else "Find it on YouTube"
            out.append(link(yt_label, links["youtube"]) + " | " + link("Find it on TikTok", links["tiktok"]))
        else:
            out.append(link("Find it on Google Images", links["images"]) + " | " + link("Pinterest", links["pinterest"]))
    elif v.get("clip_type") == "own_footage":
        out.append(esc("SHOOT IT YOURSELF with your phone"))
    if v.get("best_moment"):
        out.append(esc(f"START AT: {v['best_moment']}"))
    sound_line = f"SOUND: {v['audio']}" + (f" ({v['sound_why']})" if v.get("sound_why") else "")
    out += [esc(sound_line),
            esc(f"LOOK: {v['color_grade']}, {v['overlay_fx']}"),
            esc(f"FORMAT: {v['delivery']}")]
    if p.get("why"):
        out.append(esc(f"WHY IT SHOULD HIT: {p['why']}"))
    return "\n".join(out)


def render_header(pkg: Dict[str, object], html: bool = False) -> str:
    rows = [f"{pkg['page']} | {pkg['date']}", "Today's plan:"]
    for p in pkg["posts"]:
        rows.append(f"{p['post_number']}. {p['post_time']['time']} | {_media_label(p)} | {config.PILLAR_LABELS[p['pillar']]}")
    broken = [p for p in pkg["posts"] if p.get("fallback_reason")]
    if broken:
        rows.append(f"⚠ {len(broken)} pre-written: {broken[0]['fallback_reason']}")
    text = "\n".join(rows)
    return _html.escape(text, quote=False) if html else text


def render_package(pkg: Dict[str, object], html: bool = False) -> List[str]:
    """[header, post1, post2, ...] as separate messages."""
    return [render_header(pkg, html)] + [render_post(p, html) for p in pkg["posts"]]
