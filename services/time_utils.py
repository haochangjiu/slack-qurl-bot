"""Time formatting with timezone support for Slack bot responses."""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

# Default format: YYYY-MM-DD HH:MM:SS
DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def format_utc_to_local(
    iso_utc_str: str,
    user_tz: str | None = None,
    include_tz_label: bool = True,
) -> str:
    """
    Convert UTC ISO 8601 string to localized display format.

    Args:
        iso_utc_str: UTC time in ISO 8601 format (e.g., "2026-03-11T09:16:14.792797654Z")
        user_tz: IANA timezone (e.g., "Asia/Shanghai") from Slack user.tz, or None for UTC
        include_tz_label: Whether to append timezone label like " (CST)" or " (UTC)"

    Returns:
        Formatted string like "2026-03-11 17:16:14 (CST)" or "2026-03-11 09:16:14 (UTC)"
    """
    try:
        # Parse ISO 8601 UTC string (e.g. 2026-03-11T09:16:14.792797654Z)
        parse_str = iso_utc_str.replace("Z", "+00:00").strip()
        dt_utc = datetime.fromisoformat(parse_str)
        if dt_utc.tzinfo is None:
            dt_utc = dt_utc.replace(tzinfo=ZoneInfo("UTC"))
    except (ValueError, TypeError) as e:
        logger.warning(f"Failed to parse datetime {iso_utc_str}: {e}")
        return iso_utc_str  # Return original on parse error

    tz_label = ""
    if user_tz:
        try:
            target_tz = ZoneInfo(user_tz)
            dt_local = dt_utc.astimezone(target_tz)
            if include_tz_label:
                tz_label = f" ({dt_local.strftime('%Z')})"
        except Exception as e:
            logger.warning(f"Invalid timezone {user_tz}: {e}, falling back to UTC")
            dt_local = dt_utc.astimezone(ZoneInfo("UTC"))
            if include_tz_label:
                tz_label = " (UTC)"
    else:
        dt_local = dt_utc.astimezone(ZoneInfo("UTC"))
        if include_tz_label:
            tz_label = " (UTC)"

    return dt_local.strftime(DATETIME_FORMAT) + tz_label


async def get_user_timezone(client, user_id: str) -> str | None:
    """
    Get user's timezone from Slack API.

    Args:
        client: Slack AsyncWebClient (from Bolt context)
        user_id: Slack user ID

    Returns:
        IANA timezone string (e.g., "Asia/Shanghai") or None
    """
    if not client:
        logger.warning(f"No Slack client available, cannot get timezone for {user_id}")
        return None
    try:
        response = await client.users_info(user=user_id)
        if response.get("ok") and response.get("user"):
            tz = response["user"].get("tz")
            tz_offset = response["user"].get("tz_offset")
            logger.info(f"User {user_id} timezone: tz={tz}, tz_offset={tz_offset}")
            return tz
        else:
            logger.warning(f"users_info response not ok for {user_id}: {response.get('error', 'unknown')}")
    except Exception as e:
        logger.warning(f"Failed to get user timezone for {user_id}: {e}")
    return None


# Discord locale (e.g. "zh-CN", "en-US") to IANA timezone mapping.
# Discord does not expose user timezone; we infer from locale.
DISCORD_LOCALE_TO_TZ: dict[str, str] = {
    "zh-CN": "Asia/Shanghai",
    "zh-TW": "Asia/Taipei",
    "zh-HK": "Asia/Hong_Kong",
    "ja": "Asia/Tokyo",
    "ko": "Asia/Seoul",
    "en-US": "America/New_York",
    "en-GB": "Europe/London",
    "de": "Europe/Berlin",
    "fr": "Europe/Paris",
    "es": "Europe/Madrid",
    "it": "Europe/Rome",
    "pt-BR": "America/Sao_Paulo",
    "ru": "Europe/Moscow",
    "hi": "Asia/Kolkata",
    "th": "Asia/Bangkok",
    "vi": "Asia/Ho_Chi_Minh",
    "id": "Asia/Jakarta",
    "tr": "Europe/Istanbul",
    "pl": "Europe/Warsaw",
    "nl": "Europe/Amsterdam",
    "sv": "Europe/Stockholm",
    "da": "Europe/Copenhagen",
    "fi": "Europe/Helsinki",
    "no": "Europe/Oslo",
    "cs": "Europe/Prague",
    "hu": "Europe/Budapest",
    "ro": "Europe/Bucharest",
    "bg": "Europe/Sofia",
    "uk": "Europe/Kiev",
    "el": "Europe/Athens",
}


def get_timezone_from_discord_locale(locale: str | None) -> str | None:
    """
    Map Discord user locale to IANA timezone.

    Args:
        locale: Discord locale (e.g., "zh-CN", "en-US")

    Returns:
        IANA timezone string or None
    """
    if not locale:
        return None
    return DISCORD_LOCALE_TO_TZ.get(locale)
