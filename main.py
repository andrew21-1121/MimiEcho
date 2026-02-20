"""
MimiEcho — Main Entry Point

Workflow:
  1. Load state (last processed article ID)
  2. Scrape new posts from the configured Naver Cafe board
  3. Summarize each post with Claude AI
  4. Send summaries to Discord via Webhook
  5. Save updated state
"""

import logging
import os
import sys
import traceback

from dotenv import load_dotenv

from src.scraper import NaverCafeScraper, NaverLoginError, ClubIdResolutionError
from src.summarizer import AISummarizer
from src.notifier import DiscordNotifier

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(
            open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1, closefd=False)
        )
    ],
)
logger = logging.getLogger("MimiEcho")

# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------
STATE_FILE = "last_processed_id.txt"


def load_last_processed_id() -> int:
    """Read the last processed article ID from disk. Returns 0 if not found."""
    if os.path.exists(STATE_FILE):
        try:
            content = open(STATE_FILE).read().strip()
            return int(content) if content else 0
        except (ValueError, OSError):
            logger.warning("Could not read %s; defaulting to 0.", STATE_FILE)
    return 0


def save_last_processed_id(post_id: int) -> None:
    """Persist the highest processed article ID to disk."""
    with open(STATE_FILE, "w") as f:
        f.write(str(post_id))
    logger.info("State saved: last_processed_id = %d", post_id)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
def load_config() -> dict:
    """Load all required settings from environment variables."""
    load_dotenv()  # No-op in CI; reads .env locally

    required = {
        "CAFE_URL_NAME": "Naver Cafe URL name (e.g. daechi2dongchurch)",
        "CAFE_BOARD_ID": "Naver Cafe numeric board (menu) ID",
        "DISCORD_WEBHOOK_URL": "Discord Webhook URL",
        "ANTHROPIC_API_KEY": "Anthropic API key",
    }

    config = {}
    missing = []
    for key, description in required.items():
        value = os.environ.get(key, "").strip()
        if not value:
            missing.append(f"  {key}: {description}")
        config[key] = value

    if missing:
        logger.error("Missing required environment variables:\n%s", "\n".join(missing))
        sys.exit(1)

    # Auth: NAVER_COOKIES (preferred) or NAVER_ID + NAVER_PW fallback
    config["NAVER_COOKIES"] = os.environ.get("NAVER_COOKIES", "").strip()
    config["NAVER_ID"] = os.environ.get("NAVER_ID", "").strip()
    config["NAVER_PW"] = os.environ.get("NAVER_PW", "").strip()

    if not config["NAVER_COOKIES"] and not (config["NAVER_ID"] and config["NAVER_PW"]):
        logger.error(
            "Auth required: set NAVER_COOKIES (recommended) "
            "or both NAVER_ID and NAVER_PW."
        )
        sys.exit(1)

    return config


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    logger.info("=== MimiEcho starting ===")

    config = load_config()
    notifier = DiscordNotifier(config["DISCORD_WEBHOOK_URL"])

    try:
        # ── 1. State ───────────────────────────────────────────────────
        last_id = load_last_processed_id()
        logger.info("Last processed article ID: %d", last_id)

        # ── 2. Scrape ──────────────────────────────────────────────────
        scraper = NaverCafeScraper(
            naver_id=config["NAVER_ID"],
            naver_pw=config["NAVER_PW"],
            naver_cookies=config["NAVER_COOKIES"],
        )
        posts = scraper.get_new_posts(
            cafe_url_name=config["CAFE_URL_NAME"],
            board_id=config["CAFE_BOARD_ID"],
            last_id=last_id,
        )

        if not posts:
            logger.info("No new posts found. Sending notice.")
            notifier.send_no_posts_notice()
            return

        logger.info("Found %d new post(s) to process.", len(posts))

        # ── 3 & 4. Summarize + Notify ──────────────────────────────────
        summarizer = AISummarizer(api_key=config["ANTHROPIC_API_KEY"])
        max_processed_id = last_id
        errors = []

        for post in posts:
            try:
                summary = summarizer.summarize(post)
                notifier.send(post, summary)
                if post.id > max_processed_id:
                    max_processed_id = post.id
            except Exception as exc:
                logger.error("Failed to process post %d: %s", post.id, exc)
                errors.append(f"Post {post.id} ({post.title[:40]}): {exc}")
                # Still advance state past failed posts to avoid infinite retry
                if post.id > max_processed_id:
                    max_processed_id = post.id

        # ── 5. Save state ──────────────────────────────────────────────
        if max_processed_id > last_id:
            save_last_processed_id(max_processed_id)

        if errors:
            error_summary = "일부 게시글 처리 중 오류 발생:\n" + "\n".join(errors)
            notifier.send_error(error_summary)

    except NaverLoginError as exc:
        logger.critical("Login failed: %s", exc)
        notifier.send_error(f"네이버 로그인 실패:\n{exc}")
        sys.exit(1)

    except ClubIdResolutionError as exc:
        logger.critical("Club ID resolution failed: %s", exc)
        notifier.send_error(f"카페 ID 자동 감지 실패:\n{exc}")
        sys.exit(1)

    except Exception as exc:
        tb = traceback.format_exc()
        logger.critical("Unexpected error: %s\n%s", exc, tb)
        notifier.send_error(f"예상치 못한 오류:\n{exc}\n\n{tb[:500]}")
        sys.exit(1)

    logger.info("=== MimiEcho finished successfully ===")


if __name__ == "__main__":
    main()
