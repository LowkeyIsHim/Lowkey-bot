"""Gemini is the page's strategist: it decides EVERYTHING about each post, fresh every time.

Pillar, format, photo vs video, the words, the clip or still and the exact moment, color grade, sound,
hashtags, length and the exact time to post. Nothing comes from a local menu. The only local data it is
shown is what the page used recently (so it never repeats) and what happened (results, audience, trends).

Everything it returns is validated. Missing fields are repaired, bad candidates are dropped, and if Gemini
is off or fails, engine.py falls back to the local bank.
"""
import json
import logging
import random
import re
import time
import urllib.parse
import urllib.request
from typing import Dict, List, Optional, Tuple

from . import captions, config, insights, persona, quotes, store, timing, trends, visuals
from .quotes import Quote

log = logging.getLogger("brain")

JOB = """YOUR JOB
You are the full-time content manager and creative director of @im_just_lowkey. The owner has one goal: grow this
page to millions of followers and engagement, then monetize it. You decide EVERYTHING about each post, like a
strategist who studies what is trending: the idea and the exact words, the pillar, the format, photo or video, the
clip or still (which scene, which exact moment), the color grade, the sound, the hashtags, how long it runs, and the
exact time to post. The owner only edits on his phone in CapCut and uploads what you decide, so every field must be
specific enough to act on with no guessing. He has no budget, can shoot simple footage on his phone (night walks,
rain on a window, a hooded silhouette), and finds clips on YouTube, TikTok and Pinterest.
Before you answer, think: what is trending in this niche right now, what stops the scroll in the first second, what
makes someone save or send it, and what has the page NOT done recently. The trend notes are your main input."""

VOICE = """Voice of the on-screen lines: calm, cold, conversational. Someone talking plainly to himself, not performing.
Everyday words (energy, peace, circle, business, noise, chapter, quiet, grind). Heavy but never dramatic.
Statements, not advice. Examples of the voice (do NOT reuse or paraphrase them):
- "Notice how quiet it gets when you stop reaching out first."
- "I didn't change. I just stopped forcing connections with people who only reach out when it suits them."
- "They think I'm distant... / ...I just outgrew the need to be understood."
- "The older you get, the more you realize... / ...how peaceful life is when you keep your business to yourself."
Rules: no emojis, hashtags or quotation marks in the lines. No motivational-poster cliches (rise and grind, believe in
yourself, never give up, king, queen, sigma, alpha, manifesting, blessed, journey, hustle). Do not tell the reader
what to do. Concrete beats abstract. Original lines only, never famous quotes or real people's words."""

STYLE_REF = """THE PAGE'S LOOK SO FAR (style reference only, NOT a menu): dark, cinematic, stoic edits: black-and-white or
desaturated, bold white centered text, slowed + reverb sounds, 5-14 second clips, a line that reads like a private
thought; plus rapper interview clips with a hook line. So far it leaned on a few film characters (Thomas Shelby, The
Batman, Gosling in Drive and Blade Runner 2049, American Psycho, Rust Cohle, Jax Teller, Ragnar) and a handful of
sounds, and it has been repetitive. Do NOT default to those characters, scenes or sounds. Keep the dark stoic mood
but go wider and fresher: other films and series, anime, boxing and athlete moments, interviews, nature, cities at
night, real-life footage, cinematic b-roll, stills, or simple own-phone footage ideas."""

GROWTH = """GROWTH RULES
- The first 1-2 seconds decide everything: open on the strongest line, readable instantly.
- Under 10 seconds for most videos so they replay; the last word should land as the loop restarts.
- One idea per post. Relatable lines people want to send to someone or save.
- Mix formats across the day: photo/carousel posts earn saves, short videos earn replays, interview hooks earn
  watch time. Vary pillar, format, media, clip and sound from recent posts.
- Reaching NEW viewers on the For You page matters more than followers. Follow what is trending in sounds,
  hashtags, scenes and hooks, but keep the page's dark stoic identity.
- Sounds: choose trending or rising sounds for this niche (see trend notes) or strong evergreen tracks. Never reuse
  a sound from the recently used list. Give the exact track title and artist. If you are not sure a track exists on
  TikTok, choose one you are sure about."""

