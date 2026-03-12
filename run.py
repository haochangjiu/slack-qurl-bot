"""
Unified entry point for QURL bot. Runs Slack and/or Discord based on configuration.
"""

import asyncio
import logging
import sys

from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def main():
    """Start enabled bot(s)."""
    tasks = []

    if settings.slack_bot_token and settings.slack_app_token:
        from adapters.slack_app import run_slack
        tasks.append(run_slack())
        logger.info("Slack bot enabled")
    elif settings.slack_bot_token or settings.slack_app_token:
        logger.warning("Both SLACK_BOT_TOKEN and SLACK_APP_TOKEN required for Slack; skipping")

    if settings.discord_token:
        from adapters.discord_bot import run_discord_async
        tasks.append(run_discord_async())
        logger.info("Discord bot enabled")

    if not tasks:
        logger.error(
            "No bot enabled. Configure at least one:\n"
            "  - Slack: SLACK_BOT_TOKEN + SLACK_APP_TOKEN\n"
            "  - Discord: DISCORD_TOKEN"
        )
        sys.exit(1)

    await asyncio.gather(*tasks)


if __name__ == "__main__":
    asyncio.run(main())
