"""Engine tests (no Telegram, no network). Run: python -m unittest discover -s tests -v"""
import os
import random
import tempfile
import time
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from lowkey import brain, capcut, config, engine, insights, persona, quotes, store, timing, trends, visuals


class Base(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self._patches = [
            mock.patch.object(config, "DATA_DIR", tmp),
            mock.patch.object(config, "OUTPUT_DIR", tmp / "output"),
            mock.patch.object(config, "USED_FILE", tmp / "used.json"),
            mock.patch.object(config, "SETTINGS_FILE", tmp / "settings.json"),
            mock.patch.object(config, "LOG_DIR", tmp / "logs"),
            mock.patch.object(config, "GEMINI_API_KEY", ""),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()


def good_item(**over):
    item = {
        "pillar": "silence", "format": "single", "media": "video",
        "lines": ["Nobody asks what the quiet cost me, and I never offer."],
        "clip": {"who": "Thomas Shelby", "scene": "smoking at a window", "search": ["thomas shelby window edit"]},
        "look": "B&W, high contrast", "overlay": "rain",
        "sound": {"title": "snowfall", "treatment": "slowed + reverb"},
        "duration_seconds": 9, "time_band": "late_night", "caption_line": "No updates.",
        "hashtags": ["#MovingInSilence", "stoic", "#lonewolf", "bad tag!", "#darkaesthetic"],
        "best_moment": "", "why": "Short, relatable, loops on the last word.",
    }
    item.update(over)
    return item


class TestBank(Base):
    def test_bank_valid_and_original(self):
        for pillar in config.PILLARS:
            for fmt in ("single", "split", "interview"):
                bank = quotes._bank(pillar, fmt)
                self.assertTrue(bank, (pillar, fmt))
                for q in bank:
                    self.assertTrue(quotes.validate(q), q.text)
                    self.assertFalse(quotes._is_dup(q, []), f"too close to an existing post: {q.text}")

    def test_validate_rules(self):
        Q = quotes.Quote
        self.assertTrue(quotes.validate(Q("silence", "single", ["Working in silence is the whole point of it."])))
        self.assertFalse(quotes.validate(Q("silence", "single", ["Be a king and rise and grind every day."])))
        self.assertFalse(quotes.validate(Q("silence", "single", ["Quiet moves only 🔥 keep it moving always."])))
        self.assertFalse(quotes.validate(Q("silence", "single", ["Too short."])))
        self.assertFalse(quotes.validate(Q("silence", "single", [" ".join(["word"] * 40)])))

    def test_no_repeats_then_graceful_reuse(self):
        rng = random.Random(2)
        texts = [quotes.get_quote("alone", "single", rng).text for _ in range(8)]
        self.assertEqual(len(set(texts)), 8)
        self.assertTrue(quotes.get_quote("alone", "single", rng).text)


class TestBrain(Base):
    def setUp(self):
        super().setUp()
        self._key = mock.patch.object(config, "GEMINI_API_KEY", "x")
        self._key.start()

    def tearDown(self):
        self._key.stop()
        super().tearDown()

    def test_candidate_normalized(self):
        with mock.patch.object(brain, "_ask", return_value=[good_item()]):
            post = brain.generate_post()
        self.assertEqual(post["quote_source"], "gemini")
        self.assertEqual(post["visual"]["audio"], "snowfall (slowed + reverb)")
        self.assertEqual(post["visual"]["overlay_fx"], "rain overlay")
        self.assertEqual(post["visual"]["duration_seconds"], 9)
        self.assertEqual(post["post_time"]["band"], "late_night")
        tags = post["hashtags"]
        self.assertEqual(tags[0], "#movinginsilence")
        self.assertIn("#stoic", tags)
        self.assertNotIn("bad tag!", " ".join(tags))
        self.assertTrue(4 <= len(tags) <= 8)
        self.assertIn("youtube.com/results", post["visual"]["links"]["youtube"])

    def test_media_rules_and_interview(self):
        with mock.patch.object(brain, "_ask", return_value=[good_item(format="split", media="photo",
                                lines=["I stopped explaining", "the day I realized people only hear their own story"])]):
            self.assertEqual(brain.generate_post()["media"], "carousel")
        with mock.patch.object(brain, "_ask", return_value=[good_item(format="interview", media="photo",
                                lines=["Why my circle got this small"], clip_topic="trust and loyalty answer")]):
            post = brain.generate_post()
        self.assertEqual(post["media"], "video")
        self.assertIn("keep the interview audio", post["visual"]["audio"])
        self.assertEqual(post["visual"]["duration_seconds"], 25)

    def test_photo_has_no_duration(self):
        with mock.patch.object(brain, "_ask", return_value=[good_item(media="photo")]):
            post = brain.generate_post()
        self.assertEqual(post["media"], "photo")
        self.assertEqual(post["visual"]["duration_seconds"], 0)

    def test_repairs_missing_fields(self):
        item = good_item(clip={}, sound={}, look="", caption_line="Agree?", hashtags=[], overlay="")
        with mock.patch.object(brain, "_ask", return_value=[item]):
            post = brain.generate_post()
        self.assertTrue(post["visual"]["clip"] and post["visual"]["search_keywords"])
        self.assertTrue(post["visual"]["audio"])
        self.assertNotIn("?", post["caption_line"])
        self.assertGreaterEqual(len(post["hashtags"]), 4)

    def test_bad_candidates_skipped(self):
        bad = [good_item(lines=["Be a king and rise and grind every day."]),
               good_item(lines=["Notice how quiet it gets when you stop reaching out first."]),  # copy of an existing post
               good_item(pillar="nope")]
        with mock.patch.object(brain, "_ask", return_value=bad + [good_item()]):
            post = brain.generate_post()
        self.assertEqual(post["on_screen_text"][0].replace("\n", " "), "Nobody asks what the quiet cost me, and I never offer.")

    def test_youtube_link_flow(self):
        link = "https://www.youtube.com/watch?v=abcdefghijk"
        with mock.patch.object(brain, "_ask", return_value=[good_item(best_moment="0:42-0:50")]) as ask:
            post = brain.generate_post(link=link)
        self.assertEqual(post["visual"]["best_moment"], "0:42-0:50")
        self.assertEqual(post["visual"]["links"]["youtube"], link)
        self.assertEqual(ask.call_args[0][2], link)  # first attempt shows Gemini the video

    def test_youtube_falls_back_to_title(self):
        link = "https://youtu.be/abcdefghijk"
        calls = []

        def fake_ask(system, prompt, lnk=""):
            calls.append((lnk, prompt))
            if lnk:
                raise RuntimeError("400 video not supported")
            return [good_item(best_moment="1:00-1:08")]

        with mock.patch.object(brain, "_ask", side_effect=fake_ask), \
             mock.patch.object(brain, "_youtube_title", return_value="Shelby speech (Some Channel)"):
            post = brain.generate_post(link=link)
        self.assertEqual(calls[0][0], link)
        self.assertEqual(calls[1][0], "")
        self.assertIn("Shelby speech", calls[1][1])
        self.assertEqual(post["visual"]["best_moment"], "")  # it never watched the video, so no timestamp

    def test_failures_return_none_and_dont_retry_auth(self):
        with mock.patch.object(brain, "_ask", side_effect=RuntimeError("403 PERMISSION_DENIED")) as ask:
            self.assertIsNone(brain.generate_post())
            self.assertEqual(ask.call_count, 1)
        with mock.patch.object(brain, "_ask", side_effect=RuntimeError("429 RESOURCE_EXHAUSTED")), \
             mock.patch.object(brain.time, "sleep"):
            self.assertIsNone(brain.generate_post())

    def test_ai_switch_off(self):
        store.set_ai(False)
        with mock.patch.object(brain, "_ask") as ask:
            self.assertIsNone(brain.generate_post())
            ask.assert_not_called()

    def test_engine_falls_back_to_bank(self):
        with mock.patch.object(brain, "_ask", side_effect=RuntimeError("403 nope")):
            post = engine.build_post()
        self.assertEqual(post["quote_source"], "bank")

    def test_system_prompt_has_story_and_rules(self):
        s = brain.build_system()
        self.assertIn("Unseen", s)
        self.assertIn("HIS FULL STORY", s)
        self.assertIn("NEVER name any person", s)
        self.assertIn("NEVER glamorize", s)
        self.assertIn("thomas", s.lower())


class TestEngine(Base):
    def test_pillar_rotation_never_repeats(self):
        rng = random.Random(1)
        for last in [None] + list(config.PILLARS):
            prev = last
            for p in engine.pick_pillars(12, last, rng):
                self.assertNotEqual(p, prev)
                prev = p

    def test_daily_plan_distinct_times_sorted_and_saved(self):
        for _ in range(10):
            pkg = engine.build_package(date(2026, 10, 8), 3)
            times = [p["post_time"]["time"] for p in pkg["posts"]]
            self.assertEqual(times, sorted(times))
            self.assertEqual(len(set(times)), 3)
            self.assertEqual([p["post_number"] for p in pkg["posts"]], [1, 2, 3])
            self.assertEqual(len({p["pillar"] for p in pkg["posts"]}), 3)
        engine.generate_daily(3)
        self.assertEqual(store.posts_today(store.today()), 3)

    def test_many_offline_posts_have_everything(self):
        for _ in range(40):
            p = engine.build_post()
            for key in ("pillar", "format", "media", "on_screen_text", "post_caption", "hashtags", "visual", "post_time"):
                self.assertIn(key, p)
            self.assertIn(p["media"], ("video", "photo", "carousel"))
            self.assertEqual(p["visual"]["duration_seconds"] == 0, p["media"] != "video")

    def test_render_html_escapes_and_links(self):
        p = engine.build_post()
        p["on_screen_text"] = ["a <b>tag</b> & more"]
        text = engine.render_post(p, html=True)
        self.assertIn("&lt;b&gt;tag&lt;/b&gt; &amp; more", text)
        self.assertIn('<a href="https://www.youtube.com/results?search_query=', text)
        self.assertIn("POST AT:", text)
        plain = engine.render_post(p)
        self.assertIn("youtube.com", plain)
        self.assertNotIn("<a ", plain)


class TestTiming(Base):
    def test_defaults_and_custom(self):
        self.assertEqual(timing.band_times()["late_night"], "21:30")
        self.assertTrue(timing.set_band_times(["7:30", "12:00", "18:00", "23:15"]))
        self.assertEqual(timing.band_times()["morning"], "07:30")
        self.assertEqual(timing.post_time("late_night")["time"], "23:15")
        self.assertFalse(timing.set_band_times(["07:30", "12:00"]))
        self.assertFalse(timing.set_band_times(["07:30", "12:00", "18:00", "25:99"]))
        self.assertEqual(timing.post_time("nonsense")["band"], "evening")

    def test_label(self):
        self.assertTrue(timing.post_time("late_night")["label"].startswith("9:30 PM"))


class TestTrendsPersonaStore(Base):
    def test_trends_roundtrip_and_staleness(self):
        self.assertEqual(trends.get(), "")
        trends.set_manual("SOUNDS: snowfall - oneheart")
        self.assertIn("snowfall", trends.get())
        old = time.time() - 8 * 86400
        os.utime(trends._path(), (old, old))
        self.assertEqual(trends.get(), "")
        ok, msg = trends.refresh()
        self.assertFalse(ok)  # Gemini off

    def test_persona(self):
        ctx = persona.context()
        self.assertIn("HIS FULL STORY", ctx)
        self.assertTrue(persona.add_extra("I go quiet when I'm hurting")[0])
        self.assertIn("I go quiet", persona.context())
        persona.clear_extra()
        self.assertEqual(persona.get_extra(), "")
        self.assertFalse(persona.add_extra("   ")[0])

    def test_store(self):
        self.assertEqual(store.get_run_time(), config.RUN_TIME)
        store.set_run_time("07:45")
        self.assertEqual(store.get_run_time(), "07:45")
        self.assertTrue(store.ai_enabled())
        store.set_ai(False)
        self.assertFalse(store.ai_enabled())
        pid = store.remember_post({"pillar": "alone"})
        self.assertEqual(store.get_post(pid)["pillar"], "alone")
        self.assertEqual(store.recent_posts(1)[0]["pillar"], "alone")
        self.assertIsNone(store.get_post("nope00"))


class TestInsights(Base):
    def test_parse_metrics(self):
        p = insights.parse_metrics
        self.assertEqual(p("12400 830 95 210 62%"),
                         {"views": 12400, "likes": 830, "shares": 95, "saves": 210, "watch_pct": 62})
        self.assertEqual(p("12.4k views, 95 shares, 210 saves")["views"], 12400)
        self.assertEqual(p("views 1,200 likes 80")["likes"], 80)
        self.assertEqual(p("1.2m 5k 300 900")["views"], 1_200_000)
        self.assertEqual(p("500")["views"], 500)
        self.assertIsNone(p("830 12400 95"))        # likes > views
        self.assertIsNone(p("1000 10 5 5 150"))     # watch% over 100
        self.assertIsNone(p("no numbers here"))
        self.assertTrue(insights.looks_like_numbers("12400 830 95"))
        self.assertFalse(insights.looks_like_numbers("make one about people who only text when they need something"))

    def test_ranking_and_gemini_summary(self):
        self.assertEqual(insights.summary_for_gemini(), "")
        self.assertIn("Nothing logged", insights.breakdown_text())
        views = [100, 5000, 800, 12000]
        for v in views:
            p = engine.build_post()
            pid = store.remember_post(p)
            store.save_result(pid, insights.row_from_post(p, pid, {"views": v, "likes": v // 10, "shares": v // 50,
                                                                    "saves": v // 20, "watch_pct": 50}))
        rows = insights.ranked()
        self.assertEqual([r["metrics"]["views"] for r in rows], [12000, 5000, 800, 100])
        summary = insights.summary_for_gemini()
        self.assertIn("BEST:", summary)
        self.assertIn("WEAKEST:", summary)
        self.assertIn("12k views", summary)
        self.assertEqual(insights.rank_of(rows[0]["post_id"]), (1, 4))
        text = insights.breakdown_text()
        self.assertIn("4 posts logged", text)
        self.assertIn("By pillar", text)
        self.assertIn("Log at least 5", text)
        self.assertEqual(insights.fmt_num(1_250_000), "1.2M")

    def test_results_reach_gemini_prompt(self):
        for v in (100, 900, 7000):
            p = engine.build_post()
            pid = store.remember_post(p)
            store.save_result(pid, insights.row_from_post(p, pid, {"views": v, "likes": 1, "shares": 1,
                                                                    "saves": 1, "watch_pct": 0}))
        prompt = brain.build_prompt("", "", [], False, "")
        self.assertIn("RESULTS FROM THIS PAGE'S OWN POSTS", prompt)


class TestCapcut(Base):
    def test_every_format_and_media(self):
        seen = set()
        for _ in range(150):
            p = engine.build_post()
            text = capcut.steps(p)
            seen.add((p["format"], p["media"]))
            self.assertIn("1.", text)
            self.assertIn("Post it at", text)
            self.assertLess(len(text), 3800)
            if p["media"] == "video" and p["format"] != "interview":
                self.assertIn("Timing, second by second", text)
                self.assertIn(f"Trim to exactly {p['visual']['duration_seconds']}s", text)
                self.assertIn("Why ", text)
        self.assertTrue({("single", "video"), ("single", "photo"), ("split", "video"), ("interview", "video")} <= seen)

    def test_youtube_source_step(self):
        link = "https://www.youtube.com/watch?v=abcdefghijk"
        with mock.patch.object(config, "GEMINI_API_KEY", "x"), \
             mock.patch.object(brain, "_ask", return_value=[good_item(best_moment="0:42-0:50")]):
            post = brain.generate_post(link=link)
        post["post_number"] = 1
        text = capcut.steps(post)
        self.assertIn(link, text)
        self.assertIn("0:42-0:50", text)


if __name__ == "__main__":
    unittest.main()