FIELDS = """FIELDS (all required unless stated)
- pillar: defense | no_explanations | silence | alone  (defense = detachment/numbness as armor; no_explanations =
  closing chapters, letting people believe what they want; silence = moving in silence, private grind, observing,
  outgrowing fake people; alone = survived the lowest points alone, absence can't break me)
- format: single (1 line, 8-26 words) | split (lines = [hook, payoff]; hook 3-12 words, payoff 4-16 words, no
  ellipses) | interview (1 hook line, 4-12 words, above a REAL interview clip; set clip_topic to what the person
  should be talking about; never write the interviewee's words)
- media: video | photo (single only) | carousel (split only). Interview is always video.
- clip: {type: film|series|interview|anime|sports|stock|own_footage|still, who: the character, person or subject,
  scene: what is on screen, moment: the exact moment to use (what happens, so he can find and cut it; do NOT guess
  timestamps), search: [2-3 YouTube/TikTok/Pinterest search phrases that find it]}. For photo posts, scene = the
  exact still (subject, framing, lighting). For own_footage, scene + moment = a shot he can film himself.
- look: the color grade in a few words. grade_recipe: CapCut settings, e.g. "Saturation -60, Contrast +25,
  Temperature -15, Shadows -10, Filter: Noir 60%". overlay: snow | rain | film grain | slow zoom | none.
- sound: {title, artist, treatment: "slowed + reverb" | "slowed" | "sped up" | "as is", why: one short reason}.
  For interview leave title empty (the interview audio stays).
- duration_seconds: video 5-15 (interview 20-30); 0 for photo/carousel.
- post_time: the exact time to post, 24h "HH:MM" in the owner's local time, chosen from the audience data,
  the results, and the mood (heavy, lonely lines suit late evening). Not a vague band.
- caption_line: a short dry line (no question, no emoji). hashtags: 3-7, exactly what you would use today.
- best_moment: "m:ss-m:ss" ONLY if a YouTube clip was provided and you watched it, else "".
- why: one sentence on why this should perform."""

SCHEMA = """Return ONLY JSON: {"candidates": [{"pillar": "", "format": "", "media": "", "lines": [""], "clip_topic": "",
"clip": {"type": "", "who": "", "scene": "", "moment": "", "search": [""]}, "look": "", "grade_recipe": "",
"overlay": "", "sound": {"title": "", "artist": "", "treatment": "", "why": ""}, "duration_seconds": 8,
"post_time": "", "caption_line": "", "hashtags": [""], "best_moment": "", "why": ""}]}
Give 3 candidates, best first. Make them genuinely different from each other."""

_TAG = re.compile(r"^#[A-Za-z0-9_]{2,30}$")
_MOMENT = re.compile(r"^\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}$")
_CLOCK = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
CLIP_TYPES = ("film", "series", "interview", "anime", "sports", "stock", "own_footage", "still")
YT_RE = re.compile(r"https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?[^\s]*v=|shorts/)|youtu\.be/)[\w\-]{6,}[^\s]*")


def ai_available() -> bool:
    return bool(config.GEMINI_API_KEY) and store.ai_enabled()


def build_system() -> str:
    return "\n\n".join([JOB, VOICE, persona.context(), STYLE_REF, GROWTH, FIELDS, SCHEMA])


