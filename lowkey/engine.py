"""Builds posts and daily plans and renders them as text/HTML. No Telegram code in here.

Gemini decides everything when it's on (brain.py). Otherwise the local bank and libraries are used.
"""
import html as _html
import json
import random
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from . import brain, captions, config, quotes, reminders, store, timing, visuals
from . import own as own_mod
from .quotes import Quote


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
               number: int = 1, rng: Optional[random.Random] = None,
               for_day: Optional[date] = None) -> Dict[str, object]:
    """One complete post. `brief` is an idea from you, `link` a YouTube clip to build around,
    `for_day` the day it is planned for (week plan)."""
    rng = rng or random.Random()
    recent = recent or []
    post = brain.generate_post(brief, link, recent, for_day=for_day)
    if post is None:
        post = _fallback_post(rng, recent)
        post["fallback_reason"] = brain.why_not()
    post["post_number"] = number
    return post


def _own_fallback(own: dict, rng: random.Random, recent: List[dict], attached: Optional[str]) -> Dict[str, object]:
    """Finish the owner's own post without Gemini: his choices stay, the rest comes from the local libraries."""
    parts = own["parts"] or ["(your clip)"]
    fmt = "split" if len(parts) == 2 else "single"
    taken = {r.get("pillar") for r in recent}
    pillar = rng.choice([p for p in config.PILLARS if p not in taken] or list(config.PILLARS))
    q = Quote(pillar, fmt, parts, "mine")
    vis = visuals.build_visual(q, rng)
    media = vis["media"]
    if attached == "image":
        media = "photo" if fmt == "single" else "carousel"
    elif attached == "video":
        media = "video"
    vis["media"], vis["delivery"] = media, visuals.delivery_text(fmt, media)
    vis["duration_seconds"] = visuals.duration_for(fmt, media, len(q.text.split()))
    if attached:
        vis.update(clip=f"Your {'photo' if attached == 'image' else 'clip'}: the file you sent", clip_type="attached",
                   links={}, search_keywords=[])
    cap = captions.format_caption(q, vis["character_tags"], rng)
    post = {
        "pillar": pillar, "format": fmt, "media": media, "quote_source": "mine", "attached": attached or "",
        "on_screen_text": captions.overlay_slides(q), "clip_topic": "", **cap,
        "post_time": timing.post_time(timing.PILLAR_BAND[pillar]), "why": "", "visual": vis,
    }
    if own["parts"]:
        quotes.mark_used(q)
    return own_mod.apply_locks(post, own)


def build_own_post(own: dict, media: Optional[tuple] = None, recent: Optional[List[dict]] = None,
                   number: int = 1) -> Dict[str, object]:
    """The owner's own post (his quote, hashtags, sound, clip...). Gemini fills in what he left out; without
    Gemini the local libraries do. `media` is (bytes, mime, kind) when he attached a photo or video."""
    recent = recent or []
    attached = media[2] if media else None
    post = brain.generate_post("", own.get("link", ""), recent, media=media, own=own)
    if post is None:
        post = _own_fallback(own, random.Random(), recent, attached)
        post["fallback_reason"] = brain.why_not()
    post["post_number"] = number
    return post


def when_for(post: dict, current: Optional[datetime] = None) -> Optional[datetime]:
    """When a post should go out (its planned date, else today), or None if that moment has passed."""
    current = current or reminders.now()
    day = date.fromisoformat(post["date"]) if post.get("date") else current.date()
    hh, mm = (int(x) for x in post["post_time"]["time"].split(":"))
    when = datetime(day.year, day.month, day.day, hh, mm, tzinfo=current.tzinfo)
    return when if when > current + timedelta(minutes=1) else None


def _day_prefix(p: dict) -> str:
    return f"{date.fromisoformat(p['date']):%a %d %b}, " if p.get("date") else ""


def save_week(posts: List[dict], start: date) -> None:
    config.ensure_dirs()
    (config.OUTPUT_DIR / f"week-{start.isoformat()}.json").write_text(
        json.dumps({"page": config.PAGE_HANDLE, "start": start.isoformat(), "posts": posts},
                   indent=2, ensure_ascii=False), encoding="utf-8")


