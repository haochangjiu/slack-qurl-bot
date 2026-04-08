"""
Resolve Google Maps short URLs (maps.app.goo.gl) to full embed URLs.

Flow:
  1. Follow HTTP redirect chain to resolve the short URL to a full maps.google.com URL.
  2. If a Maps Embed API key is available, call the Embed API with the resolved URL's
     place name (q= parameter) to get a stable embed iframe src:
       https://www.google.com/maps/embed/v1/place?key=...&q=...
     This format is stable and doesn't expire.
  3. Fall back to the resolved direct URL when no API key is configured.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
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
    is_embed: bool            # Whether original was already an embed URL


async def _fetch_with_redirects(url: str, timeout: float = 30.0) -> str | None:
    """
    Make a HEAD request following redirects to resolve the final URL.
    Falls back to GET if HEAD is not supported.
    Returns the final resolved URL (from the response URL), or None on failure.
    """
    logger.info(f"[google_maps_resolver] Fetching with redirects: {url}")
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
        ) as client:
            # Prefer HEAD to avoid downloading body
            try:
                resp = await client.head(url)
            except httpx.UnsupportedProtocol:
                # Some servers reject HEAD; retry with GET
                resp = await client.get(url)
            resolved = str(resp.url)
            logger.info(f"[google_maps_resolver] Resolved URL: {resolved} (status: {resp.status_code})")
            return resolved
    except Exception as e:
        logger.warning(f"[google_maps_resolver] Failed to resolve Google Maps URL {url}: {e}")
        return None


def _extract_place_name(url: str) -> str | None:
    """
    从 resolved URL 中提取地点名称，用于 Embed API 的 q= 参数。

    URL 格式:
      https://www.google.com.hk/maps/place/地点名称/@lat,lng,zoom/...
      https://www.google.com/maps/place/地点名称/@lat,lng,zoom/data=...
    """
    m = re.search(r"/place/([^/@?]+)", url)
    if m:
        name = m.group(1)
        try:
            decoded = urllib.parse.unquote(name)
            logger.info(f"[google_maps_resolver] Place name extracted: {decoded}")
            return decoded
        except Exception:
            logger.warning(f"[google_maps_resolver] Failed to decode place name: {name}")
            return name
    logger.info(f"[google_maps_resolver] No place name found in URL: {url}")
    return None


def _extract_directions_coords(url: str) -> dict | None:
    """
    从 /dir/ URL 中提取起点和终点坐标，用于 Embed API 的 directions 模式。

    URL 格式:
      https://www.google.com/maps/dir/lat1,lng1/lat2,lng2/@center_lat,lng,zoom/data=...
    返回 {"origin": "lat,lng", "destination": "lat,lng"} 或 None。
    """
    m = re.search(r"/dir/([^@]+)@", url)
    if not m:
        return None
    parts = m.group(1).split("/")
    if len(parts) < 2:
        return None
    origin = parts[0].rstrip("/")
    destination = parts[1].rstrip("/")
    logger.info(f"[google_maps_resolver] Directions coords extracted: origin={origin}, destination={destination}")
    return {"origin": origin, "destination": destination}


def _extract_place_id(url: str) -> str | None:
    """Extract place ID from a Google Maps URL.

    The actual place ID lives in the data= param as 0x... format, e.g.
      /data=!3m1!4b1!4m6!3m5!1s0x80dcf08fba64fd89:0xe42eb4bc7001fa15!...
    or at the end of the URL as !...!XdHash after @lat,lng,zoom format.
    Falls back to /place/ slug only if it starts with 0x (looks like a real ID).
    """
    logger.info(f"[google_maps_resolver] Attempting to extract place_id from URL: {url}")

    # data=!3m1!4b1!4m6!3m5!1s0x80dcf08fba64fd89:0xe42eb4bc7001fa15!8m2...
    # !3m1 !4b1 !4m6 = (?:![^!]*){3}  → 吞掉前3个 segment
    # !1s 后紧跟 place_id（0x...:0x... 或 ChIJ...），到下一个 ! 截止
    m = re.search(r"data=[^!]*(?:![^!]*){3}!(1s([^!]+))", url)
    if m:
        candidate = m.group(2)  # group(2) = 内容在 1s 之后，不含 1s
        if candidate.startswith("0x") or candidate.startswith("ChIJ"):
            logger.info(f"[google_maps_resolver] place_id extracted via data= pattern: {candidate}")
            return candidate

    # Pattern: /place/PLACE_ID/ — only use if it looks like a real place ID
    m = re.search(r"/place/([^/@?]+)/", url)
    if m:
        candidate = m.group(1)
        if candidate.startswith("0x"):
            logger.info(f"[google_maps_resolver] place_id extracted via /place/ pattern: {candidate}")
            return candidate

    # @lat,lng,zoom place: /@lat,lng,.../.../(PLACE_NAME)/...
    m = re.search(r"@[-0-9.,]+/[^/]+/([^/]+)/", url)
    if m:
        name = m.group(1)
        if name.startswith("0x"):
            logger.info(f"[google_maps_resolver] place_id extracted via @ pattern: {name}")
            return name

    logger.warning(f"[google_maps_resolver] No place_id found in URL: {url}")
    return None


async def _call_embed_api(short_url: str, resolved_url: str) -> str | None:
    """
    Use Google Maps Embed API to generate a stable embed iframe src URL.

    Requires GOOGLE_MAPS_EMBED_API_KEY in config.
    Embed API 不需要标准 place_id，直接用 q= 查询即可。
    返回 embed iframe src:
      - place 模式: https://www.google.com/maps/embed/v1/place?key=...&q=...
      - directions 模式: https://www.google.com/maps/embed/v1/directions?key=...&origin=...&destination=...
    """
    api_key = getattr(settings, "google_maps_embed_api_key", None) or None
    logger.info(f"[google_maps_resolver] google_maps_embed_api_key is set: {bool(api_key)}")
    if not api_key:
        logger.warning("[google_maps_resolver] No GOOGLE_MAPS_EMBED_API_KEY configured, skipping embed API call")
        return None

    embed_url = None

    # 模式 A: /dir/ 导航链接
    coords = _extract_directions_coords(resolved_url)
    if coords:
        embed_url = (
            f"https://www.google.com/maps/embed/v1/directions"
            f"?key={api_key}"
            f"&origin={coords['origin']}"
            f"&destination={coords['destination']}"
        )
        logger.info(f"[google_maps_resolver] Using directions embed mode: {embed_url}")

    # 模式 B: /place/ 地点链接
    else:
        place_name = _extract_place_name(resolved_url)
        logger.info(f"[google_maps_resolver] Extracted place_name for embed API: {place_name}")
        if not place_name:
            logger.warning(f"[google_maps_resolver] Could not extract place name from resolved URL: {resolved_url}")
            return None
        embed_url = f"https://www.google.com/maps/embed/v1/place?key={api_key}&q={urllib.parse.quote(place_name)}"
        logger.info(f"[google_maps_resolver] Using place embed mode: {embed_url}")

    # 调用 Embed API（GET 请求，返回 HTML body 即成功）
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(15.0),
            follow_redirects=True,
        ) as client:
            resp = await client.get(embed_url)
            logger.info(f"[google_maps_resolver] Embed API response status: {resp.status_code}, body_preview: {resp.text[:300]}")
            if resp.status_code == 200 and resp.text:
                logger.info(f"[google_maps_resolver] Embed API call successful, returning embed_url: {embed_url}")
                return embed_url
            else:
                logger.warning(f"[google_maps_resolver] Embed API returned non-200 or empty body: {resp.status_code}")
    except Exception as e:
        logger.warning(f"[google_maps_resolver] Embed API call failed for {short_url}: {e}")

    return None


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
        logger.warning(f"[google_maps_resolver] Embed API returned None, falling back to resolved URL: {resolved_url}")
        embed_url = resolved_url
    else:
        logger.info(f"[google_maps_resolver] Successfully generated embed URL via API")

    logger.info(f"[google_maps_resolver] Final result | original: {url} | resolved: {resolved_url} | embed: {embed_url}")
    return ResolvedGoogleMap(
        original_url=url,
        resolved_url=resolved_url,
        embed_url=embed_url,
        is_embed=False,
    )
