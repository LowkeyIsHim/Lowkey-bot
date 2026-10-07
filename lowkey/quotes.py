"""Quote engine: Gemini first, local bank as fallback, no repeats within NO_REPEAT_DAYS.

Three formats, matched to the page's existing posts:
  single     one block of text
  split      hook... / ...payoff (two beats)
  interview  a hook line over a real interview clip (the clip's own subtitles do the talking)
"""
import json
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Dict, List, Optional

from . import config, seed, store

log = logging.getLogger("quotes")
_LOCK = threading.RLock()  # bot handlers run generation in threads; keep used-state consistent


@dataclass
class Quote:
    pillar: str
    fmt: str                      # "single" | "split" | "interview"
    parts: List[str] = field(default_factory=list)
    source: str = "bank"          # "gemini" | "bank"
    clip_topic: str = ""          # interview only: what the person in the clip should be talking about

    @property
    def text(self) -> str:
        return " ".join(self.parts)


# ------------------------------------------------------------------ fallback bank (original lines)
_SINGLE: Dict[str, List[str]] = {
    "defense": [
        "I laugh when I should cry. It's not a joke, it's the only thing that ever worked.",
        "Numb isn't empty. It's what you build when feeling everything was never safe.",
        "Nobody asks why I'm this calm. Calm was the only way to get through it.",
        "I learned to smile through it before I learned to talk about it.",
        "Being open cost me too much growing up. So I stopped paying.",
        "I'm not cold. I just stopped handing out the version of me that got used.",
        "I don't shut people out. I just stopped letting them see when it hurts.",
        "Detached isn't the same as unbothered. I just got good at hiding the difference.",
    ],
    "no_explanations": [
        "I stopped explaining myself the day I realized people only hear what fits their story.",
        "Let them think what they want. It costs me nothing and saves me everything.",
        "Some chapters close without a text, a reason, or a goodbye. That's the cleanest way.",
        "I'm not ignoring you. I'm just done spending energy on people who already decided.",
        "Not every silence is anger. Sometimes I'm just done arguing with your version of me.",
        "I don't owe anyone a full explanation for protecting my peace.",
        "If you needed me to explain it, you were never going to understand it.",
        "The ones who matter never needed the explanation. The rest never deserved it.",
    ],
    "silence": [
        "I stopped posting my plans. Now people only find out when it's already done.",
        "Keep your circle small and your moves smaller. Nobody needs a preview.",
        "I don't react anymore. I watch, I learn, and I remember.",
        "The grind hits different when nobody knows you're doing it.",
        "Real work doesn't announce itself. It just changes your life quietly.",
        "People show you who they are the moment they think you're not watching.",
        "I didn't lose my friends. I just stopped chasing people who were never really there.",
        "Silence isn't me being gone. It's me building.",
    ],
    "alone": [
        "I've been through worse with nobody. Your absence isn't going to be what breaks me.",
        "Nobody carried me through my lowest, so nobody leaving can drop me now.",
        "I stopped waiting for someone to show up the day I realized I'd survive without them.",
        "Being alone doesn't scare me anymore. I've already lived through the worst version of it.",
        "I built myself without a safety net. That's why I don't panic when people leave.",
        "I don't miss people. I miss who I thought they were.",
        "My lowest point had no audience. I don't need one for the comeback either.",
        "People think I'm strong because I'm quiet. I'm quiet because nobody was there to talk to.",
    ],
}

_SPLIT: Dict[str, List[List[str]]] = {
    "defense": [
        ["They call it a defense mechanism", "I call it the reason I'm still standing"],
        ["I laugh at things that should've broken me", "that's how I know how much they did"],
        ["It's not that I can't feel", "I just learned early that feeling out loud wasn't safe"],
        ["Quiet people aren't always cold", "some of us just learned what happens when you let people in"],
    ],
    "no_explanations": [
        ["You can't explain yourself to someone who needs you to be the villain", "so I stopped trying"],
        ["I used to write the long message", "now I just leave and let the silence say it"],
        ["Let them tell the story wrong", "I know where I was and what I carried"],
        ["I never stopped caring about the truth", "I just stopped needing everyone to hear it"],
    ],
    "silence": [
        ["The less I say about my plans", "the more peace I have while I work on them"],
        ["They'll see the results", "just not the nights that built them"],
        ["Nobody clapped at 3am", "that's how I know it's real"],
        ["I used to want everyone to know", "now I want nobody to see it coming"],
    ],
    "alone": [
        ["You can leave", "I've already survived worse without you"],
        ["I learned to hold myself together", "so nobody's absence can pull me apart"],
        ["I didn't have a safety net", "so I learned to be my own"],
        ["Missing me won't bring me back", "I got used to the quiet before you noticed it"],
    ],
}

