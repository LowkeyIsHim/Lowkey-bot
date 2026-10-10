"""Learn from results: parse the numbers you log, rank your posts, and tell Gemini what works."""
import re
from datetime import datetime
from typing import Dict, List, Optional

from . import store

_NUM = r"(\d[\d,]*(?:\.\d+)?\s*[kKmM]?)"
LABELS = {
    "views": r"(?:views?|plays?)",
    "likes": r"(?:likes?|hearts?)",
    "shares": r"(?:shares?)",
    "saves": r"(?:saves?|favou?rites?)",
    "watch_pct": r"(?:watch(?:ed)?|completion|retention|finish(?:ed)?)",
}


def to_num(text: str) -> float:
    t = text.strip().lower().replace(",", "").replace(" ", "")
    mult = 1
    if t.endswith("k"):
        mult, t = 1_000, t[:-1]
    elif t.endswith("m"):
        mult, t = 1_000_000, t[:-1]
    return float(t) * mult


def fmt_num(n: float) -> str:
    n = float(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000:
        return f"{n / 1_000:.1f}k".replace(".0k", "k")
    return str(int(n))


def looks_like_numbers(text: str) -> bool:
    """True if a message is plausibly a stats message (digits, few words)."""
    return any(c.isdigit() for c in text) and sum(c.isalpha() for c in text) <= 40


def parse_metrics(text: str) -> Optional[Dict[str, float]]:
    """'12400 830 95 210 62%' (views likes shares saves watch%) or labeled: '12.4k views, 95 shares ...'."""
    out: Dict[str, float] = {}
    number_first = text.strip()[:1].isdigit()  # "12.4k views 95 shares" vs "views 12.4k shares 95"
    for key, label in LABELS.items():
        pattern = (_NUM + r"\s*%?\s*" + label) if number_first else (label + r"\s*[:=\-]?\s*" + _NUM)
        m = re.search(pattern, text, re.I)
        if m:
            out[key] = to_num(m.group(1))
    if "views" not in out:
        tokens = re.findall(_NUM + r"%?", text)
        if not tokens:
            return None
        out = {k: to_num(t) for k, t in zip(("views", "likes", "shares", "saves", "watch_pct"), tokens)}
    m = {"views": out.get("views", 0), "likes": out.get("likes", 0), "shares": out.get("shares", 0),
         "saves": out.get("saves", 0), "watch_pct": out.get("watch_pct", 0)}
    if m["views"] < 1 or m["watch_pct"] > 100:
        return None
    if any(m[k] > m["views"] for k in ("likes", "shares", "saves")):
        return None  # likely typed in the wrong order
    return {k: (int(v) if k != "watch_pct" else round(v, 1)) for k, v in m.items()}


def reach_score(m: Dict[str, float]) -> float:
    """Weighted reach: shares and saves count most because they feed the For You page."""
    return m["views"] + 20 * m["shares"] + 10 * m["saves"] + 2 * m["likes"]


def row_from_post(post: dict, post_id: str, metrics: Dict[str, float]) -> dict:
    return {
        "post_id": post_id, "logged": datetime.now().isoformat(), "metrics": metrics,
        "pillar": post["pillar"], "format": post["format"], "media": post["media"],
        "band": post["post_time"]["band"], "audio": post["visual"]["audio"],
        "text": " / ".join(s.replace("\n", " ") for s in post["on_screen_text"])[:160],
    }


def ranked() -> List[dict]:
    return sorted(store.read_results().values(), key=lambda r: reach_score(r["metrics"]), reverse=True)


def rank_of(post_id: str) -> tuple:
    rows = ranked()
    for i, r in enumerate(rows, 1):
        if r["post_id"] == post_id:
            return i, len(rows)
    return 0, len(rows)


def _line(r: dict) -> str:
    m = r["metrics"]
    watch = f", {m['watch_pct']}% watched" if m.get("watch_pct") else ""
    return (f"- {fmt_num(m['views'])} views, {fmt_num(m['shares'])} shares, {fmt_num(m['saves'])} saves{watch} | "
            f"{r['pillar']}/{r['format']}/{r['media']} | posted {r['band']} | sound: {r['audio']} | \"{r['text'][:90]}\"")


def summary_for_gemini(min_posts: int = 3) -> str:
    """Best and weakest posts so Gemini can repeat what wins. Empty until enough posts are logged."""
    rows = ranked()
    if len(rows) < min_posts:
        return ""
    n = min(3, len(rows) // 2)
    return ("RESULTS FROM THIS PAGE'S OWN POSTS (learn from them: repeat what the winners share, avoid what the "
            "weakest share, never copy their lines):\nBEST:\n" + "\n".join(_line(r) for r in rows[:n]) +
            "\nWEAKEST:\n" + "\n".join(_line(r) for r in rows[-n:]))


def _avg_by(rows: List[dict], key) -> List[tuple]:
    groups: Dict[str, List[float]] = {}
    for r in rows:
        groups.setdefault(key(r), []).append(r["metrics"]["views"])
    return sorted(((k, sum(v) / len(v), len(v)) for k, v in groups.items()), key=lambda x: x[1], reverse=True)


def breakdown_text() -> str:
    """Plain-text results screen for Telegram."""
    rows = ranked()
    if not rows:
        return ("📊 Results\n\nNothing logged yet. After you post, tap 📊 Log results under the post and send "
                "your numbers. Once a few posts are logged, Gemini learns what wins and makes more like it.")
    top = rows[0]["metrics"]
    out = [f"📊 Results: {len(rows)} post{'s' if len(rows) != 1 else ''} logged", "",
           f"Best post: {fmt_num(top['views'])} views, {fmt_num(top['shares'])} shares, {fmt_num(top['saves'])} saves",
           f"\"{rows[0]['text'][:110]}\"", ""]
    for title, key in (("By pillar", lambda r: r["pillar"]),
                       ("By style", lambda r: f"{r['format']} {r['media']}"),
                       ("By time", lambda r: r["band"].replace("_", " "))):
        out.append(f"{title} (average views):")
        out += [f"{k}: {fmt_num(avg)} ({n} post{'s' if n != 1 else ''})" for k, avg, n in _avg_by(rows, key)[:4]]
        out.append("")
    if len(rows) < 5:
        out.append("Log at least 5 posts before trusting these patterns.")
    return "\n".join(out).strip()
