"""
Platform-agnostic bot logic for QURL proxy generation.

Handles message analysis, URL extraction, QURL creation.
Returns message content to be sent - each platform adapter formats & sends.
"""

import logging
import re

from config import settings
from services.layerv import layerv_client, InvalidApiKeyError
from services.ai_analyzer import ai_analyzer
from services.url_parser import extract_urls, normalize_url, is_valid_url
from services.i18n import get_message
from services.user_store import user_store
from services.time_utils import format_utc_to_local

logger = logging.getLogger(__name__)

PLATFORM_SLACK = "slack"
PLATFORM_DISCORD = "discord"


def _key_id(platform: str, raw_id: str) -> str:
    """Get storage key ID for Discord (per-user)."""
    return f"{platform}:{raw_id}"


def _get_api_key(platform: str, user_id: str) -> str | None:
    """Get API key. Slack reads from .env; Discord from per-user store."""
    if platform == PLATFORM_SLACK:
        return settings.layerv_api_key
    return user_store.get_api_key(_key_id(platform, user_id))


def _has_api_key(platform: str, user_id: str) -> bool:
    if platform == PLATFORM_SLACK:
        return bool(settings.layerv_api_key)
    return user_store.has_api_key(_key_id(platform, user_id))


def preprocess_text(text: str, platform: str) -> str:
    """
    Preprocess message text for platform-specific formats.

    - Slack: <http://url|display> or <@USER> mentions
    - Discord: <@!123> mentions, similar link formats
    """
    # Slack link format
    text = re.sub(r"<(https?://[^|>]+)\|[^>]+>", r"\1", text)
    text = re.sub(r"<(https?://[^>]+)>", r"\1", text)
    # Slack mentions: <@U123ABC>
    text = re.sub(r"<@[A-Z0-9]+>", "", text)
    # Discord mentions: <@!123456> or <@123456>
    text = re.sub(r"<@!?\d+>", "", text)
    return text.strip()


def detect_language(text: str) -> str:
    """Simple language detection based on character analysis."""
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    return "en"


async def process_message(
    text: str,
    user_id: str,
    platform: str,
    user_tz: str | None = None,
) -> tuple[str, str]:
    """
    Core message processing logic. Platform-agnostic.

    Args:
        text: User message content (after preprocessing)
        user_id: Raw platform user ID (Slack U123 or Discord snowflake)
        platform: "slack" or "discord"
        user_tz: IANA timezone for expiry display (e.g. "Asia/Shanghai"), optional

    Returns:
        (message_to_send, language)
    """
    lang = "en"

    if not text:
        return f"{get_message('empty_input', lang)}", lang

    if not _has_api_key(platform, str(user_id)):
        lang = detect_language(text)
        no_key_msg = "no_api_key_env" if platform == PLATFORM_SLACK else "no_api_key"
        return get_message(no_key_msg, lang), lang

    try:
        analysis = await ai_analyzer.analyze(text)
        lang = analysis.language

        logger.info(
            f"AI analysis: lang={lang}, urls={analysis.urls}, "
            f"expires_in={analysis.expires_in}"
        )

        extracted_urls = extract_urls(text)
        combined = analysis.urls + extracted_urls
        normalized = [normalize_url(u) for u in combined]
        all_urls = list(dict.fromkeys(normalized))

        if not all_urls:
            return get_message("no_url_detected", lang), lang

        api_key = _get_api_key(platform, str(user_id))
        if not api_key:
            no_key_msg = "no_api_key_env" if platform == PLATFORM_SLACK else "no_api_key"
            return get_message(no_key_msg, lang), lang

        results = []
        errors = []

        for url in all_urls:
            if not is_valid_url(url):
                errors.append(get_message("invalid_url", lang, url=url))
                continue

            try:
                qurl_response = await layerv_client.create_qurl(
                    api_key=api_key,
                    target_url=url,
                    expires_in=analysis.expires_in,
                    description=analysis.reason
                    or f"Generated via {platform} bot for user {user_id}",
                )
                results.append(
                    {
                        "original_url": url,
                        "qurl_link": qurl_response.qurl_link,
                        "expires_at": format_utc_to_local(
                            qurl_response.expires_at,
                            user_tz=user_tz,
                        ),
                    }
                )
            except InvalidApiKeyError:
                logger.error(f"Invalid API key for {platform}:{user_id}")
                return get_message("invalid_api_key", lang), lang
            except Exception as e:
                logger.error(f"Failed to create QURL for {url}: {e}")
                errors.append(get_message("failed_item", lang, url=url, error=str(e)))

        parts = []
        if results:
            parts.append(get_message("proxy_generated_header", lang))
            for r in results:
                parts.append(
                    get_message(
                        "proxy_item",
                        lang,
                        original_url=r["original_url"],
                        qurl_link=r["qurl_link"],
                        expires_at=r["expires_at"],
                    )
                )
        if errors:
            parts.append(get_message("failed_header", lang))
            parts.extend([f"\n{e}" for e in errors])

        return "".join(parts), lang

    except Exception as e:
        logger.error(f"Error processing message: {e}")
        return get_message("processing_error", lang, error=str(e)), lang


async def handle_setkey(user_id: str, api_key: str, platform: str) -> tuple[str, str]:
    """Handle /setkey command. Returns (message, lang)."""
    lang = "en"
    if platform == PLATFORM_SLACK:
        return get_message("slack_cmd_disabled", lang), lang

    kid = _key_id(platform, str(user_id))
    if not api_key:
        return get_message("setkey_usage", lang), lang

    try:
        user_store.set_api_key(kid, api_key)
        return get_message("setkey_success", lang), lang
    except Exception as e:
        logger.error(f"Error setting API key ({kid}): {e}")
        return get_message("setkey_error", lang, error=str(e)), lang


async def handle_mykey(
    user_id: str,
    platform: str,
    user_tz: str | None = None,
) -> tuple[str, str]:
    """Handle /mykey command. Returns (message, lang)."""
    lang = "en"

    if platform == PLATFORM_SLACK:
        key = settings.layerv_api_key
        if key:
            prefix = key[:8] + "..." if len(key) > 8 else key
            return get_message("slack_mykey_info", lang, prefix=prefix), lang
        return get_message("no_api_key_env", lang), lang

    kid = _key_id(platform, str(user_id))
    key_info = user_store.get_key_info(kid)
    if key_info:
        created_at = (
            format_utc_to_local(key_info["created_at"], user_tz=user_tz)
            if key_info.get("created_at")
            else key_info.get("created_at", "-")
        )
        return (
            get_message(
                "mykey_info",
                lang,
                prefix=key_info["api_key_prefix"],
                created_at=created_at,
            ),
            lang,
        )
    return get_message("mykey_none", lang), lang


async def handle_delkey(user_id: str, platform: str) -> tuple[str, str]:
    """Handle /delkey command. Returns (message, lang)."""
    lang = "en"
    if platform == PLATFORM_SLACK:
        return get_message("slack_cmd_disabled", lang), lang

    kid = _key_id(platform, str(user_id))
    if user_store.delete_api_key(kid):
        return get_message("delkey_success", lang), lang
    return get_message("delkey_none", lang), lang
