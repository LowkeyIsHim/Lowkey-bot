"""Central config. Everything comes from env vars with safe defaults."""
import logging
import logging.handlers
import os
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # .env is optional; real env vars still work
    pass

BASE_DIR = Path(__file__).resolve().parent.parent  # repo root
# Runtime data (used quotes, settings, saved packages, logs) lives OUTSIDE the git checkout when
# launched via app.py (it sets DATA_DIR), so a re-clone or pull never wipes it.
DATA_DIR = Path(os.getenv("DATA_DIR", str(BASE_DIR / "data")))
OUTPUT_DIR = DATA_DIR / "output"
USED_FILE = DATA_DIR / "used_quotes.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
LOG_DIR = DATA_DIR / "logs"


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# --- Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
OWNER_ID = _int("TELEGRAM_OWNER_ID", 0)  # only this Telegram user can use the bot
BOT_TZ = os.getenv("BOT_TZ", "Africa/Lagos")  # timezone for the daily schedule

# --- AI
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# --- Content
POSTS_PER_DAY = _int("POSTS_PER_DAY", 3)
RUN_TIME = os.getenv("RUN_TIME", "06:00")  # default daily time (change live with /settime)
NO_REPEAT_DAYS = _int("NO_REPEAT_DAYS", 30)
HASHTAGS_MIN = _int("HASHTAGS_MIN", 6)
HASHTAGS_MAX = _int("HASHTAGS_MAX", 9)

PAGE_HANDLE = "@im_just_lowkey"
PAGE_BIO = "Moving in silence ⚙️"

# Post formats (matched to the page's existing posts) and how often each is picked.
FORMAT_WEIGHTS = {"single": 0.50, "split": 0.35, "interview": 0.15}

MIN_WORDS = 6
MAX_WORDS = 30

PILLARS = {
    "defense": "Defense Mechanisms: detachment, laughing instead of crying, emotional numbness as a "
               "shield because vulnerability wasn't safe growing up.",
    "no_explanations": "No Explanations: letting people believe what they want, closing chapters "
                       "silently, never explaining yourself, doors that stay closed after betrayal.",
    "silence": "Moving in Silence: grinding alone, keeping business private, observing people's true "
               "nature without reacting, outgrowing fake connections, not being reachable all the time.",
    "alone": "Surviving Alone: you survived your lowest points with no safety net, so people's "
             "absence and silence can't break you.",
}
PILLAR_LABELS = {
    "defense": "Defense Mechanisms",
    "no_explanations": "No Explanations",
    "silence": "Moving in Silence",
    "alone": "Surviving Alone",
}

# Only truly cheesy stuff is banned. "grind", "vibe", "energy" are part of the page voice.
BANNED_PATTERN = (
    r"\b(sigma|alpha|manifest(?:ing)?|blessed|journey|hustle|king|queen|"
    r"rise and grind|never give up|believe in yourself)\b"
)


def ensure_dirs() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def setup_logging() -> None:
    """Log to stdout (shows in the Spaceify console) and a rotating file."""
    ensure_dirs()
    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    root = logging.getLogger()
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    fh = logging.handlers.RotatingFileHandler(
        LOG_DIR / "engine.log", maxBytes=500_000, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(sh)
    root.addHandler(fh)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # keep bot token out of request logs
