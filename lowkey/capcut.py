"""CapCut walkthrough for one post: what to do, in order, with exact seconds and why.

Menu names move between CapCut versions, so each step says what to do first and the menu name second.
"""
from typing import Dict, List

GRADES = [
    ("B&W", "Filters: search B&W or Noir. Or Adjust: Saturation -100, Contrast +25, Brightness -10."),
    ("Teal", "Filters: a teal or cinematic filter at about 60%. Adjust: Contrast +20, Temperature -25."),
    ("Warm", "Adjust: Saturation -35, Temperature +10, Shadows -15. Then Effects: Vignette."),
    ("Desaturated", "Adjust: Saturation -50, Temperature -15, Contrast +15."),
]

WATERMARK = ("Watermark: Overlay > Add overlay: your @im_just_lowkey blackletter PNG. Make it once (type the "
             "handle in a blackletter font on a transparent background, save as PNG) and reuse it every time. "
             "Opacity 30-40%, lower-middle of the frame. Cover or crop any old watermark.")


def _grade(text: str) -> str:
    for key, tip in GRADES:
        if key.lower() in text.lower():
            return tip
    return "Adjust: Saturation -40, Contrast +20, Brightness -10 (then match the look: " + text + ")."


def _fx(fx: str) -> str:
    f = fx.lower()
    for kind in ("snow", "rain"):
        if kind in f:
            return (f"Overlay > Add overlay: pick a {kind} video (search '{kind} overlay'). "
                    "Blend mode Screen, opacity about 40%.")
    if "grain" in f:
        return "Effects > Video effects: Film grain, keep it subtle."
    if "zoom" in f:
        return "Keyframes (or Animations > Combo): scale 100% to 110% across the clip for a slow push-in."
    return ""


def _indent(s: str) -> str:
    return "   " + s.replace("\n", "\n   ")


