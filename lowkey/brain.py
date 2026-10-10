"""Gemini decides the whole post: pillar, format, photo vs video, text, clip, sound, hashtags, timing.

Everything it returns is validated. Missing or bad fields are repaired from the local libraries, and
bad candidates are dropped. If Gemini is off or fails, engine.py falls back to the local bank.
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

VOICE = """You run the content for @im_just_lowkey, a dark stoic theme page ("Moving in silence").
Voice: calm, cold, conversational. Someone talking plainly to himself, not performing. Everyday words
(energy, peace, circle, business, noise, chapter, quiet, grind). Heavy but never dramatic. Statements, not advice.
Voice reference (do NOT reuse or paraphrase these):
- "Notice how quiet it gets when you stop reaching out first."
- "I didn't change. I just stopped forcing connections with people who only reach out when it suits them."
- "They think I'm distant... / ...I just outgrew the need to be understood."
- "The older you get, the more you realize... / ...how peaceful life is when you keep your business to yourself."
Rules for the on-screen lines:
- No emojis, hashtags, or quotation marks. No motivational-poster cliches (rise and grind, believe in yourself,
  never give up, king, queen, sigma, alpha, manifesting, blessed, journey, hustle).
- Do not tell the reader what to do. State it. Concrete beats abstract.
- Original lines only. Never reproduce famous quotes or real people's words."""

GROWTH = """GROWTH: the page is being built into a big, viral page.
- The first 1-2 seconds decide everything: open on the strongest line, readable instantly.
- Under 10 seconds for video so it replays; the last word should land as the loop restarts.
- One idea per post. Relatable lines people want to send to someone or save.
- Mix formats: photo/carousel posts earn saves, short videos earn replays, interview hooks earn watch time.
- Vary pillar, format and media from the recent posts. Keep one consistent dark look and white bold text.
- 4-7 hashtags: #movinginsilence plus a mix of niche and bigger tags. No spam."""

FIELDS = """FIELDS:
- pillar: defense | no_explanations | silence | alone  (defense = detachment/numbness as armor; no_explanations = closing chapters,
  letting people believe what they want; silence = moving in silence, private grind, observing, outgrowing fake people;
  alone = survived the lowest points alone, absence can't break me)
- format: single (1 line, 8-26 words) | split (lines = [hook, payoff], hook 3-12 words, payoff 4-16 words, no ellipses)
  | interview (1 hook line, 4-12 words, sits above a REAL interview clip; set clip_topic = what the person in the clip
  should be talking about; never write the interviewee's words)
- media: video | photo (single only) | carousel (split only). Interview is always video.
- clip: {who, scene, search: [2-3 YouTube/TikTok search phrases that find that exact scene]}. Prefer the page's clips;
  you may suggest other iconic dark, stoic scenes from films, series, or interviews.
- look: color grade in a few words. overlay: snow | rain | film grain | slow zoom | none.
- sound: {title, treatment: "slowed + reverb" | "slowed" | "as is"}. Only tracks you are confident exist on TikTok.
  For interview use title "" (the interview audio stays).
- duration_seconds: video 6-12 (interview 20-30); 0 for photo/carousel.
- time_band: morning | afternoon | evening | late_night. Pick what fits the mood (heavy, lonely = late_night).
- caption_line: a short dry line (no question, no emoji). hashtags: list.
- best_moment: "m:ss-m:ss" only if a YouTube clip was provided and you watched it, else "".
- why: one sentence on why this should perform."""

SCHEMA = """Return ONLY JSON: {"candidates": [{"pillar": "", "format": "", "media": "", "lines": [""], "clip_topic": "",
"clip": {"who": "", "scene": "", "search": [""]}, "look": "", "overlay": "", "sound": {"title": "", "treatment": ""},
"duration_seconds": 8, "time_band": "", "caption_line": "", "hashtags": [""], "best_moment": "", "why": ""}]}
Give 3 candidates, best first."""

_TAG = re.compile(r"^#[A-Za-z0-9_]{2,30}$")
_MOMENT = re.compile(r"^\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}$")
YT_RE = re.compile(r"https?://(?:www\.|m\.)?(?:youtube\.com/(?:watch\?[^\s]*v=|shorts/)|youtu\.be/)[\w\-]{6,}[^\s]*")


def ai_available() -> bool:
    return bool(config.GEMINI_API_KEY) and store.ai_enabled()


def _library_lines() -> str:
    clips = "\n".join(f"- {c['who']}: {c['scene']}" for c in visuals.CLIPS if "single" in c["fmts"])
    ints = "\n".join(f"- {c['who']}" for c in visuals.CLIPS if "interview" in c["fmts"])
    sounds = "\n".join(f"- {t} ({tr})" for t, tr, _ in visuals.AUDIO)
    return (f"CLIPS THE PAGE ALREADY USES:\n{clips}\nINTERVIEW CLIPS THE PAGE USES:\n{ints}\n"
            f"SOUNDS THE PAGE ALREADY USES:\n{sounds}")


def build_system() -> str:
    return "\n\n".join([VOICE, persona.context(), GROWTH, FIELDS, _library_lines(), SCHEMA])