def _youtube_title(link: str) -> str:
    """Best-effort title/channel via YouTube oEmbed (no API key)."""
    try:
        url = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(link, safe="")
        with urllib.request.urlopen(url, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return f"{data.get('title', '')} ({data.get('author_name', '')})".strip()
    except Exception:  # noqa: BLE001
        return ""


# ------------------------------------------------------------------ what the page used recently
def _key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _sound_title(visual: dict) -> str:
    return visual.get("sound_title") or (visual.get("audio", "").split(" (")[0].split(" - ")[0])


def _who(visual: dict) -> str:
    return (visual.get("clip", "").split(":")[0])


def _recent_visuals(recent: List[dict]) -> List[dict]:
    return [r["visual"] for r in recent if r.get("visual")]


def penalty(post: dict, recent: List[dict]) -> int:
    """How much a candidate repeats what the page used recently (0 = fully fresh)."""
    vis = _recent_visuals(recent)
    sounds = {_key(_sound_title(v)) for v in vis[-10:]}
    whos = [_key(_who(v)) for v in vis[-6:]]
    pen = 0
    if _key(_sound_title(post["visual"])) in sounds:
        pen += 2
    pen += whos.count(_key(_who(post["visual"])))
    return pen


def build_prompt(brief: str, link: str, recent: List[dict], watching: bool, yt_title: str) -> str:
    parts = ["Create the next post for the page."]
    if brief:
        parts.append(f"The owner's idea or direction for this post: {brief}")
    if link and watching:
        parts.append(f"A YouTube clip was provided: {link}. Watch it and build the post around what is really in it. "
                     "Set clip.who, clip.scene and clip.moment to what you see, and best_moment to the best 6-10 "
                     "second window.")
    elif link:
        parts.append(f"A YouTube clip was provided: {link}. Title: {yt_title or 'unknown'}. You can't watch it, so "
                     "infer from the title, set clip.search to find it, and leave best_moment empty.")
    parts.append("AUDIENCE AND TIMING DATA:\n" + timing.audience_summary())
    perf = insights.summary_for_gemini()
    if perf:
        parts.append(perf)
    notes = trends.get()
    parts.append("TREND NOTES (your main input; may be imperfect, only use what you're confident exists):\n" +
                 (notes or "None available right now. Use your own knowledge of what is currently popular."))
    if recent:
        lines = "\n".join(f"- {r.get('pillar')} / {r.get('format')} / {r.get('media', 'video')}" for r in recent[-4:])
        parts.append("Most recent posts (pick a different pillar, format and media):\n" + lines)
        vis = _recent_visuals(recent)[-12:]
        if vis:
            sounds = sorted({_sound_title(v) for v in vis if _sound_title(v)})
            clips = [v.get("clip", "") for v in vis if v.get("clip")]
            parts.append("RECENTLY USED, DO NOT REUSE (the page is repeating itself):\nSounds: " +
                         (", ".join(sounds) or "none") + "\nClips and scenes:\n- " + "\n- ".join(clips))
    avoid = quotes.recent_texts(15)
    if avoid:
        parts.append("Do NOT resemble these recent lines:\n- " + "\n- ".join(avoid))
    return "\n\n".join(parts)


def _ask(system: str, prompt: str, link: str = "") -> List[dict]:
    """One Gemini call returning raw candidate dicts. Raises on any failure (caller handles)."""
    from google import genai  # lazy import so the fallback works without the SDK
    from google.genai import types

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    contents = prompt
    if link:
        contents = types.Content(parts=[types.Part(file_data=types.FileData(file_uri=link)),
                                        types.Part(text=prompt)])
    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=contents,
        config=types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json",
                                           temperature=1.0),
    )
    raw = re.sub(r"^```(?:json)?|```$", "", (resp.text or "").strip(), flags=re.MULTILINE).strip()
    data = json.loads(raw)
    items = data.get("candidates", []) if isinstance(data, dict) else data
    return [i for i in items if isinstance(i, dict)]


