"""Local clip library, sounds, and edit helpers. Used as the fallback and to repair Gemini output.

The clip library mirrors what the page already uses (Shelby, Pattinson, Gosling, Bale, etc.)
and the sounds are the tracks already used on the page.
"""
import random
from typing import Dict, List, Optional
from urllib.parse import quote_plus

from .quotes import Quote

ALL = ["defense", "no_explanations", "silence", "alone"]


def _c(cid, who, scene, kw, pillars, static_ok=False, tags=(), fmts=("single", "split"), grade=None):
    return {"id": cid, "who": who, "scene": scene, "keywords": kw, "pillars": pillars,
            "static_ok": static_ok, "tags": list(tags), "fmts": list(fmts), "grade": grade}


CLIPS: List[dict] = [
    _c("shelby_window", "Thomas Shelby (Cillian Murphy)", "smoking, looking out a window",
       ["thomas shelby smoking window edit", "peaky blinders window scene"],
       ["silence", "no_explanations", "defense"], tags=["#peakyblinders", "#thomasshelby"]),
    _c("shelby_walk_fog", "Thomas Shelby (Cillian Murphy)", "walking out of a building into fog, coat and cap",
       ["thomas shelby walking out fog edit", "peaky blinders walking scene"],
       ["no_explanations", "silence", "alone"], tags=["#peakyblinders", "#thomasshelby"]),
    _c("shelby_briefcase", "Thomas Shelby (Cillian Murphy)", "walking with a briefcase, smoking",
       ["thomas shelby briefcase walk edit"], ["silence", "no_explanations"],
       tags=["#peakyblinders", "#thomasshelby"]),
    _c("shelby_portrait", "Thomas Shelby (Cillian Murphy)", "dark coat and flat cap, standing still (B&W still)",
       ["thomas shelby black and white portrait", "peaky blinders flat cap still"],
       ALL, static_ok=True, tags=["#peakyblinders", "#thomasshelby"]),
    _c("shelby_looking_up", "Thomas Shelby (Cillian Murphy)", "looking up while smoking, low light",
       ["thomas shelby looking up smoking edit"], ["defense", "no_explanations", "alone"],
       tags=["#peakyblinders", "#thomasshelby"]),
    _c("batman_shadows", "Bruce Wayne (Robert Pattinson)", "moving through shadows",
       ["the batman pattinson shadows edit", "robert pattinson batman dark scene"],
       ["silence", "no_explanations"], tags=["#thebatman", "#robertpattinson"]),
    _c("bruce_crowd", "Bruce Wayne (Robert Pattinson)", "suit, turning his head in a crowd",
       ["bruce wayne suit crowd edit", "robert pattinson bruce wayne walking"],
       ["silence", "no_explanations", "defense"], tags=["#thebatman", "#robertpattinson"]),
    _c("driver_night", "The Driver (Ryan Gosling)", "driving through the city at night",
       ["ryan gosling drive night driving edit", "drive 2011 night scene"],
       ["alone", "silence"], tags=["#drive", "#ryangosling"]),
    _c("officerk_snow", "Officer K (Ryan Gosling)", "sitting alone on snow-covered steps",
       ["blade runner 2049 snow steps edit", "ryan gosling officer k snow"],
       ["alone", "no_explanations", "defense"], tags=["#bladerunner2049", "#ryangosling"]),
    _c("bateman_headphones", "Patrick Bateman (Christian Bale)", "walking through an office with headphones on",
       ["patrick bateman headphones office walk edit", "american psycho walking headphones"],
       ["silence", "defense"], tags=["#americanpsycho", "#christianbale"]),
    _c("cohle_field", "Rust Cohle (Matthew McConaughey)", "smoking in a tall grassy field",
       ["rust cohle field smoking edit", "true detective cohle black and white"],
       ["defense", "no_explanations", "alone"], tags=["#truedetective", "#rustcohle"]),
    _c("jax_bedroom", "Jax Teller (Charlie Hunnam)", "sitting thoughtfully in a dim bedroom",
       ["jax teller thinking edit", "sons of anarchy jax dark room"],
       ["silence", "alone"], tags=["#sonsofanarchy", "#jaxteller"]),
    _c("ragnar_dark", "Ragnar Lothbrok (Travis Fimmel)", "sitting alone in a dark wooded area",
       ["ragnar lothbrok alone edit", "vikings ragnar dark forest"],
       ["no_explanations", "silence", "alone"], tags=["#vikings", "#ragnarlothbrok"]),
    _c("loki_diner", "Detective Loki (Jake Gyllenhaal)", "head resting in a diner, quiet and tired",
       ["jake gyllenhaal loki diner edit", "prisoners detective loki scene"],
       ["alone", "defense"], tags=["#jakegyllenhaal"]),
    _c("diner_alone", "Lone man seated in an empty diner (from behind)", "sitting alone at night",
       ["man alone diner night aesthetic", "empty diner late night footage"],
       ["alone", "defense"], tags=[]),
    _c("rain_runner", "Man running down a wet city street at night", "streetlights, rain, grinding alone",
       ["man running rain night city street", "night run rain streetlights"],
       ["silence", "alone"], tags=["#nightrun"]),
    _c("interview_cee", "Central Cee interview", "talking about emotions, blocking people out",
       ["central cee interview emotions", "central cee interview short clip"],
       ["defense", "silence"], fmts=("interview",), tags=["#centralcee"]),
    _c("interview_estgee", "EST Gee interview (B&W)", "talking about surviving alone, loyalty",
       ["est gee interview clip", "est gee interview black and white"],
       ["alone", "silence", "defense"], fmts=("interview",), tags=["#estgee"]),
    _c("interview_gates", "Kevin Gates interview", "talking about not caring who likes him, friends and loyalty",
       ["kevin gates interview clip", "kevin gates interview loyalty"],
       ["no_explanations", "silence"], fmts=("interview",), tags=["#kevingates"]),
]

