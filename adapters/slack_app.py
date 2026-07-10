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
    analyze_message,
    build_proxy_reply,
    _dashboard_reply,
    detect_language,
    handle_setkey,
    handle_mykey,
    handle_delkey,
    preprocess_text,
    PLATFORM_SLACK,
)
from services.i18n import get_message
from services.url_parser import extract_urls
from services.web_summary import WebSummaryError, WebSummaryResult, web_summary_service

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
    if t.startswith("/summary"):
        arg = t[8:].strip()
        return ("summary", arg)
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
    user_info = await _get_slack_user_info(client, user_id)
    msg, _ = await handle_mykey(user_id, PLATFORM_SLACK, user_tz=user_info["tz"])
    await say(msg)


@app.command("/delkey")
async def handle_delkey_slack(ack, command, say):
    await ack()
    user_id = command["user_id"]
    msg, _ = await handle_delkey(user_id, PLATFORM_SLACK)
    await say(msg)


@app.command("/summary")
async def handle_summary_slack(ack, command, say, client):
    await ack()
    user_id = command["user_id"]
    text = command["text"].strip()
    user_info = await _get_slack_user_info(client, user_id)
    lang = _preferred_lang(user_info, text)
    msg = await _build_summary_message(text, lang)
    await say(f"<@{user_id}> {msg}")


# ============== Message Events ==============


_bot_user_id: str | None = None


async def _get_bot_user_id(client) -> str:
    global _bot_user_id
    if _bot_user_id is None:
        auth = await client.auth_test()
        _bot_user_id = auth["user_id"]
    return _bot_user_id


async def _get_slack_user_info(client, user_id: str) -> dict:
    """Get timezone and email from a single users_info call."""
    info: dict = {"tz": None, "email": None, "locale": None}
    if not client:
        return info
    try:
        response = await client.users_info(user=user_id, include_locale=True)
        if response.get("ok") and response.get("user"):
            user_data = response["user"]
            info["tz"] = user_data.get("tz")
            info["email"] = user_data.get("profile", {}).get("email")
            info["locale"] = user_data.get("locale")
    except Exception as e:
        logger.warning(f"Failed to get user info for {user_id}: {e}")
    return info


async def _send_dm(client, user: str, text: str):
    """Open a DM channel with the user and send a message."""
    resp = await client.conversations_open(users=user)
    dm_channel = resp["channel"]["id"]
    await client.chat_postMessage(channel=dm_channel, text=text)


def _extract_slack_mentions(text: str) -> list[str]:
    """Extract user IDs from Slack <@UXXXX> mentions."""
    return re.findall(r"<@([A-Z0-9]+)>", text)


def _preferred_lang(user_info: dict | None, text: str) -> str:
    locale = str((user_info or {}).get("locale") or "").lower()
    if locale.startswith("zh"):
        return "zh"
    return detect_language(text)


def _format_summary_result(result: WebSummaryResult, lang: str) -> str:
    parts = [
        get_message("summary_result_header", lang),
        get_message("summary_result_url", lang, url=result.url),
        get_message("summary_result_title", lang, title=result.title),
        get_message("summary_result_summary", lang, summary=result.summary),
    ]
    if result.bullets:
        parts.append(get_message("summary_result_bullets_header", lang))
        parts.extend(get_message("summary_result_bullet", lang, item=item) for item in result.bullets)
    if result.warning:
        parts.append(get_message("summary_result_warning", lang, warning=result.warning))
    if result.truncated:
        parts.append(get_message("summary_result_truncated", lang))
    return "\n".join(parts)


async def _build_summary_message(text: str, lang: str) -> str:
    urls = [
        url.rstrip(".,;:!?)]}，。！？；：")
        for url in extract_urls(text)
    ]
    if not urls:
        return get_message("summary_url_required", lang)
    if len(urls) > 1:
        return get_message("summary_single_url_only", lang)

    try:
        result = await web_summary_service.summarize_url(urls[0], lang=lang)
    except WebSummaryError as e:
        if e.message_key in {"summary_fetch_failed", "summary_processing_error"}:
            return get_message(e.message_key, lang, error=e.detail or "Unknown error")
        return get_message(e.message_key, lang)

    return _format_summary_result(result, lang)


