"""Caption line, hashtags, and on-screen text layout."""
import random
import textwrap
from typing import Dict, Iterable, List

from . import config
from .quotes import Quote

FIXED_TAGS = ["#movinginsilence", "#stoicism", "#lowkey"]

GENERAL_POOL = ["#real", "#mindset", "#corecore", "#lonewolf", "#darkaesthetic",
                "#deepthoughts", "#quotes", "#mentalstrength", "#selfreliance", "#fyp"]

PILLAR_POOLS: Dict[str, List[str]] = {
    "defense": ["#emotionalarmor", "#detachment", "#numb", "#innerwar", "#stonefaced", "#healingquietly"],
    "no_explanations": ["#noexplanations", "#closedchapter", "#letthemtalk", "#peaceofmind", "#silenceisgolden", "#nocontact"],
    "silence": ["#silentgrind", "#stayquiet", "#privatelife", "#observe", "#buildinsilence", "#outgrowth"],
    "alone": ["#survivor", "#alonebutnotlonely", "#selfmade", "#solitude", "#rebuilt", "#notrust"],
}

CAPTION_LINES: Dict[str, List[str]] = {
    "defense": ["Funny how that works.", "Learned young. Still using it.", "Armor doesn't come with instructions.",
                "Not cold. Just trained.", "Laughing is cheaper."],
    "no_explanations": ["No further comment.", "Chapter closed. No notes.", "Not my story to correct.",
                        "Let it be wrong.", "Context is a privilege."],
    "silence": ["Watching. Not reacting.", "Results will do the talking.", "No updates.",
                "Still working. Still quiet.", "Announce nothing."],
    "alone": ["Nobody saw it. Nothing broke.", "Built alone. Still standing.", "Absence noted. Impact: none.",
              "Learned it the hard way.", "Still here. Still quiet."],
}


def wrap(text: str, width: int = 34) -> str:
    """Wrap on-screen text to 2-3 short centered lines."""
    return textwrap.fill(text, width=width)


def overlay_slides(q: Quote) -> List[str]:
    """On-screen text beats. Split posts become hook... / ...payoff."""
    if q.fmt == "split":
        return [wrap(q.parts[0].rstrip(".,") + "..."), wrap("..." + q.parts[1].lstrip("."))]
    return [wrap(q.parts[0])]


def format_caption(q: Quote, character_tags: Iterable[str], rng: random.Random) -> Dict[str, object]:
    """Short dry caption line + hashtags (3 fixed, clip character tags, then pillar/general pool)."""
    line = rng.choice(CAPTION_LINES[q.pillar])
    tags = FIXED_TAGS + [t for t in list(character_tags)[:2] if t not in FIXED_TAGS]
    total = rng.randint(config.HASHTAGS_MIN, max(config.HASHTAGS_MIN, config.HASHTAGS_MAX))
    pool = [t for t in dict.fromkeys(PILLAR_POOLS[q.pillar] + GENERAL_POOL) if t not in tags]
    tags += rng.sample(pool, min(max(0, total - len(tags)), len(pool)))
    return {"caption_line": line, "hashtags": tags, "post_caption": f"{line}\n\n{' '.join(tags)}"}
