"""
Resolve Google Maps short URLs (maps.app.goo.gl) to full embed URLs.

Flow:
  1. Follow HTTP redirect chain to resolve the short URL to a full maps.google.com URL.
  2. If a Maps Embed API key is available, call the Embed API to get the canonical place ID
     and reconstruct the embed URL as:
       https://www.google.com/maps/embed?pb=!1s<encoded_place_string>!...
     This format is stable and doesn't expire.
  3. Fall back to the resolved direct URL when no API key is configured.
"""

import logging
import re
from dataclasses import dataclass

import httpx

from config import settings

logger = logging.getLogger(__name__)


# Pattern to detect maps.app.goo.gl short links
GOOGLE_MAPS_SHORT_PATTERN = re.compile(
    r"https://maps\.app\.goo\.gl/[^\s<>)\]\"']+",
    re.IGNORECASE,
)

# Known direct Google Maps embed URL pattern
GOOGLE_MAPS_EMBED_PATTERN = re.compile(
    r"https://www\.google\.com/maps/embed[^\s<>)\]\"']+",
    re.IGNORECASE,
)


@dataclass
class ResolvedGoogleMap:
    original_url: str
    resolved_url: str | None  # After following redirects
    embed_url: str | None     # Stable embed URL (if resolved)
    is_embed: bool             # Whether original was already an embed URL


async def _fetch_with_redirects(url: str, timeout: float = 30.0) -> str | None:
    """
    Make a HEAD request following redirects to resolve the final URL.
    Falls back to GET if HEAD is not supported.
    Returns the final resolved URL (from the response URL), or None on failure.
    """
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
        ) as client:
            # Prefer HEAD to avoid downloading body
            try:
                resp = await client.head(url, allow_redirects=True)
            except httpx.UnsupportedProtocol:
                # Some servers reject HEAD; retry with GET
                resp = await client.get(url, allow_redirects=True)
            return str(resp.url)
    except Exception as e:
        logger.warning(f"Failed to resolve Google Maps URL {url}: {e}")
        return None


async def _call_embed_api(short_url: str, resolved_url: str) -> str | None:
    """
    Use Google Maps Embed API to get a stable embed URL from a resolved maps URL.

    Requires GOOGLE_MAPS_EMBED_API_KEY in config.
    Returns an embed URL like:
      https://www.google.com/maps/embed?pb=!1s...!2s...!3s...!...
    or None if the API is unavailable or fails.
    """
    api_key = getattr(settings, "google_maps_embed_api_key", None) or None
    if not api_key:
        return None

    # Extract the place query from the resolved URL
    # e.g. https://www.google.com/maps/place/... -> extract "..." part
    place_match = re.search(
        r"https://www\.google\.com/maps/([^?]+)",
        resolved_url,
        re.IGNORECASE,
    )
    if not place_match:
        return None

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
        ) as client:
            resp = await client.get(
                "https://www.google.com/maps/api/place/details/json",
                params={
                    "placeid": _extract_place_id(resolved_url) or "",
                    "key": api_key,
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                result = data.get("result", {})
                place_id = result.get("place_id")
                if place_id:
                    return f"https://www.google.com/maps/embed?pb=!1s{_encode_place_id(place_id)}"
    except Exception as e:
        logger.warning(f"Embed API call failed for {short_url}: {e}")

    return None


def _extract_place_id(url: str) -> str | None:
    """Extract place ID from a Google Maps URL (after /place/ or @... )."""
    # Pattern: /place/PLACE_ID/ or /data=...!2sPLACE_ID!...
    m = re.search(r"/place/([^/@?]+)/", url)
    if m:
        return m.group(1)
    # @lat,lng,zoom place: /@lat,lng,.../.../(PLACE_NAME)/...
    m = re.search(r"@[-0-9.,]+/[^/]+/([^/]+)/", url)
    if m:
        name = m.group(1)
        # If it looks like a place ID (starts with 0x...), return it
        if name.startswith("0x"):
            return name
    return None


def _encode_place_id(place_id: str) -> str:
    """URL-safe encode for embed URL place ID segment."""
    import base64
    import urllib.parse

    encoded = base64.urlsafe_b64encode(urllib.parse.unquote(place_id).encode("utf-8")).decode("utf-8")
    # Remove padding
    return encoded.rstrip("=")


async def resolve_google_map(url: str) -> ResolvedGoogleMap:
    """
    Resolve a Google Maps short URL (maps.app.goo.gl) or direct URL to a stable embed URL.

    Args:
        url: The Google Maps URL (short or direct)

    Returns:
        ResolvedGoogleMap with resolved direct URL and stable embed URL (if available).
    """
    is_embed = bool(GOOGLE_MAPS_EMBED_PATTERN.search(url))
    is_short = bool(GOOGLE_MAPS_SHORT_PATTERN.search(url))

    if is_embed:
        # Already an embed URL - no need to resolve
        return ResolvedGoogleMap(
            original_url=url,
            resolved_url=url,
            embed_url=url,
            is_embed=True,
        )

    if not is_short:
        # Not a recognized Google Maps URL at all
        return ResolvedGoogleMap(
            original_url=url,
            resolved_url=url,
            embed_url=url,
            is_embed=False,
        )

    # Step 1: Follow redirects
    resolved_url = await _fetch_with_redirects(url)
    if not resolved_url:
        return ResolvedGoogleMap(
            original_url=url,
            resolved_url=None,
            embed_url=None,
            is_embed=False,
        )

    # Step 2: Try Embed API to get stable embed URL
    embed_url = await _call_embed_api(url, resolved_url)

    # Fall back to the resolved direct URL as embed
    if not embed_url:
        # Use the resolved URL as-is for the embed
        embed_url = resolved_url

    return ResolvedGoogleMap(
        original_url=url,
        resolved_url=resolved_url,
        embed_url=embed_url,
        is_embed=False,
    )
