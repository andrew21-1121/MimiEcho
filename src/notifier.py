"""
Discord Notifier Module
Sends summarized post data to a Discord channel via Webhook using Embed format.
"""

import logging
from datetime import datetime, timezone

import requests

from .scraper import CafePost

logger = logging.getLogger(__name__)

# Discord limits
EMBED_DESCRIPTION_LIMIT = 4_096
EMBED_FIELD_VALUE_LIMIT = 1_024
DISCORD_COLOR_NAVER_GREEN = 0x03C75A


class DiscordNotifier:
    """
    Sends Discord Embed messages via a Webhook URL.

    Usage:
        notifier = DiscordNotifier(webhook_url="https://discord.com/api/webhooks/...")
        notifier.send(post, summary)
        notifier.send_error("Something went wrong")
    """

    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def send(self, post: CafePost, summary: str) -> None:
        """Send a single post summary as a Discord Embed."""
        logger.info("Sending Discord embed for post %d.", post.id)

        # Truncate summary if needed
        description = summary
        if len(description) > EMBED_DESCRIPTION_LIMIT:
            description = description[: EMBED_DESCRIPTION_LIMIT - 20] + "\n\n*(내용 일부 생략)*"

        embed = {
            "title": f"📝 {post.title}" if post.title else "📝 (제목 없음)",
            "url": post.url,
            "color": DISCORD_COLOR_NAVER_GREEN,
            "description": description,
            "fields": [
                {
                    "name": "✍️ 작성자",
                    "value": post.author or "알 수 없음",
                    "inline": True,
                },
                {
                    "name": "📅 작성일",
                    "value": post.date or "알 수 없음",
                    "inline": True,
                },
                {
                    "name": "🔗 원문 링크",
                    "value": f"[게시글 바로가기]({post.url})",
                    "inline": False,
                },
            ],
            "footer": {
                "text": "MimiEcho • 네이버 카페 자동 요약봇",
                "icon_url": "https://ssl.pstatic.net/static/cafe/cafe_pc/favicon/favicon.ico",
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        self._post_webhook(
            username="MimiEcho",
            content="",
            embeds=[embed],
        )

    def send_error(self, error_message: str) -> None:
        """Send an error notification embed to Discord."""
        logger.info("Sending error notification to Discord.")
        embed = {
            "title": "❌ MimiEcho 오류 발생",
            "description": f"```\n{error_message[:EMBED_DESCRIPTION_LIMIT - 10]}\n```",
            "color": 0xFF0000,
            "footer": {"text": "MimiEcho"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._post_webhook(username="MimiEcho", content="", embeds=[embed])

    def send_no_posts_notice(self) -> None:
        """Send a notice when no new posts are found (optional, informational)."""
        embed = {
            "title": "ℹ️ 새로운 게시글 없음",
            "description": "이번 주기에 새로운 게시글이 없습니다.",
            "color": 0xAAAAAA,
            "footer": {"text": "MimiEcho"},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._post_webhook(username="MimiEcho", content="", embeds=[embed])

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _post_webhook(self, username: str, content: str, embeds: list[dict]) -> None:
        payload = {
            "username": username,
            "content": content,
            "embeds": embeds,
        }
        response = requests.post(
            self.webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
        if response.status_code not in (200, 204):
            raise RuntimeError(
                f"Discord webhook returned {response.status_code}: {response.text}"
            )
        logger.debug("Discord webhook responded with %d.", response.status_code)
