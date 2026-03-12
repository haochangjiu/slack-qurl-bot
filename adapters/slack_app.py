"""
Slack adapter for QURL proxy bot.

Uses core.bot_core for message processing; Slack Bolt for events and slash commands.
"""

import asyncio
import logging
import re

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from config import settings
from core.bot_core import (
    process_message,
    handle_setkey,
    handle_mykey,
    handle_delkey,
    preprocess_text,
    PLATFORM_SLACK,
)
from services.i18n import get_message
from services.time_utils import get_user_timezone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = AsyncApp(token=settings.slack_bot_token)


def _preprocess_slack(text: str) -> str:
    """Slack-specific preprocessing (links, etc.)."""
    return preprocess_text(text, PLATFORM_SLACK)


def _parse_command(text: str) -> tuple[str | None, str]:
    """
    Parse /setkey, /mykey, /delkey from message text.
    Returns (command_name, arg) e.g. ('setkey', 'xxx') or (None, '') if not a command.
    """
    t = text.strip()
    if t.startswith("/setkey"):
        arg = t[7:].strip()
        return ("setkey", arg)
    if t.startswith("/mykey"):
        return ("mykey", "")
    if t.startswith("/delkey"):
        return ("delkey", "")
    return (None, "")


# ============== Slash Commands ==============


@app.command("/setkey")
async def handle_setkey_slack(ack, command, say):
    await ack()
    user_id = command["user_id"]
    api_key = command["text"].strip()
    logger.info(f"Slack setkey from {user_id}: '{api_key[:12]}...' (len={len(api_key)})")
    msg, _ = await handle_setkey(user_id, api_key, PLATFORM_SLACK)
    await say(msg)


@app.command("/mykey")
async def handle_mykey_slack(ack, command, say, client):
    await ack()
    user_id = command["user_id"]
    user_tz = await get_user_timezone(client, user_id) if client else None
    msg, _ = await handle_mykey(user_id, PLATFORM_SLACK, user_tz=user_tz)
    await say(msg)


@app.command("/delkey")
async def handle_delkey_slack(ack, command, say):
    await ack()
    user_id = command["user_id"]
    msg, _ = await handle_delkey(user_id, PLATFORM_SLACK)
    await say(msg)


# ============== Message Events ==============


@app.event("app_mention")
async def handle_app_mention(event, say, client):
    text = event.get("text", "")
    user = event.get("user")
    clean_text = _preprocess_slack(text)
    if not clean_text:
        await say(f"<@{user}> {get_message('empty_input', 'en')}")
        return
    logger.info(f"Slack mention from {user}: {clean_text}")

    user_tz = await get_user_timezone(client, user) if client else None
    reply, _ = await process_message(clean_text, user, PLATFORM_SLACK, user_tz=user_tz)
    await say(f"<@{user}> {reply}")


@app.event("message")
async def handle_direct_message(event, say, client):
    if event.get("channel_type") != "im":
        return
    if event.get("subtype"):
        return
    if re.search(r"<@[A-Z0-9]+>", event.get("text", "")):
        return

    text = event.get("text", "")
    user = event.get("user")
    clean_text = _preprocess_slack(text)
    if not clean_text:
        await say(f"<@{user}> {get_message('empty_input', 'en')}")
        return
    logger.info(f"Slack DM from {user}: {clean_text}")

    user_tz = await get_user_timezone(client, user) if client else None
    reply, _ = await process_message(clean_text, user, PLATFORM_SLACK, user_tz=user_tz)
    await say(f"<@{user}> {reply}")


@app.event("app_home_opened")
async def handle_app_home_opened(client, event):
    try:
        await client.views_publish(
            user_id=event["user"],
            view={
                "type": "home",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"{get_message('welcome_title', 'en')} / {get_message('welcome_title', 'zh')}",
                        },
                    },
                    {"type": "divider"},
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": get_message("welcome_body", "en"),
                        },
                    },
                    {"type": "divider"},
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": get_message("welcome_body", "zh"),
                        },
                    },
                ],
            },
        )
    except Exception as e:
        logger.warning(f"Failed to publish app home: {e}")


async def run_slack():
    """Run Slack bot. Blocks until shutdown."""
    handler = AsyncSocketModeHandler(app, settings.slack_app_token)
    logger.info("Starting Slack QURL Bot...")
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(run_slack())
