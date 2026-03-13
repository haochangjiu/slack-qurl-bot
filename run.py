"""
Unified entry point for QURL bot. Runs Slack and/or Discord based on configuration.
Each bot runs independently: if one fails, the other keeps running.
The process stays alive as long as at least one bot is still running.
"""

import asyncio
import logging
import sys

from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _format_bot_error(name: str, e: Exception) -> str:
    """Format a human-friendly error message."""
    err_type = type(e).__name__
    err_str = str(e)
    if "PrivilegedIntentsRequired" in err_type or "privileged intents" in err_str.lower():
        return (
            f"[Discord] Missing privileged intents. "
            f"Go to https://discord.com/developers/applications/ > Your App > Bot > "
            f"Privileged Gateway Intents > Enable 'Message Content Intent', then restart."
        )
    if "invalid" in err_str.lower() and "token" in err_str.lower():
        return f"[{name}] Invalid or expired token. Check .env configuration."
    if "missing" in err_str.lower() and "scope" in err_str.lower():
        return f"[{name}] Missing OAuth scope. Add required scopes and reinstall the app."
    return f"[{name}] {err_type}: {err_str}"


async def _run_slack_safe(running_bots: set):
    """Run Slack bot with error isolation."""
    running_bots.add("slack")
    try:
        from adapters.slack_app import run_slack
        await run_slack()
    except Exception as e:
        logger.error(_format_bot_error("Slack", e))
        logger.error("Slack bot has stopped. Fix the issue above and restart the service.")
    finally:
        running_bots.discard("slack")


async def _run_discord_safe(running_bots: set):
    """Run Discord bot with error isolation."""
    running_bots.add("discord")
    try:
        from adapters.discord_bot import run_discord_async
        await run_discord_async()
    except Exception as e:
        logger.error(_format_bot_error("Discord", e))
        logger.error("Discord bot has stopped. Fix the issue above and restart the service.")
    finally:
        running_bots.discard("discord")


async def _keep_alive(running_bots: set):
    """Keep process alive while at least one bot is running."""
    while running_bots:
        await asyncio.sleep(5)


async def main():
    """Start enabled bot(s). Each runs independently."""
    tasks = []
    running_bots: set[str] = set()

    if settings.slack_bot_token and settings.slack_app_token:
        tasks.append(asyncio.create_task(_run_slack_safe(running_bots)))
        logger.info("Slack bot enabled")
    elif settings.slack_bot_token or settings.slack_app_token:
        logger.warning("Both SLACK_BOT_TOKEN and SLACK_APP_TOKEN required for Slack; skipping")

    if settings.discord_token:
        tasks.append(asyncio.create_task(_run_discord_safe(running_bots)))
        logger.info("Discord bot enabled")

    if not tasks:
        logger.error(
            "No bot enabled. Configure at least one:\n"
            "  - Slack: SLACK_BOT_TOKEN + SLACK_APP_TOKEN\n"
            "  - Discord: DISCORD_TOKEN"
        )
        sys.exit(1)

    # Wait briefly for bots to start, then keep process alive while at least one is running
    await asyncio.sleep(1)
    await _keep_alive(running_bots)
    logger.error("All bots have stopped. Exiting.")
    sys.exit(1)
