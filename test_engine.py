"""Engine tests (no Telegram, no network). Run: python -m unittest discover -s tests -v"""
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from lowkey import config, engine, quotes, store


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
        ok = quotes.Quote("silence", "single", ["I keep my business to myself and my circle small."])
        self.assertTrue(quotes.validate(ok))
        self.assertTrue(quotes.validate(quotes.Quote("silence", "single", ["Working in silence is the whole point of it."])))  # 'king' inside 'working' is fine
        self.assertFalse(quotes.validate(quotes.Quote("silence", "single", ["Be a king and rise and grind every day."])))
        self.assertFalse(quotes.validate(quotes.Quote("silence", "single", ["Quiet moves only 🔥 keep it moving always."])))
        self.assertFalse(quotes.validate(quotes.Quote("silence", "single", ["Too short."])))
        self.assertFalse(quotes.validate(quotes.Quote("silence", "single", [" ".join(["word"] * 40)])))


class TestGeneration(Base):
    def test_pillar_rotation_never_repeats(self):
        rng = random.Random(1)
        for last in [None] + list(config.PILLARS):
            seq = engine.pick_pillars(12, last, rng)
            prev = last
            for p in seq:
                self.assertNotEqual(p, prev)
                prev = p

    def test_no_repeats_then_graceful_reuse(self):
        rng = random.Random(2)
        texts = [quotes.get_quote("alone", "single", rng).text for _ in range(8)]
        self.assertEqual(len(set(texts)), 8)
        self.assertTrue(quotes.get_quote("alone", "single", rng).text)  # bank exhausted: reuses oldest, no crash

    def test_many_posts_all_fields(self):
        for _ in range(40):
            p = engine.build_post()
            for key in ("pillar", "format", "on_screen_text", "post_caption", "hashtags", "visual"):
                self.assertIn(key, p)
            self.assertTrue(3 <= len([t for t in p["hashtags"] if t in ("#movinginsilence", "#stoicism", "#lowkey")]))
            self.assertTrue(config.HASHTAGS_MIN <= len(p["hashtags"]) <= config.HASHTAGS_MAX + 2)

    def test_daily_package_saved(self):
        pkg = engine.generate_daily(3)
        self.assertEqual(len(pkg["posts"]), 3)
        self.assertTrue(store.has_package(store.today()))
        self.assertEqual(store.posts_today(store.today()), 3)

    def test_gemini_success_and_fallback(self):
        quotes_mod = quotes
        good = quotes.Quote("silence", "single", ["Nobody asks what the quiet cost me, and I never offer."], "gemini")
        with mock.patch.object(config, "GEMINI_API_KEY", "x"), \
             mock.patch.object(quotes_mod, "_gemini_candidates", return_value=[good]):
            self.assertEqual(quotes.get_quote("silence", "single", random.Random()).source, "gemini")
        with mock.patch.object(config, "GEMINI_API_KEY", "x"), \
             mock.patch.object(quotes_mod, "_gemini_candidates", side_effect=RuntimeError("429 RESOURCE_EXHAUSTED")), \
             mock.patch.object(quotes_mod.time, "sleep"):
            self.assertEqual(quotes.get_quote("silence", "single", random.Random()).source, "bank")
        with mock.patch.object(config, "GEMINI_API_KEY", "x"), \
             mock.patch.object(quotes_mod, "_gemini_candidates", side_effect=RuntimeError("403 PERMISSION_DENIED")) as m:
            self.assertEqual(quotes.get_quote("alone", "split", random.Random()).source, "bank")
            self.assertEqual(m.call_count, 1)  # auth errors are not retried

    def test_ai_toggle_skips_gemini(self):
        store.set_ai(False)
        with mock.patch.object(config, "GEMINI_API_KEY", "x"), \
             mock.patch.object(quotes, "_gemini_candidates") as m:
            quotes.get_quote("defense", "single", random.Random())
            m.assert_not_called()

    def test_gemini_duplicate_of_existing_post_rejected(self):
        dup = quotes.Quote("silence", "single", ["Notice how quiet it gets when you stop reaching out first."], "gemini")
        with mock.patch.object(config, "GEMINI_API_KEY", "x"), \
             mock.patch.object(quotes, "_gemini_candidates", return_value=[dup]), \
             mock.patch.object(quotes.time, "sleep"):
            self.assertEqual(quotes.get_quote("silence", "single", random.Random()).source, "bank")


class TestRenderAndStore(Base):
    def test_html_escapes(self):
        p = engine.build_post("alone", "single")
        p["on_screen_text"] = ["a <b>tag</b> & more"]
        text = engine.render_post(p, html=True)
        self.assertIn("&lt;b&gt;tag&lt;/b&gt; &amp; more", text)
        self.assertNotIn("<b>tag</b>", text)

    def test_settings_roundtrip(self):
        self.assertEqual(store.get_run_time(), config.RUN_TIME)
        store.set_run_time("07:45")
        self.assertEqual(store.get_run_time(), "07:45")
        self.assertTrue(store.ai_enabled())
        store.set_ai(False)
        self.assertFalse(store.ai_enabled())


if __name__ == "__main__":
    unittest.main()