@app.event("app_mention")
async def handle_app_mention(event, say, client):
    text = event.get("text", "")
    user = event.get("user")

    bot_id = await _get_bot_user_id(client)
    mentioned_users = [
        uid for uid in _extract_slack_mentions(text)
        if uid != bot_id
    ]

    clean_text = _preprocess_slack(text)
    if not clean_text:
        await say(f"<@{user}> {get_message('empty_input', 'en')}")
        return

    user_info = await _get_slack_user_info(client, user)
    user_tz = user_info["tz"]
    if user_info["email"]:
        logger.info(f"Slack request from {user} (email: {user_info['email']}): {clean_text}")
    else:
        logger.info(f"Slack mention from {user}: {clean_text}")

    cmd, arg = _parse_command(clean_text)
    if cmd:
        if cmd == "setkey":
            msg, _ = await handle_setkey(user, arg, PLATFORM_SLACK)
        elif cmd == "mykey":
            msg, _ = await handle_mykey(user, PLATFORM_SLACK, user_tz=user_tz)
        elif cmd == "summary":
            lang = _preferred_lang(user_info, clean_text)
            msg = await _build_summary_message(arg, lang)
        else:  # delkey
            msg, _ = await handle_delkey(user, PLATFORM_SLACK)
        await say(f"<@{user}> {msg}")
        return

    # Analyze once (AI + URL extraction)
    analysis = await analyze_message(clean_text, user, PLATFORM_SLACK)
    if "dashboard" in analysis:
        await say(f"<@{user}> {_dashboard_reply(analysis['lang'])}")
        return
    if "error" in analysis:
        await say(f"<@{user}> {analysis['error']}")
        return

    lang = analysis["lang"]
    dm_targets = mentioned_users if mentioned_users else [user]

    success = []
    for target in dm_targets:
        reply, _ = await build_proxy_reply(
            analysis["urls"], analysis["api_key"], analysis["expires_in"],
            analysis["reason"], lang, PLATFORM_SLACK, user, user_tz=user_tz,
        )
        try:
            if target == user:
                await _send_dm(client, target, reply)
            else:
                target_info = await _get_slack_user_info(client, target)
                if target_info["email"]:
                    logger.info(f"Sending proxy to {target} (email: {target_info['email']})")
                header = get_message("dm_proxy_for_you", lang, from_user=f"<@{user}>")
                await _send_dm(client, target, f"{header}\n{reply}")
            success.append(target)
        except Exception as e:
            logger.warning(f"Cannot DM Slack user {target}: {e}")

    if success:
        if mentioned_users:
            mentions = " ".join(f"<@{u}>" for u in success)
            await say(f"<@{user}> {get_message('dm_sent_to_users', lang, users=mentions)}")
        else:
            await say(f"<@{user}> {get_message('dm_sent', lang)}")
    else:
        await say(f"<@{user}> {get_message('dm_failed', lang)}")


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

    user_info = await _get_slack_user_info(client, user)
    if user_info["email"]:
        logger.info(f"Slack DM from {user} (email: {user_info['email']}): {clean_text}")
    else:
        logger.info(f"Slack DM from {user}: {clean_text}")

    cmd, arg = _parse_command(clean_text)
    if cmd:
        if cmd == "setkey":
            msg, _ = await handle_setkey(user, arg, PLATFORM_SLACK)
        elif cmd == "mykey":
            msg, _ = await handle_mykey(user, PLATFORM_SLACK, user_tz=user_info["tz"])
        elif cmd == "summary":
            lang = _preferred_lang(user_info, clean_text)
            msg = await _build_summary_message(arg, lang)
        else:
            msg, _ = await handle_delkey(user, PLATFORM_SLACK)
        await say(f"<@{user}> {msg}")
        return

    reply, _ = await process_message(clean_text, user, PLATFORM_SLACK, user_tz=user_info["tz"])
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
        err_str = str(e)
        if "not_enabled" in err_str.lower():
            logger.debug(
                "App Home not enabled. Enable at: https://api.slack.com/apps > Your App > App Home"
            )
        else:
            logger.warning(f"Failed to publish app home: {e}")


async def run_slack():
    """Run Slack bot. Blocks until shutdown."""
    handler = AsyncSocketModeHandler(app, settings.slack_app_token)
    logger.info("Starting Slack QURL Bot...")
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(run_slack())