# ------------------------------------------------------------------ validation + repair
def _s(value, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _hashtags(raw, pillar: str, rng: random.Random) -> List[str]:
    tags: List[str] = []
    for t in raw if isinstance(raw, list) else []:
        t = str(t).strip().replace(" ", "").lower()
        t = t if t.startswith("#") else "#" + t
        if _TAG.match(t) and t not in tags:
            tags.append(t)
    pool = [t for t in captions.PILLAR_POOLS[pillar] + captions.GENERAL_POOL if t not in tags]
    while len(tags) < 3 and pool:
        tags.append(pool.pop(rng.randrange(len(pool))))
    return tags[:8]


def _clock(value) -> str:
    m = _CLOCK.match(str(value or "").strip())
    return f"{int(m.group(1)):02d}:{m.group(2)}" if m else ""


def to_post(item: dict, link: str, rng: random.Random,
            watched: bool = False) -> Optional[Tuple[Dict[str, object], Quote]]:
    """Validate and normalize one Gemini candidate. None if the text itself is unusable."""
    pillar = _s(item.get("pillar"), 30).lower()
    fmt = _s(item.get("format"), 20).lower()
    if pillar not in config.PILLARS or fmt not in config.FORMAT_WEIGHTS:
        return None
    lines = [quotes.clean(l) for l in item.get("lines", []) if isinstance(l, str)]
    q = Quote(pillar, fmt, lines, "gemini", clip_topic=_s(item.get("clip_topic"), 160))
    if not quotes.validate(q) or quotes.is_dup(q):
        return None

    media = _s(item.get("media"), 20).lower()
    if fmt == "split" and media == "photo":
        media = "carousel"
    elif fmt == "single" and media == "carousel":
        media = "photo"
    if media not in visuals.ALLOWED_MEDIA[fmt]:
        media = "video"

    clip = item.get("clip") if isinstance(item.get("clip"), dict) else {}
    ctype = _s(clip.get("type"), 20).lower()
    ctype = ctype if ctype in CLIP_TYPES else ("interview" if fmt == "interview" else "film")
    who, scene = _s(clip.get("who"), 80), _s(clip.get("scene"), 140)
    moment = _s(clip.get("moment"), 160)
    search = [x for x in (_s(k, 80) for k in clip.get("search", []) if isinstance(k, str)) if x][:3]
    if not (who and scene and search):
        log.warning("Gemini left the clip incomplete; repairing from the local library")
        lib = visuals.library_clip(q, rng)
        who, scene, search = lib["who"], lib["scene"], lib["keywords"]
    if fmt == "interview":
        search = search + ["clip topic: " + q.clip_topic]

    sound = item.get("sound") if isinstance(item.get("sound"), dict) else {}
    s_title, s_artist = _s(sound.get("title"), 60), _s(sound.get("artist"), 60)
    treatment = _s(sound.get("treatment"), 30).lower()
    if fmt == "interview":
        s_title, audio = "", "no extra sound (keep the interview audio)"
    else:
        if not s_title:
            log.warning("Gemini left the sound empty; repairing from the local list")
            audio_fallback = visuals.pick_audio(pillar, rng)
            s_title = audio_fallback.split(" (")[0]
        name = f"{s_title} - {s_artist}" if s_artist else s_title
        audio = name if treatment in ("", "as is") else f"{name} ({treatment})"

    try:
        wanted = int(item.get("duration_seconds") or 0)
    except (TypeError, ValueError):
        wanted = 0
    words = len(q.text.split())
    duration = visuals.duration_for(fmt, media, words)
    if media == "video" and wanted:
        if fmt == "interview":
            duration = wanted if 20 <= wanted <= 35 else 25
        else:
            duration = visuals._clamp(wanted, 5, 15)

    clock = _clock(item.get("post_time"))
    if not clock:
        clock = timing.band_times()[timing.PILLAR_BAND[pillar]]
    cl = quotes.clean(_s(item.get("caption_line"), 80))
    if not cl or "?" in cl or quotes.has_emoji(cl):
        cl = rng.choice(captions.CAPTION_LINES[pillar])
    tags = _hashtags(item.get("hashtags"), pillar, rng)
    best = _s(item.get("best_moment"), 12)
    best = best if (link and watched and _MOMENT.match(best)) else ""

    links = {} if ctype == "own_footage" else visuals.search_links(search, link)
    visual = {
        "media": media,
        "clip_id": "gemini",
        "clip": f"{who}: {scene}",
        "clip_type": ctype,
        "clip_moment": moment,
        "search_keywords": search,
        "delivery": visuals.delivery_text(fmt, media),
        "color_grade": _s(item.get("look"), 80) or visuals.pick_grade(rng),
        "grade_recipe": _s(item.get("grade_recipe"), 160),
        "overlay_fx": visuals.fx_label(_s(item.get("overlay"), 30)),
        "audio": audio,
        "sound_title": s_title,
        "sound_why": _s(sound.get("why"), 140),
        "duration_seconds": duration,
        "character_tags": [],
        "edit_notes": visuals.EDIT_NOTES,
        "links": links,
        "best_moment": best,
        "source_link": link,
    }
    post = {
        "pillar": pillar, "format": fmt, "media": media, "quote_source": "gemini",
        "on_screen_text": captions.overlay_slides(q), "clip_topic": q.clip_topic,
        "caption_line": cl, "hashtags": tags, "post_caption": f"{cl}\n\n{' '.join(tags)}",
        "post_time": timing.post_time_at(clock), "why": _s(item.get("why"), 180), "visual": visual,
    }
    return post, q


# ------------------------------------------------------------------ public API
def generate_post(brief: str = "", link: str = "", recent: Optional[List[dict]] = None) -> Optional[Dict[str, object]]:
    """Ask Gemini for a full post. Returns None if Gemini is off, failing, or gave nothing usable."""
    if not ai_available():
        return None
    rng = random.Random()
    recent = recent or []
    system = build_system()
    yt_title = ""
    for attempt in range(3):
        watching = bool(link) and attempt == 0  # try real video understanding first, then fall back to the title
        if link and attempt == 1:
            yt_title = _youtube_title(link)
        prompt = build_prompt(brief, link, recent, watching, yt_title)
        try:
            valid = [r for r in (to_post(i, link, rng, watching) for i in _ask(system, prompt, link if watching else ""))
                     if r]
            if valid:
                post, q = min(valid, key=lambda r: penalty(r[0], recent))  # freshest candidate; ties keep Gemini's order
                quotes.mark_used(q)
                return post
            log.warning("Gemini returned no usable post (attempt %d)", attempt + 1)
        except ImportError:
            log.error("google-genai not installed; run: pip install -r requirements.txt")
            return None
        except Exception as exc:  # noqa: BLE001 - SDK raises many types; all mean "try again or fall back"
            msg = str(exc)
            if watching:
                log.warning("Video understanding failed, retrying with the title only: %s", msg[:160])
                continue
            if any(c in msg for c in ("400", "401", "403", "API_KEY", "PERMISSION")):
                log.error("Gemini auth/config error, skipping retries: %s", msg[:200])
                return None
            wait = 20 if ("429" in msg or "RESOURCE_EXHAUSTED" in msg) else 2 * (attempt + 1)
            log.warning("Gemini failed (attempt %d): %s", attempt + 1, msg[:200])
            if attempt < 2:
                time.sleep(wait)
    return None