# (hook line over the clip, what the person in the real clip should be talking about)
_HOOKS: Dict[str, List[List[str]]] = {
    "defense": [
        ["Why I laugh when I should be crying", "interview answer about laughing off pain, blocking people out, being bad with emotions"],
        ["The real reason I went numb", "interview answer about growing up fast and shutting feelings down to cope"],
    ],
    "no_explanations": [
        ["Why I don't need everyone to like me", "interview answer about not caring what people think, being loyal but not friendly"],
        ["The day I stopped defending myself", "interview answer about not justifying yourself to people who already decided"],
    ],
    "silence": [
        ["What happens when you stop telling people your plans", "interview answer about keeping business private and moving alone"],
        ["Why my circle got this small", "interview answer about trust, loyalty, and cutting people off"],
    ],
    "alone": [
        ["What being alone at your lowest does to you", "interview answer about going through the worst with nobody and not fearing people leaving"],
        ["Why your absence doesn't scare me", "interview answer about being self-reliant and unbothered when people walk away"],
    ],
}


def _bank(pillar: str, fmt: str) -> List[Quote]:
    if fmt == "single":
        return [Quote(pillar, fmt, [t]) for t in _SINGLE[pillar]]
    if fmt == "split":
        return [Quote(pillar, fmt, list(p)) for p in _SPLIT[pillar]]
    return [Quote(pillar, fmt, [h], clip_topic=t) for h, t in _HOOKS[pillar]]


# ------------------------------------------------------------------ dedup + usage tracking
def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", text.lower())).strip()


_SEED_NORMS = [_norm(t) for t in seed.EXISTING_POSTS]


def _similar(a: str, b: str) -> bool:
    """True if two normalized texts are near-duplicates, including one being a chunk of the other."""
    if SequenceMatcher(None, a, b).ratio() >= 0.78:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if len(short) < 25:
        return False
    m = SequenceMatcher(None, short, long_, autojunk=False).find_longest_match(0, len(short), 0, len(long_))
    return m.size / len(short) >= 0.6


def used_count() -> int:
    """Quotes used inside the no-repeat window (for /status)."""
    return len(_load_used())


def _load_used() -> List[dict]:
    """Used entries from the last NO_REPEAT_DAYS days."""
    if not config.USED_FILE.exists():
        return []
    try:
        rows = json.loads(config.USED_FILE.read_text(encoding="utf-8")).get("used", [])
    except (json.JSONDecodeError, OSError, AttributeError) as exc:
        log.error("used_quotes.json unreadable (%s); starting fresh", exc)
        return []
    cutoff = datetime.now() - timedelta(days=config.NO_REPEAT_DAYS)
    return [r for r in rows if datetime.fromisoformat(r["date"]) >= cutoff]


def _mark_used(q: Quote) -> None:
    config.ensure_dirs()
    rows = _load_used()
    rows.append({"text": q.text, "pillar": q.pillar, "fmt": q.fmt, "date": datetime.now().isoformat()})
    try:
        config.USED_FILE.write_text(json.dumps({"used": rows}, indent=2), encoding="utf-8")
    except OSError as exc:
        log.error("Could not save used quotes: %s", exc)


def _is_dup(q: Quote, used: List[dict]) -> bool:
    n = _norm(q.text)
    return any(_similar(n, o) for o in _SEED_NORMS + [_norm(r["text"]) for r in used])


# ------------------------------------------------------------------ validation
_EMOJI = re.compile("[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F]")
_BANNED = re.compile(config.BANNED_PATTERN, re.IGNORECASE)


def _w(s: str) -> int:
    return len(s.split())


def validate(q: Quote) -> bool:
    """Enforce voice + format rules."""
    if not q.parts or any((not p) or _EMOJI.search(p) or _BANNED.search(p) or '"' in p for p in q.parts):
        return False
    if q.fmt == "single":
        return len(q.parts) == 1 and config.MIN_WORDS <= _w(q.parts[0]) <= config.MAX_WORDS
    if q.fmt == "split":
        return (len(q.parts) == 2 and 3 <= _w(q.parts[0]) <= 14 and 3 <= _w(q.parts[1]) <= 20
                and _w(q.text) <= config.MAX_WORDS)
    if q.fmt == "interview":
        return len(q.parts) == 1 and 4 <= _w(q.parts[0]) <= 14 and 3 <= _w(q.clip_topic) <= 30
    return False


def _clean(line: str) -> str:
    return re.sub(r"^\.+\s*|\s*\.+$", "", line.strip().strip('"\u201c\u201d')).strip()


