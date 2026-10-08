"""python -m lowkey            -> run the Telegram bot
python -m lowkey --preview  -> print today's plan to the console (no Telegram needed)
"""
import argparse

from . import config


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m lowkey")
    parser.add_argument("--preview", action="store_true", help="print a plan and exit (no Telegram)")
    parser.add_argument("--count", type=int, help="posts for --preview (default POSTS_PER_DAY)")
    parser.add_argument("--offline", action="store_true", help="skip Gemini, use the local bank only")
    args = parser.parse_args()

    if args.offline:
        config.GEMINI_API_KEY = ""
    if args.preview:
        from . import engine
        config.setup_logging()
        pkg = engine.generate_daily(args.count)
        print("\n" + ("\n\n" + "-" * 36 + "\n\n").join(engine.render_package(pkg)) + "\n")
    else:
        from .bot import run_bot
        run_bot()


if __name__ == "__main__":
    main()