def timeline(post: Dict[str, object]) -> List[str]:
    """Second-by-second plan for video posts."""
    v, fmt = post["visual"], post["format"]
    secs = v["duration_seconds"]
    if fmt == "interview":
        return ["0.0s: your hook text is already on screen and stays the whole clip",
                "0.0s to the end: auto captions follow the speech",
                f"Cut so the clip ends on the last word of a sentence (about {secs}s, 20-30s is the sweet spot)"]
    last = secs - 1
    if fmt == "single":
        return ["0.0 - 0.5s: clip plays, no text yet (the eye settles)",
                "0.5s: text fades in (0.5s fade)",
                f"0.5 - {last}s: text stays, nothing else moves",
                f"{last} - {secs}s: text and sound fade out so it loops cleanly"]
    half = max(3, secs // 2)
    return ["0.0 - 0.5s: clip plays, no text yet",
            f"0.5 - {half}s: beat 1 (the hook)",
            f"{half}s: beat 1 out, beat 2 (the payoff) fades in",
            f"{half} - {last}s: beat 2 stays",
            f"{last} - {secs}s: text and sound fade out"]


def steps(post: Dict[str, object]) -> str:
    """Plain-text, numbered CapCut steps tailored to this post."""
    v, fmt, media, slides = post["visual"], post["format"], post.get("media", "video"), post["on_screen_text"]
    secs, kw = v["duration_seconds"], v["search_keywords"]
    words = len(" ".join(slides).split())
    kind = {"video": f"video, {secs}s", "photo": "photo post", "carousel": "photo carousel"}[media]
    out: List[str] = [f"CAPCUT | POST {post['post_number']} | {fmt} | {kind}", ""]
    n = [0]

    def add(text: str) -> None:
        n[0] += 1
        out.append(f"{n[0]}. {text}")

    # 1. the clip
    if v.get("source_link"):
        where = f"Open your YouTube clip: {v['source_link']}."
        if v.get("best_moment"):
            where += f" Best moment: {v['best_moment']}."
        add(where + " Save the part you need to your gallery.")
    elif fmt == "interview":
        add(f"Find the clip: tap the YouTube link in the post (it searches \"{kw[0]}\"). Pick a 20-30s answer "
            f"about: {post['clip_topic']}.")
    else:
        pick = "one sharp, dark frame" if media != "video" else f"a moment of about {secs}s"
        add(f"Find the clip: tap the YouTube or TikTok link in the post (searches \"{kw[0]}\"). Pick {pick} "
            "where the face or silhouette is clear and the frame is dark.")

    # 2. project + length
    if media == "video":
        add("New project, add the clip. Ratio 9:16. " + (
            "Trim to about 25s, black bars top and bottom are fine." if fmt == "interview"
            else f"Trim to exactly {secs}s (drag the ends or Split)."))
        if fmt != "interview":
            add(f"Why {secs}s: about {words} words take ~{round(words / 3, 1)}s to read, plus ~3s so the text isn't "
                "rushed. Short videos replay more, and a replay counts as extra watch time.")
    else:
        add("New project, add the clip. Ratio 9:16. Scrub to the best frame, then Freeze (this becomes your "
            "background image).")

    # 3. look
    add("Look: " + _grade(v["color_grade"]))
    fx = _fx(v["overlay_fx"])
    if fx:
        add(fx)

    # 4. text
    if fmt == "interview":
        add("Subtitles: Text > Auto captions > English. Style: bold white, centered, highlight the word being "
            "spoken. Fix any wrong words.")
        add(f"Hook: Text > Add text. Type:\n{_indent(slides[0])}\n   Put it near the top, bold, on screen for the "
            "whole clip.")
    elif media == "carousel":
        add("Make 2 slides: duplicate the frozen frame so you have two. Font: search Typewriter or Courier, "
            f"white, centered.\n   Slide 1:\n{_indent(slides[0])}\n   Slide 2:\n{_indent(slides[1])}")
    elif media == "photo":
        add("Text: Text > Add text, paste this, bold clean sans, white, no outline, centered about 60% down.\n"
            f"{_indent(slides[0])}")
    elif fmt == "split":
        add("Text: Text > Add text, bold clean sans, white, no outline, centered about 60% down. Make two text layers:\n"
            f"   Beat 1:\n{_indent(slides[0])}\n   Beat 2:\n{_indent(slides[1])}\n"
            "   Animation In: Fade in, 0.5s. Drag the text ends to match the timing below.")
    else:
        add("Text: Text > Add text, paste this, bold clean sans, white, no outline, centered about 60% down.\n"
            f"{_indent(slides[0])}\n   Animation In: Fade in, 0.5s.")

    # 5. timing
    if media == "video":
        add("Timing, second by second:\n" + "\n".join("   " + t for t in timeline(post)))
    elif media == "photo":
        add("No timing, it's a still. Photo posts earn saves, so make the text the whole point.")
    else:
        add("Slide 1 is the hook (it makes people swipe), slide 2 is the payoff. Carousels earn saves and shares.")

    add(WATERMARK)

    # 6. sound
    if fmt == "interview":
        add("Sound: keep the clip's own audio. No music.")
    elif media == "video":
        add(f"Sound: Audio > Sounds, search \"{v['audio']}\". Mute the clip's own sound, volume 100%, fade out the "
            "last second. For reach, export without music and add the sound inside TikTok so your post links to "
            "the sound page. Check that the sound exists before you commit to it.")
    else:
        add(f"Sound: in TikTok's photo post screen, tap Add sound and search \"{v['audio']}\".")

    # 7. export
    if media == "video":
        add("Export 1080p, 30fps.")
    else:
        add("Export each slide as an image if CapCut offers it (Export > Photo). If not, screenshot the "
            "full-screen preview.")
    add(f"Post it at {post['post_time']['label']}. Paste the caption and hashtags from the post above (tap to copy).")
    out += ["", "Menu names shift between CapCut versions. If you can't find one, search the option name."]
    return "\n".join(out)