def _youtube_title(link: str) -> str:
    """Best-effort title/channel via YouTube oEmbed (no API key)."""
    try:
        url = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(link, safe="")
        with urllib.request.urlopen(url, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return f"{data.get('title', '')} ({data.get('author_name', '')})".strip()
    except Exception:  # noqa: BLE001
        return ""


def build_prompt(brief: str, link: str, recent: List[dict], watching: bool, yt_title: str) -> str:
    parts = ["Create the next post for the page."]
    if brief:
        parts.append(f"His idea or direction for this post: {brief}")
    if link and watching:
        parts.append(f"A YouTube clip was provided: {link}. Watch it and build the post around what is really in it. "
                     "Set clip.who and clip.scene to what you see, and best_moment to the best 6-10 second window.")
    elif link:
        parts.append(f"A YouTube clip was provided: {link}. Title: {yt_title or 'unknown'}. You can't watch it, "
                     "so infer from the title, set clip.search to find it, and leave best_moment empty.")
    if recent:
        lines = "\n".join(f"- {r.get('pillar')} / {r.get('format')} / {r.get('media', 'video')}" for r in recent[-4:])
        parts.append("Most recent posts (pick a different pillar, format and media from these):\n" + lines)
    perf = insights.summary_for_gemini()
    if perf:
        parts.append(perf)
    notes = trends.get()
    if notes:
        parts.append("Trend notes (may be wrong, only use what you're confident exists):\n" + notes)
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
    tags: List[str] = ["#movinginsilence"]
    for t in raw if isinstance(raw, list) else []:
        t = str(t).strip().replace(" ", "").lower()
        t = t if t.startswith("#") else "#" + t
        if _TAG.match(t) and t not in tags:
            tags.append(t)
    pool = [t for t in captions.PILLAR_POOLS[pillar] + captions.GENERAL_POOL if t not in tags]
    while len(tags) < 4 and pool:
        tags.append(pool.pop(rng.randrange(len(pool))))
    return tags[:8]


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
    who, scene = _s(clip.get("who"), 80), _s(clip.get("scene"), 120)
    search = [x for x in (_s(k, 80) for k in clip.get("search", []) if isinstance(k, str)) if x][:3]
    if not (who and scene and search):
        lib = visuals.library_clip(q, rng)
        who, scene, search = lib["who"], lib["scene"], lib["keywords"]
    if fmt == "interview":
        search = search + ["clip topic: " + q.clip_topic]

    sound = item.get("sound") if isinstance(item.get("sound"), dict) else {}
    title, treatment = _s(sound.get("title"), 60), _s(sound.get("treatment"), 30).lower()
    if fmt == "interview":
        audio = "no extra sound (keep the interview audio)"
    elif title:
        audio = title if treatment == "as is" else f"{title} ({treatment or 'slowed + reverb'})"
    else:
        audio = visuals.pick_audio(pillar, rng)

    try:
        wanted = int(item.get("duration_seconds") or 0)
    except (TypeError, ValueError):
        wanted = 0
    words = len(q.text.split())
    duration = visuals.duration_for(fmt, media, words)
    if media == "video" and fmt != "interview" and wanted:
        duration = visuals._clamp(wanted, 6, 14 if fmt == "single" else 10)

    band = _s(item.get("time_band"), 20).lower()
    band = band if band in timing.BANDS else timing.PILLAR_BAND[pillar]

    cl = quotes.clean(_s(item.get("caption_line"), 80))
    if not cl or "?" in cl or quotes.has_emoji(cl):
        cl = rng.choice(captions.CAPTION_LINES[pillar])
    tags = _hashtags(item.get("hashtags"), pillar, rng)
    moment = _s(item.get("best_moment"), 12)
    moment = moment if (link and watched and _MOMENT.match(moment)) else ""

    visual = {
        "media": media,
        "clip_id": "gemini",
        "clip": f"{who}: {scene}",
        "search_keywords": search,
        "delivery": visuals.delivery_text(fmt, media),
        "color_grade": _s(item.get("look"), 80) or visuals.pick_grade(rng),
        "overlay_fx": visuals.fx_label(_s(item.get("overlay"), 30)),
        "audio": audio,
        "duration_seconds": duration,
        "character_tags": [],
        "edit_notes": visuals.EDIT_NOTES,
        "links": visuals.search_links(search, link),
        "best_moment": moment,
        "source_link": link,
    }
    post = {
        "pillar": pillar, "format": fmt, "media": media, "quote_source": "gemini",
        "on_screen_text": captions.overlay_slides(q), "clip_topic": q.clip_topic,
        "caption_line": cl, "hashtags": tags, "post_caption": f"{cl}\n\n{' '.join(tags)}",
        "post_time": timing.post_time(band), "why": _s(item.get("why"), 180), "visual": visual,
    }
    return post, q


# ------------------------------------------------------------------ public API
def generate_post(brief: str = "", link: str = "", recent: Optional[List[dict]] = None) -> Optional[Dict[str, object]]:
    """Ask Gemini for a full post. Returns None if Gemini is off, failing, or gave nothing usable."""
    if not ai_available():
        return None
    rng = random.Random()
    system = build_system()
    yt_title = ""
    for attempt in range(3):
        watching = bool(link) and attempt == 0  # try real video understanding first, then fall back to the title
        if link and attempt == 1:
            yt_title = _youtube_title(link)
        prompt = build_prompt(brief, link, recent or [], watching, yt_title)
        try:
            for item in _ask(system, prompt, link if watching else ""):
                res = to_post(item, link, rng, watching)
                if res:
                    post, q = res
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
