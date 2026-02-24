import asyncio
import logging
import re

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler

from config import settings
from services.layerv import layerv_client
from services.ai_analyzer import ai_analyzer
from services.url_parser import extract_urls, normalize_url, is_valid_url
from services.i18n import get_message

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Slack app with Socket Mode
app = AsyncApp(token=settings.slack_bot_token)


def preprocess_slack_text(text: str) -> str:
    """
    Preprocess Slack message text.
    Convert Slack link format <http://url|display> to plain URL.
    """
    # Convert Slack links to plain URLs
    text = re.sub(r'<(https?://[^|>]+)\|[^>]+>', r'\1', text)
    text = re.sub(r'<(https?://[^>]+)>', r'\1', text)
    return text


@app.event("app_mention")
async def handle_app_mention(event, say):
    """Handle when bot is mentioned in a channel."""
    text = event.get("text", "")
    user = event.get("user")

    # Remove bot mention from text
    text = re.sub(r"<@[A-Z0-9]+>", "", text).strip()

    await process_message(text, user, say)


@app.event("message")
async def handle_direct_message(event, say):
    """Handle direct messages to the bot."""
    # Only process direct messages (no subtype means it's a regular message)
    if event.get("channel_type") != "im":
        return
    if event.get("subtype"):
        return

    text = event.get("text", "")
    user = event.get("user")

    await process_message(text, user, say)


async def process_message(text: str, user: str, say):
    """Process user message using Claude AI for semantic analysis."""
    # Default language
    lang = "en"

    if not text:
        await say(f"<@{user}> {get_message('empty_input', lang)}")
        return

    # Preprocess Slack text format
    clean_text = preprocess_slack_text(text)
    logger.info(f"Processing message from {user}: {clean_text}")

    try:
        # Use Claude AI for semantic analysis
        analysis = await ai_analyzer.analyze(clean_text)
        lang = analysis.language
        logger.info(
            f"AI analysis result: lang={lang}, urls={analysis.urls}, "
            f"wants_proxy={analysis.wants_proxy}, expires_in={analysis.expires_in}"
        )

        # Also extract URLs from text as fallback (handles Slack formatting)
        extracted_urls = extract_urls(text)

        # Merge URLs from AI analysis and regex extraction
        all_urls = list(set(analysis.urls + extracted_urls))

        if not all_urls:
            await say(f"<@{user}> {get_message('no_url_detected', lang)}")
            return

        if not analysis.wants_proxy:
            # User provided URL but didn't explicitly ask for proxy
            await say(
                f"<@{user}> {get_message('url_detected_no_proxy', lang, urls=', '.join(all_urls), example_url=all_urls[0])}"
            )
            return

        # Generate QURL for each URL
        results = []
        errors = []

        for url in all_urls:
            normalized_url = normalize_url(url)
            if not is_valid_url(normalized_url):
                errors.append(get_message("invalid_url", lang, url=normalized_url))
                continue

            try:
                qurl_response = await layerv_client.create_qurl(
                    target_url=normalized_url,
                    expires_in=analysis.expires_in,
                    description=analysis.reason or f"Generated via Slack bot for user {user}",
                )
                results.append({
                    "original_url": normalized_url,
                    "qurl_link": qurl_response.qurl_link,
                    "expires_at": qurl_response.expires_at,
                })
            except Exception as e:
                logger.error(f"Failed to create QURL for {normalized_url}: {e}")
                errors.append(get_message("failed_item", lang, url=normalized_url, error=str(e)))

        # Build response message
        response_parts = [f"<@{user}>"]

        if results:
            response_parts.append(get_message("proxy_generated_header", lang))
            for r in results:
                response_parts.append(
                    get_message(
                        "proxy_item",
                        lang,
                        original_url=r["original_url"],
                        qurl_link=r["qurl_link"],
                        expires_at=r["expires_at"],
                    )
                )

        if errors:
            response_parts.append(get_message("failed_header", lang))
            response_parts.extend([f"\n{e}" for e in errors])

        await say("".join(response_parts))

    except Exception as e:
        logger.error(f"Error processing message: {e}")
        await say(f"<@{user}> {get_message('processing_error', lang, error=str(e))}")


@app.event("app_home_opened")
async def handle_app_home_opened(client, event):
    """Update the App Home tab when user opens it."""
    try:
        # Default to showing both languages in App Home
        await client.views_publish(
            user_id=event["user"],
            view={
                "type": "home",
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": f"{get_message('welcome_title', 'en')} / {get_message('welcome_title', 'zh')}"
                        }
                    },
                    {
                        "type": "divider"
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": get_message("welcome_body", "en")
                        }
                    },
                    {
                        "type": "divider"
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": get_message("welcome_body", "zh")
                        }
                    }
                ]
            }
        )
    except Exception as e:
        logger.warning(f"Failed to publish app home: {e}")


async def main():
    """Start the bot."""
    handler = AsyncSocketModeHandler(app, settings.slack_app_token)
    logger.info("Starting Slack QURL Bot with Claude AI (multilingual support)...")
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