# ------------------------------------------------------------------ Gemini
SYSTEM_PROMPT = """You write on-screen text for @im_just_lowkey, a dark stoic theme page ("Moving in silence").
Voice: calm, cold, conversational. Someone talking plainly to themselves, not performing. Everyday words
(energy, peace, circle, business, noise, chapter, quiet, grind). Heavy but never dramatic. Statements, not advice.
Voice reference (do NOT reuse or paraphrase these):
- "Notice how quiet it gets when you stop reaching out first."
- "I didn't change. I just stopped forcing connections with people who only reach out when it suits them."
- "They think I'm distant... / ...I just outgrew the need to be understood."
- "The older you get, the more you realize... / ...how peaceful life is when you keep your business to yourself."
Rules:
- No emojis, hashtags, or quotation marks.
- No motivational-poster cliches: rise and grind, believe in yourself, never give up, king, queen, sigma, alpha, manifesting, blessed, journey, hustle.
- Do not tell the reader what to do. State it.
- Concrete beats abstract. Avoid "In a world where".
- Original lines only. Never reproduce famous quotes or real people's words.
Return ONLY JSON: {"candidates": [{"lines": ["..."], "clip_topic": "..."}]}"""

FORMAT_SPECS = {
    "single": "single: ONE block, 1-2 sentences, 8-26 words. lines has exactly 1 string. Omit clip_topic.",
    "split": ("split: two beats shown in sequence. lines = [hook, payoff]. The hook is an unfinished setup "
              "(3-12 words, no trailing ellipsis). The payoff completes it (4-16 words, no leading ellipsis). "
              "Omit clip_topic."),
    "interview": ("interview: a short headline (4-12 words) that sits above a real interview clip. lines has "
                  "exactly 1 string. Set clip_topic to what the person in the clip should be talking about "
                  "(max 20 words). Do not write the interviewee's words."),
}


def _gemini_candidates(pillar: str, fmt: str, avoid: List[str]) -> List[Quote]:
    """Ask Gemini for candidates. Raises on any failure (caller handles)."""
    from google import genai  # lazy import so the fallback works without the SDK
    from google.genai import types

    client = genai.Client(api_key=config.GEMINI_API_KEY)
    prompt = (
        f"Pillar: {config.PILLARS[pillar]}\nFormat: {FORMAT_SPECS[fmt]}\n"
        f"Write 6 candidates.\nDo NOT resemble these recent ones:\n- " + "\n- ".join(avoid[-15:] or ["(none)"])
    )
    resp = client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
            temperature=1.0,
        ),
    )
    raw = re.sub(r"^```(?:json)?|```$", "", (resp.text or "").strip(), flags=re.MULTILINE).strip()
    data = json.loads(raw)
    items = data.get("candidates", []) if isinstance(data, dict) else data
    out: List[Quote] = []
    for it in items:
        if not isinstance(it, dict):
            continue
        lines = [_clean(l) for l in it.get("lines", []) if isinstance(l, str)]
        out.append(Quote(pillar, fmt, lines, "gemini", clip_topic=str(it.get("clip_topic", "")).strip()))
    return out


def _try_gemini(pillar: str, fmt: str, used: List[dict]) -> Optional[Quote]:
    if not config.GEMINI_API_KEY:
        log.info("No GEMINI_API_KEY set; using local bank")
        return None
    if not store.ai_enabled():
        log.info("AI switched off via /ai; using local bank")
        return None
    avoid = [r["text"] for r in used]
    for attempt in range(3):
        try:
            for q in _gemini_candidates(pillar, fmt, avoid):
                if validate(q) and not _is_dup(q, used):
                    return q
            log.warning("Gemini returned no usable %s quote (attempt %d)", fmt, attempt + 1)
        except ImportError:
            log.error("google-genai not installed; run: pip install -r requirements.txt")
            return None
        except Exception as exc:  # noqa: BLE001 - SDK raises many types; all mean "fall back"
            msg = str(exc)
            if any(c in msg for c in ("400", "401", "403", "API_KEY", "PERMISSION")):
                log.error("Gemini auth/config error, skipping retries: %s", msg[:200])
                return None
            wait = 20 if ("429" in msg or "RESOURCE_EXHAUSTED" in msg) else 2 * (attempt + 1)
            log.warning("Gemini failed (attempt %d): %s", attempt + 1, msg[:200])
            if attempt < 2:
                time.sleep(wait)
    return None


# ------------------------------------------------------------------ public API
def get_quote(pillar: str, fmt: str, rng) -> Quote:
    """Return a Quote for pillar+format. Never raises; always returns something usable."""
    with _LOCK:
        used = _load_used()
        q = _try_gemini(pillar, fmt, used)
        if q is None:
            bank = _bank(pillar, fmt)
            fresh = [b for b in bank if not _is_dup(b, used)]
            if fresh:
                q = rng.choice(fresh)
            else:  # whole bank used inside the window: reuse the least recently used
                last = {_norm(r["text"]): r["date"] for r in used}
                q = min(bank, key=lambda b: last.get(_norm(b.text), "0"))
                log.warning("Bank exhausted for %s/%s; reusing oldest", pillar, fmt)
        _mark_used(q)
        return q
