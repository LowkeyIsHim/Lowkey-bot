"""Local quote bank, validation, and no-repeat tracking (Gemini lives in brain.py).

Three formats, matched to the page's existing posts:
  single     one block of text
  split      hook... / ...payoff (two beats)
  interview  a hook line over a real interview clip (the clip's own subtitles do the talking)
"""
import json
import logging
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from typing import Dict, List

from . import config, seed

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
    return re.sub(r"^\.{2,}\s*|\s*\.{2,}$", "", line.strip().strip('"\u201c\u201d')).strip()


# ------------------------------------------------------------------ public API
def clean(line: str) -> str:
    return _clean(line)


def has_emoji(text: str) -> bool:
    return bool(_EMOJI.search(text))


def is_dup(q: Quote) -> bool:
    """True if q is (nearly) identical to a post already on the page or used in the last NO_REPEAT_DAYS."""
    with _LOCK:
        return _is_dup(q, _load_used())


def mark_used(q: Quote) -> None:
    with _LOCK:
        _mark_used(q)


def recent_texts(n: int = 15) -> List[str]:
    with _LOCK:
        return [r["text"] for r in _load_used()][-n:]


def get_quote(pillar: str, fmt: str, rng) -> Quote:
    """Pick an unused line from the local bank. Never raises; reuses the oldest if the bank is exhausted."""
    with _LOCK:
        used = _load_used()
        bank = _bank(pillar, fmt)
        fresh = [b for b in bank if not _is_dup(b, used)]
        if fresh:
            q = rng.choice(fresh)
        else:
            last = {_norm(r["text"]): r["date"] for r in used}
            q = min(bank, key=lambda b: last.get(_norm(b.text), "0"))
            log.warning("Bank exhausted for %s/%s; reusing oldest", pillar, fmt)
        _mark_used(q)
        return q