# Tracks already used on the page (title, treatment, pillars). Check availability in your region.
AUDIO = [
    ("snowfall", "slowed + reverb", ["alone", "no_explanations"]),
    ("past lives", "slowed + reverb", ["alone", "silence"]),
    ("apathy", "slowed + reverb", ["defense", "no_explanations"]),
    ("golden brown", "slowed", ["no_explanations", "defense"]),
    ("sleep walker", "slowed", ["silence", "alone"]),
    ("goth", "slowed + reverb", ["silence"]),
    ("resonance", "as is", ["silence"]),
    ("this feeling - oneheart", "as is", ["silence", "no_explanations"]),
    ("last hope", "over slowed + reverb", ["defense"]),
    ("loosing interest", "slowed", ["no_explanations"]),
    ("solitude - Felsmann + Tiley", "reinterpretation", ["alone", "silence"]),
    ("big dawgs", "as is", ["silence"]),
]

GRADES = [
    "B&W, high contrast, crushed blacks",
    "Desaturated, cold, slight film grain",
    "Teal-green wash, heavy contrast",
    "Warm shadows, low saturation, vignette",
]
FX = ["snow overlay", "rain overlay", "film grain only", "slow zoom-in", "no overlay, keep it clean"]


EDIT_NOTES = [
    "Only your blackletter @im_just_lowkey watermark, low opacity, lower-middle frame",
    "Crop out any source watermarks (old @novaclips included)",
]

FX_LABELS = [("snow", "snow overlay"), ("rain", "rain overlay"), ("grain", "film grain only"),
             ("zoom", "slow zoom-in")]
NO_FX = "no overlay, keep it clean"

ALLOWED_MEDIA = {"single": ("video", "photo"), "split": ("video", "carousel"), "interview": ("video",)}


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def fx_label(text: Optional[str]) -> str:
    t = (text or "").lower()
    for key, label in FX_LABELS:
        if key in t:
            return label
    return NO_FX


def pick_grade(rng: random.Random) -> str:
    return rng.choice(GRADES)


def pick_audio(pillar: str, rng: random.Random) -> str:
    """A sound from the tracks already used on the page that fits the pillar."""
    title, treatment, _ = rng.choice([a for a in AUDIO if pillar in a[2]] or AUDIO)
    return title if treatment == "as is" else f"{title} ({treatment})"


def library_clip(q: Quote, rng: random.Random) -> dict:
    options = [c for c in CLIPS if q.fmt in c["fmts"] and q.pillar in c["pillars"]]
    return rng.choice(options)


def search_links(keywords: List[str], source_link: str = "") -> Dict[str, str]:
    """Tappable search links for the clip. A pasted YouTube link is used directly as the source."""
    query = quote_plus(keywords[0] if keywords else "dark aesthetic edit")
    links = {"youtube": source_link or f"https://www.youtube.com/results?search_query={query}",
             "tiktok": f"https://www.tiktok.com/search?q={query}"}
    return links


def delivery_text(fmt: str, media: str) -> str:
    if fmt == "interview":
        return "Interview clip: your hook line pinned on top, the clip's real subtitles (bold, dynamic) below"
    if media == "photo":
        return "Photo post (TikTok photo mode): one still frame from the clip with the text on it"
    if media == "carousel":
        return "Photo carousel, 2 slides (typewriter font): hook on slide 1, payoff on slide 2"
    if fmt == "split":
        return "Video: hook first, swap to the payoff at the halfway point"
    return "Video with the text centered, fade in"


def duration_for(fmt: str, media: str, words: int) -> int:
    """Seconds for video; 0 for photo posts."""
    if media != "video":
        return 0
    if fmt == "interview":
        return 25
    if fmt == "single":
        return _clamp(round(words / 3) + 3, 6, 14)
    return _clamp(round(words / 3.5) + 3, 6, 10)


def pick_media(q: Quote, clip: dict, rng: random.Random) -> str:
    if q.fmt == "interview":
        return "video"
    if q.fmt == "split":
        return "carousel" if clip["static_ok"] and rng.random() < 0.6 else "video"
    return "photo" if rng.random() < 0.25 else "video"


def build_visual(q: Quote, rng: random.Random) -> Dict[str, object]:
    """Fallback visual direction from the local libraries (used when Gemini is off or fails)."""
    clip = library_clip(q, rng)
    media = pick_media(q, clip, rng)
    words = len(q.text.split())
    search = clip["keywords"] + (["clip topic: " + q.clip_topic] if q.fmt == "interview" else [])
    if q.fmt == "interview":
        audio, fx, grade = "no extra sound (keep the interview audio)", NO_FX, "B&W or desaturated, subtle vignette"
    else:
        audio = pick_audio(q.pillar, rng)
        fx = rng.choice(FX)
        grade = clip["grade"] or pick_grade(rng)
    return {
        "media": media,
        "clip_id": clip["id"],
        "clip": f"{clip['who']}: {clip['scene']}",
        "search_keywords": search,
        "delivery": delivery_text(q.fmt, media),
        "color_grade": grade,
        "overlay_fx": fx,
        "audio": audio,
        "duration_seconds": duration_for(q.fmt, media, words),
        "character_tags": clip["tags"],
        "edit_notes": EDIT_NOTES,
        "links": search_links(clip["keywords"]),
        "best_moment": "",
        "source_link": "",
    }
