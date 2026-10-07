# @im_just_lowkey content bot

Telegram bot that generates posts for the page: on-screen text, caption + hashtags, clip search
keywords, edit notes, and sound. Gemini writes new lines in the page's voice; a local bank of
original lines is the fallback. Nothing repeats within 30 days, and nothing too close to a post
already on the page (see `lowkey/seed.py`).

## Layout
    lowkey/
      config.py     env vars, pillars, paths
      seed.py       texts of posts already on the page (never repeated)
      quotes.py     Gemini + local bank, validation, no-repeat tracking
      captions.py   caption line, hashtags, on-screen text layout
      visuals.py    clip library, sounds, edit direction
      engine.py     builds posts/packages, renders text (no Telegram in here)
      store.py      settings + saved packages
      bot.py        Telegram commands, buttons, daily schedule
      __main__.py   `python -m lowkey` (bot) or `--preview` (console)
    tests/          python -m unittest discover -s tests

## Setup
1. @BotFather -> /newbot -> copy the token.
2. Set env vars (see `.env.example`): TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, BOT_TZ.
3. Start it, message the bot /start, copy your ID, set TELEGRAM_OWNER_ID, restart. Only you can use it.
4. Deploy: upload `app.py` (the launcher, one level above this folder) to Spaceify with REPO_URL set.

## Commands
/post (pick a pillar) | /post alone | /post a interview | /daily | /settime 06:30 | /ai on|off | /status | /update

## Local test (no Telegram needed)
    pip install -r requirements.txt
    python -m lowkey --preview --offline

## Notes
- Runtime data lives in DATA_DIR (app.py points it outside the repo so pulls never wipe it).
- Film/interview footage is yours to source: the bot gives search keywords and edit notes, not clips.
  Interview posts only get a hook line; use the clip's own subtitles.
