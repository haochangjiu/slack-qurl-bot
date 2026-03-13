"""
Unified entry point for QURL bot. Runs Slack and/or Discord based on configuration.
On permission/configuration errors, the failing bot stops (no retry); the other keeps running.
"""

import asyncio
import logging
import sys

from config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def _format_bot_error(name: str, e: Exception) -> str:
    """Format error message for bot failure."""
    err_str = str(e)
    if "PrivilegedIntentsRequired" in type(e).__name__ or "privileged intents" in err_str.lower():
        return (
            f"Discord bot failed (missing privileged intents). "
            f"Enable 'Message Content Intent' at: https://discord.com/developers/applications/ "
            f"> Your App > Bot > Privileged Gateway Intents. Error: {e}"
        )
    if "invalid" in err_str.lower() and "token" in err_str.lower():
        return f"{name} bot failed (invalid or expired token). Check configuration. Error: {e}"
    if "missing" in err_str.lower() and "scope" in err_str.lower():
        return f"{name} bot failed (missing OAuth scope). Add required scopes and reinstall. Error: {e}"
    return f"{name} bot failed: {e}"


async def _run_slack_safe():
    """Run Slack bot; catch errors, log, and stop without retry."""
    try:
        from adapters.slack_app import run_slack
        await run_slack()
    except Exception as e:
        logger.error(_format_bot_error("Slack", e))
        logger.error("Slack bot has stopped and will not retry. Fix configuration and restart the service.")


async def _run_discord_safe():
    """Run Discord bot; catch errors, log, and stop without retry."""
    try:
        from adapters.discord_bot import run_discord_async
        await run_discord_async()
    except Exception as e:
        logger.error(_format_bot_error("Discord", e))
        logger.error("Discord bot has stopped and will not retry. Fix configuration and restart the service.")


async def main():
    """Start enabled bot(s). One failure does not affect the other."""
    tasks = []

    if settings.slack_bot_token and settings.slack_app_token:
        tasks.append(_run_slack_safe())
        logger.info("Slack bot enabled")
    elif settings.slack_bot_token or settings.slack_app_token:
        logger.warning("Both SLACK_BOT_TOKEN and SLACK_APP_TOKEN required for Slack; skipping")

    if settings.discord_token:
        tasks.append(_run_discord_safe())
        logger.info("Discord bot enabled")

    if not tasks:
        logger.error(
            "No bot enabled. Configure at least one:\n"
            "  - Slack: SLACK_BOT_TOKEN + SLACK_APP_TOKEN\n"
            "  - Discord: DISCORD_TOKEN"
        )
        sys.exit(1)

    # return_exceptions=True: one bot failing does not cancel the other
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for i, r in enumerate(results):
        if isinstance(r, Exception):
            logger.error(f"Bot task {i + 1} exited with: {r}")
    if any(isinstance(r, Exception) for r in results):
        # At least one failed; if all failed, exit. Otherwise keep process alive for the running bot.
        if all(isinstance(r, Exception) for r in results):
            sys.exit(1)