def render_week_header(posts: List[dict], html: bool = False) -> str:
    rows = [f"📆 Week plan: {_day_prefix(posts[0]).rstrip(', ')} to {_day_prefix(posts[-1]).rstrip(', ')}"] if posts else []
    for p in posts:
        hook = " ".join(p["on_screen_text"][0].split())[:46]
        rows.append(f"{date.fromisoformat(p['date']):%a %d}: {p['post_time']['time']} | {_media_label(p)} | {hook}")
    broken = [p for p in posts if p.get("fallback_reason")]
    if broken:
        rows.append(f"⚠ {len(broken)} pre-written: {broken[0]['fallback_reason']}")
    text = "\n".join(rows)
    return _html.escape(text, quote=False) if html else text


def render_shopping_list(posts: List[dict], html: bool = False) -> str:
    """One list of every clip or still the week needs, with tappable search links."""
    esc = (lambda s: _html.escape(s, quote=False)) if html else (lambda s: s)

    def link(label: str, url: str) -> str:
        return f'<a href="{_html.escape(url, quote=True)}">{esc(label)}</a>' if html else f"{label}: {url}"

    rows = [("<b>🛒 Clips and stills for the week</b>" if html else "🛒 Clips and stills for the week")]
    for p in posts:
        v, links = p["visual"], p["visual"].get("links") or {}
        day = f"{date.fromisoformat(p['date']):%a %d}" if p.get("date") else f"#{p['post_number']}"
        line = f"{day}: {esc(v['clip'])}"
        if v.get("clip_moment"):
            line += esc(f" ({v['clip_moment']})")
        if v.get("clip_type") == "own_footage":
            line += " | shoot it yourself"
        elif links and p["media"] == "video":
            line += " | " + link("YouTube", links["youtube"])
        elif links:
            line += " | " + link("Images", links["images"])
        rows.append(line)
    return "\n".join(rows)


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


def build_media_post(data: bytes, mime: str, kind: str, recent: Optional[List[dict]] = None, brief: str = "",
                     link: str = "") -> Optional[Dict[str, object]]:
    """A post built around a photo or video the owner sent. None if Gemini can't do it (no local fallback)."""
    post = brain.generate_post(brief, link, recent or [], media=(data, mime, kind))
    if post is not None:
        post["post_number"] = 1
    return post


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
    pkg = build_package(store.today(), count or store.get_posts_per_day())
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
    tag = {"gemini": "", "mine": " | your own"}.get(p["quote_source"], " | pre-written")
    out = [bold(f"POST {p['post_number']} | {config.PILLAR_LABELS[p['pillar']]} | {p['format']} | {_media_label(p)}{tag}"),
           esc(f"POST AT: {_day_prefix(p)}{t['label']} ({timing.BAND_LABELS[t['band']]})")]
    if p.get("fallback_reason"):
        if p["quote_source"] == "mine":  # his own words are untouched; only the extras came from the local list
            out.append(esc(f"ℹ Gemini is off, so what you didn't choose came from my local list ({p['fallback_reason']})"))
        else:
            out.append(esc(f"⚠ Gemini didn't write this: {p['fallback_reason']}"))
    if p["format"] == "interview":
        out += ["", "HOOK TEXT:", blk(slides[0]), esc(f"Clip topic: {p['clip_topic']}")]
    elif len(slides) == 2:
        out += ["", "ON SCREEN, beat 1:", blk(slides[0]), "ON SCREEN, beat 2:", blk(slides[1])]
    else:
        out += ["", "ON SCREEN:", blk(slides[0])]
    out += ["", "CAPTION:", blk(p["post_caption"]), "",
            esc(f"{'CLIP' if p['media'] == 'video' else 'STILL'}: {v['clip']}")]
    if p.get("attached"):
        out.append(esc(f"(this is the {'photo' if p['attached'] == 'image' else 'clip'} you sent me)"))
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
