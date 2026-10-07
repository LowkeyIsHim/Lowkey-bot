"""Clip, edit, and sound direction. Outputs search keywords and edit notes, not downloaded footage.

The clip library mirrors what the page already uses (Shelby, Pattinson, Gosling, Bale, etc.)
and the sounds are the tracks already used on the page.
"""
import random
from typing import Dict, List

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


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def build_visual(q: Quote, rng: random.Random) -> Dict[str, object]:
    """Pick clip, delivery, grade, sound, and duration for a quote."""
    options = [c for c in CLIPS if q.fmt in c["fmts"] and q.pillar in c["pillars"]]
    clip = rng.choice(options)
    words = len(q.text.split())

    if q.fmt == "interview":
        delivery = "Interview clip: your hook line pinned on top, the clip's real subtitles (bold, dynamic) below"
        duration = 25
        audio = "no extra sound (keep the interview audio)"
        search = clip["keywords"] + ["clip topic: " + q.clip_topic]
        fx = "no overlay, keep it clean"
        grade = "B&W or desaturated, subtle vignette"
    else:
        static = q.fmt == "split" and clip["static_ok"] and rng.random() < 0.6
        if q.fmt == "split":
            delivery = ("2 static slides (typewriter font), hook on slide 1, payoff on slide 2" if static
                        else "Video: hook first, swap to the payoff at the halfway point")
        else:
            delivery = "Video with the text centered, fade in"
        duration = (_clamp(round(words / 3) + 3, 6, 14) if q.fmt == "single"
                    else _clamp(round(words / 3.5) + 3, 6, 10))
        track = rng.choice([a for a in AUDIO if q.pillar in a[2]] or AUDIO)
        audio = track[0] if track[1] == "as is" else f"{track[0]} ({track[1]})"
        search = clip["keywords"]
        fx = rng.choice(FX)
        grade = clip["grade"] or rng.choice(GRADES)

    return {
        "clip_id": clip["id"],
        "clip": f"{clip['who']}: {clip['scene']}",
        "search_keywords": search,
        "delivery": delivery,
        "color_grade": grade,
        "overlay_fx": fx,
        "audio": audio,
        "duration_seconds": duration,
        "character_tags": clip["tags"],
        "edit_notes": ["Only your blackletter @im_just_lowkey watermark, low opacity, lower-middle frame",
                       "Crop out any source watermarks (old @novaclips included)"],
    }
