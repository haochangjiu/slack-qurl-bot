"""Client for mint_link API (generate qurl_link from resource_id)."""

import logging
from dataclasses import dataclass

import httpx

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class MintLinkResult:
    success: bool
    links: list[dict]  # [{"qurl_link": "...", "expires_at": "..."}, ...]
    error: str | None


async def mint_links(
    resource_id: str,
    n: int = 1,
    expires_at: str | None = None,
) -> MintLinkResult:
    """
    Create qurl links from resource_id.

    Args:
        resource_id: QURL resource ID (e.g. r_gjjpq8hapvq, rkrdrn7o79c, res_abc123)
        n: Number of links to create (1-10), default 1
        expires_at: ISO 8601 expiry (optional)

    Returns:
        MintLinkResult with links or error
    """
    # Base URL includes path up to (but not) resource_id: e.g. https://get.qurl.link/api/mint_link
    base = (settings.mint_link_api_url or "").rstrip("/")
    if not base:
        return MintLinkResult(success=False, links=[], error="Mint link API not configured")

    url = f"{base}/{resource_id}"
    payload: dict = {}
    if n > 1:
        payload["n"] = min(max(n, 1), 10)
    if expires_at:
        payload["expires_at"] = expires_at

    try:
        # verify=False bypasses SSL certificate validation (use only when server cert has issues)
        async with httpx.AsyncClient(timeout=30.0, verify=False) as client:
            resp = await client.post(url, json=payload or {})

        if resp.status_code != 200:
            data = resp.json() if resp.content else {}
            err = data.get("error", resp.text[:200] or f"HTTP {resp.status_code}")
            return MintLinkResult(success=False, links=[], error=str(err))

        data = resp.json()
        if not data.get("success"):
            return MintLinkResult(
                success=False,
                links=[],
                error=data.get("error", "Mint link failed"),
            )
        links = data.get("links", [])
        if not links:
            return MintLinkResult(success=False, links=[], error="No links returned")
        return MintLinkResult(success=True, links=links, error=None)
    except Exception as e:
        logger.error(f"Mint link API error: {e}")
        return MintLinkResult(success=False, links=[], error=str(e))
