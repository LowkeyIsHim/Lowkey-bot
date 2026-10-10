# @im_just_lowkey content bot

Telegram bot that builds posts for the page. Gemini decides everything for each post: pillar, format
(single / split / interview), photo vs video, the text, clip, sound, hashtags, length and best time to post.
A local bank of original lines is the fallback when Gemini is off or fails. Nothing repeats within 30 days,
and nothing too close to a post already on the page (see `lowkey/seed.py`).

KEEP THIS REPO PRIVATE: `lowkey/persona.py` holds the owner's full story, which Gemini reads on every post.

## Layout
    lowkey/
      config.py     env vars, pillars, paths
      persona.py    who is behind the page (full story + rules for using it)
      brain.py      Gemini: decides and validates the whole post (also YouTube link + idea input)
      quotes.py     local bank, validation, no-repeat tracking
      visuals.py    clip library, sounds, edit helpers (fallback + repair)
      captions.py   caption line, hashtag pools, on-screen text layout
      timing.py     best-time bands
      insights.py   results log: parses your stats, ranks posts, tells Gemini what wins
      trends.py     trending sounds/hashtags notes (Gemini search or pasted)
      insights.py   logs your post results and tells Gemini what wins
      capcut.py     per-post CapCut steps with exact seconds
      engine.py     builds posts/plans and renders them (no Telegram in here)
      store.py      settings, saved plans, recent posts
      bot.py        Telegram menu, buttons, daily plan
      seed.py       texts of posts already on the page (never repeated)
    tests/          python -m unittest discover -s tests

## Using the bot
Send /start for the menu. Tap New post, or just type an idea ("something about fake friends"),
or paste a YouTube link and it builds the post around that clip. Under every post: CapCut steps, Log results (views, likes, shares, saves, watch %), Another, Menu.
The Results screen shows what's working, and Gemini uses your best and weakest posts on the next ones.
Commands: /menu /post [idea] /daily /persona /trends /besttimes /settime /update /myid

## Setup
1. @BotFather -> /newbot -> copy the token.
2. Env vars (see `.env.example`): TELEGRAM_BOT_TOKEN, GEMINI_API_KEY, BOT_TZ.
3. Message the bot /start, copy your ID, set TELEGRAM_OWNER_ID, restart. Only you can use it.
4. Deploy: upload `app.py` (the launcher) to Spaceify with REPO_URL set. /update pulls new code.

## Local test (no Telegram needed)
    pip install -r requirements.txt
    python -m lowkey --preview --offline

## Notes
- Runtime data lives in DATA_DIR (app.py points it outside the repo so pulls never wipe it).
- The bot gives clip search links and edit notes, not footage. Interview posts only get a hook line;
  use the clip's own subtitles.
- Gemini can't see live TikTok trends on its own. /trends refreshes notes with Gemini search or you paste yours.
  Always check a suggested sound exists before using it.
